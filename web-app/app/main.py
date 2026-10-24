# -*- coding: utf-8 -*-
"""FastAPI: страницы (Jinja2) и JSON API рекомендательной системы."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import ontology
from .sparql import ParamError, Registry, local_name, param_class, run_query, validate_params

APP_DIR = Path(__file__).resolve().parent

# иконки карточек-кнопок; запрос без иконки (новый .rq) получит значок по умолчанию
QUERY_ICONS = {
    "exercises_for_patient": "🧘",
    "exercises_for_diagnosis": "🩺",
    "program_for_patient": "📋",
    "specialist_for_patient": "👩‍⚕️",
    "equipment_for_patient": "🏋️",
    "replace_exercise": "🔄",
    "audit_programs": "🛡️",
    "similar_patients": "👥",
    "schedule_for_patient": "📅",
    "top_exercises_for_goal": "🏆",
    "waiting_list": "⏳",
    "can_patient_do": "✅",
}
DEFAULT_ICON = "🔎"
ACCENT_QUERY = "waiting_list"
PATIENT_PARAM = "пациент"

STAT_CARDS = [
    ("пациенты", "Пациентов", "🧑", "patient", "/patients"),
    ("безПрограммы", "Ждут программу", "⏳", "warn", "/recommend?q=waiting_list&run=1"),
    ("программы", "Программ", "📋", "program", "/catalog?tab=programs"),
    ("программыСРиском", "Программ с риском", "⚠️", "danger", "/recommend?q=audit_programs&run=1"),
    ("упражнения", "Упражнений", "🧘", "exercise", "/catalog?tab=exercises"),
    ("специалисты", "Специалистов", "👩‍⚕️", "specialist", "/catalog?tab=specialists"),
    ("инвентарь", "Единиц инвентаря", "🏋️", "equipment", "/catalog?tab=equipment"),
]

CATALOG_TABS = [
    ("exercises", "Упражнения"),
    ("specialists", "Специалисты"),
    ("equipment", "Инвентарь"),
    ("programs", "Программы"),
]

registry = Registry()


@asynccontextmanager
async def lifespan(_app):
    ontology.get_graph()          # граф + правила до неподвижной точки — один раз при старте
    yield


app = FastAPI(title="Подбор реабилитационной программы", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


# ---------------------------------------------------------------- ошибки
def _is_api(request: Request):
    return request.url.path.startswith("/api/")


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if _is_api(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    message = exc.detail if exc.status_code != 404 or exc.detail != "Not Found" else "Страница не найдена"
    return templates.TemplateResponse(
        request, "error.html", {"status": exc.status_code, "message": message, "active": None},
        status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "Некорректное тело запроса: ожидается {\"params\": {…}}"},
                        status_code=422)


# ---------------------------------------------------------------- метаданные запросов
def query_public(meta, with_options=True):
    params = []
    for p in meta["params"]:
        cls = param_class(p["type"])
        item = {
            "name": p["name"],
            "type": "individual" if cls else p["type"],
            "class": cls,
            "default": local_name(p["default"]) if cls else p["default"],
        }
        if cls and with_options:
            item["options"] = ontology.options(cls)
        params.append(item)
    return {
        "id": meta["id"],
        "file": meta["file"],
        "title": meta.get("title", meta["id"]),
        "button": meta.get("button", "Выполнить"),
        "description": meta.get("description", ""),
        "kind": meta["kind"],
        "icon": QUERY_ICONS.get(meta["id"], DEFAULT_ICON),
        "params": params,
        "card": meta["card_spec"],
        "group_concat": meta["group_concat"],
    }


def all_queries(with_options=True):
    return [query_public(m, with_options) for m in registry.queries]


def recommend(query_id, params):
    meta = registry.get(query_id)
    if meta is None:
        raise HTTPException(404, f"Запрос «{query_id}» не найден")
    try:
        values = validate_params(meta, params, ontology.is_instance)
        return run_query(ontology.get_graph(), meta, values)
    except (ParamError, ValueError) as e:
        raise HTTPException(422, str(e))


# ---------------------------------------------------------------- API
class RecommendRequest(BaseModel):
    params: dict[str, Any] = {}


@app.get("/api/stats")
def api_stats():
    return ontology.stats()


@app.get("/api/options/{cls}")
def api_options(cls: str):
    if not ontology.class_exists(cls):
        raise HTTPException(404, f"Класс «{cls}» не найден в онтологии")
    return ontology.options(cls)


@app.get("/api/patients")
def api_patients():
    return ontology.patients()


@app.get("/api/patients/{patient_id}")
def api_patient(patient_id: str):
    data = ontology.patient(patient_id)
    if data is None:
        raise HTTPException(404, f"Пациент «{patient_id}» не найден")
    return data


@app.get("/api/catalog/{kind}")
def api_catalog(kind: str):
    if kind not in ontology.CATALOG:
        raise HTTPException(404, f"Раздел каталога «{kind}» не найден "
                                 f"(доступны: {', '.join(ontology.CATALOG)})")
    return ontology.CATALOG[kind]()


@app.get("/api/queries")
def api_queries():
    return all_queries()


@app.post("/api/recommend/{query_id}")
def api_recommend(query_id: str, body: Optional[RecommendRequest] = None):
    return recommend(query_id, body.params if body else {})


# ---------------------------------------------------------------- страницы
@app.get("/", response_class=HTMLResponse)
def page_index(request: Request):
    stats = ontology.stats()
    cards = [dict(key=k, label=l, icon=i, group=g, href=h, value=stats[k]) for k, l, i, g, h in STAT_CARDS]
    return templates.TemplateResponse(request, "index.html", {
        "active": "index", "stats": cards, "queries": all_queries(with_options=False),
        "accent": ACCENT_QUERY,
    })


@app.get("/patients", response_class=HTMLResponse)
def page_patients(request: Request):
    return templates.TemplateResponse(request, "patients.html", {
        "active": "patients", "patients": ontology.patients(),
    })


@app.get("/patients/{patient_id}", response_class=HTMLResponse)
def page_patient(request: Request, patient_id: str):
    data = ontology.patient(patient_id)
    if data is None:
        raise HTTPException(404, f"Пациент «{patient_id}» не найден")
    queries = [q for q in all_queries() if any(p["name"] == PATIENT_PARAM for p in q["params"])]
    return templates.TemplateResponse(request, "patient.html", {
        "active": "patients", "p": data, "queries": queries, "patient_param": PATIENT_PARAM,
    })


@app.get("/recommend", response_class=HTMLResponse)
def page_recommend(request: Request, q: Optional[str] = None):
    queries = all_queries()
    selected = q if q in registry.by_id else queries[0]["id"]
    return templates.TemplateResponse(request, "recommend.html", {
        "active": "recommend", "queries": queries, "selected": selected,
    })


@app.get("/catalog", response_class=HTMLResponse)
def page_catalog(request: Request, tab: str = "exercises"):
    if tab not in ontology.CATALOG:
        tab = "exercises"
    return templates.TemplateResponse(request, "catalog.html", {
        "active": "catalog", "tabs": CATALOG_TABS, "tab": tab,
        "data": {k: f() for k, f in ontology.CATALOG.items()},
    })
