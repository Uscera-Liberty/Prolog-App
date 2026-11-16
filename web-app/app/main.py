# -*- coding: utf-8 -*-
"""FastAPI: страницы (Jinja2) и JSON API рекомендательной системы."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import actions, ontology, store
from .sparql import ParamError, Registry, local_name, param_class, run_query, validate_params
from .store import Conflict, NotFound, StoreError

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
    "contraindicated_for_patient": "⛔",
}
DEFAULT_ICON = "🔎"
ACCENT_QUERY = "waiting_list"
PATIENT_PARAM = "пациент"

# «Персональный подбор» на странице пациента — запускается сразу при открытии, в этом порядке
SUMMARY_QUERIES = [
    "exercises_for_patient",
    "contraindicated_for_patient",
    "specialist_for_patient",
    "equipment_for_patient",
    "schedule_for_patient",
    "program_for_patient",
]

LEVELS = [
    (1, "1 — минимальная: почти не двигаюсь"),
    (2, "2 — низкая: короткие прогулки"),
    (3, "3 — средняя: зарядка, регулярные прогулки"),
    (4, "4 — хорошая: тренируюсь 2–3 раза в неделю"),
    (5, "5 — высокая: спорт, активные тренировки"),
]

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
    return JSONResponse({"detail": "Некорректное тело запроса: ожидается JSON-объект "
                                   "(для рекомендаций — {\"params\": {…}})"},
                        status_code=422)


def _call(fn, *args):
    """Ошибки хранилища → HTTP: 422 — плохие данные, 409 — данные из OWL, 404 — нет объекта."""
    try:
        return fn(*args)
    except StoreError as e:
        raise HTTPException(422, str(e))
    except Conflict as e:
        raise HTTPException(409, str(e))
    except NotFound as e:
        raise HTTPException(404, str(e))


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


@app.post("/api/patients", status_code=201)
def api_create_patient(payload: dict[str, Any] = Body(...)):
    patient_id = _call(actions.create_patient, payload)
    return {"id": patient_id, "url": f"/patients/{patient_id}"}


@app.post("/api/diagnoses", status_code=201)
def api_create_diagnosis(payload: dict[str, Any] = Body(...)):
    diagnosis_id = _call(actions.create_diagnosis, payload)
    diagnosis = next(d for d in ontology.diagnoses() if d["id"] == diagnosis_id)
    return diagnosis


@app.put("/api/patients/{patient_id}")
def api_update_patient(patient_id: str, payload: dict[str, Any] = Body(...)):
    _call(actions.update_patient, patient_id, payload)
    return {"id": patient_id, "url": f"/patients/{patient_id}"}


@app.delete("/api/patients/{patient_id}")
def api_delete_patient(patient_id: str):
    _call(actions.delete_patient, patient_id)
    return {"deleted": patient_id}


@app.get("/api/patients/{patient_id}/program-form")
def api_program_form(patient_id: str):
    if ontology.patient(patient_id) is None:
        raise HTTPException(404, f"Пациент «{patient_id}» не найден")
    return program_form(patient_id)


@app.post("/api/patients/{patient_id}/program", status_code=201)
def api_assign_program(patient_id: str, payload: dict[str, Any] = Body(...)):
    program_id = _call(actions.assign_program, patient_id, payload)
    return {"id": program_id, "patient": patient_id}


@app.delete("/api/patients/{patient_id}/program")
def api_delete_program(patient_id: str):
    _call(actions.delete_program, patient_id)
    return {"deleted": True}


def program_form(patient_id):
    """Подсказки для формы «Назначить программу» — из рекомендательных запросов 01, 13, 04, 09, 03."""
    params = {PATIENT_PARAM: patient_id}
    p = ontology.patient(patient_id)
    suitable = {r["у"]: r for r in recommend("exercises_for_patient", params)["rows"]}
    bad = {r["у"]: r for r in recommend("contraindicated_for_patient", params)["rows"]}
    ranked = [r["с"] for r in recommend("specialist_for_patient", params)["rows"]]
    schedule = recommend("schedule_for_patient", params)["rows"]
    templates_rows = recommend("program_for_patient", params)["rows"]

    equipment_catalog = {item["id"]: item for item in ontology.catalog_equipment()}
    exercises = []
    for e in ontology.catalog_exercises():
        reasons = bad.get(e["id"], {}).get("причины", "")
        # Жёсткий запрет определяется по графу знаний, а не по тексту пояснения.
        diagnosis = ontology.diagnosis_of(ontology.P(patient_id))
        blocked = (any(diagnosis in ontology.objects(c, "противопоказаноПри")
                       for c in ontology.objects(ontology.P(e["id"]), "имеетПротивопоказание"))
                   or e["status"] == "Приостановлено")
        # Любое ограничение имеет приоритет над положительной рекомендацией.
        status = ("blocked" if blocked else "bad" if e["id"] in bad
                  else "ok" if e["id"] in suitable else "neutral")
        equipment_details = []
        for item in e["equipment"]:
            detail = equipment_catalog.get(item["id"], {})
            equipment_details.append({
                "label": item["label"], "price": detail.get("price"),
                "rules": detail.get("rules", []),
            })
        exercises.append({
            "id": e["id"], "label": e["label"], "difficulty": e["difficulty"],
            "equipment": ", ".join(x["label"] for x in e["equipment"]) or None,
            "equipment_details": equipment_details,
            "sets": e["sets"], "reps": e["reps"], "minutes": e["minutes"],
            "technique": e["technique"], "side_effects": e["side_effects"],
            "status": status,
            "rating": suitable.get(e["id"], {}).get("рейтинг"),
            "reasons": reasons,
        })
    order = {"ok": 0, "neutral": 1, "bad": 2, "blocked": 3}
    exercises.sort(key=lambda e: (order[e["status"]], -(e["rating"] or 0), e["label"]))

    all_specialists = {s["id"]: s for s in ontology.catalog_specialists()}
    # В форме остаются только специалисты, которых вернул SPARQL-запрос для диагноза.
    specialists = [{"id": sid, "label": all_specialists[sid]["label"],
                    "type": all_specialists[sid]["type"], "recommended": True}
                   for sid in ranked if sid in all_specialists]

    programs = {pr["id"]: pr for pr in ontology.catalog_programs()}
    template_list = [{
        "id": r["пр"], "label": r["программа"], "match": r["совпадение"], "unsuitable": r["неПодходит"],
        "exercises": [e["id"] for e in programs.get(r["пр"], {}).get("exercises", [])],
    } for r in templates_rows if r["пр"] in programs]

    current = p["program"]
    surname = p["fio"].split()[0]
    if current:
        defaults = {"name": current["label"],
                    "specialist": current["specialist"]["id"] if current["specialist"] else None,
                    "weeks": current["weeks"], "per_week": current["per_week"],
                    "exercises": [e["id"] for e in current["exercises"]]}
    else:
        defaults = {"name": f"Программа для {surname}",
                    "specialist": ranked[0] if ranked else (specialists[0]["id"] if specialists else None),
                    "weeks": round(schedule[0]["недель"]) if schedule else 8,
                    "per_week": round(schedule[0]["занятийВНеделю"]) if schedule else 3,
                    # Автоматически включаем только упражнения без противопоказаний и оговорок.
                    "exercises": [e["id"] for e in exercises if e["status"] == "ok"]}
    return {
        "editable": (current is None or current["user_added"]) and bool(specialists),
        "no_specialist": not bool(specialists),
        "current": current,
        "defaults": defaults,
        "exercises": exercises,
        "specialists": specialists,
        "templates": template_list,
    }


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


def _patient_form_page(request, patient=None, patient_id=None):
    return templates.TemplateResponse(request, "patient_form.html", {
        "active": "new", "patient": patient or {}, "patient_id": patient_id,
        "diagnoses": ontology.diagnoses(), "levels": LEVELS, "sexes": store.SEXES,
    })


@app.get("/patients/new", response_class=HTMLResponse)
def page_patient_new(request: Request):
    return _patient_form_page(request)


@app.get("/patients/{patient_id}/edit", response_class=HTMLResponse)
def page_patient_edit(request: Request, patient_id: str):
    data = ontology.user_data()["patients"].get(patient_id)
    if data is None:
        if ontology.is_instance(patient_id, "Пациент"):
            raise HTTPException(409, "Это пациент из базы знаний (OWL) — его данные изменить нельзя")
        raise HTTPException(404, f"Пациент «{patient_id}» не найден")
    return _patient_form_page(request, data, patient_id)


@app.get("/patients/{patient_id}", response_class=HTMLResponse)
def page_patient(request: Request, patient_id: str, new: Optional[str] = None, saved: Optional[str] = None):
    data = ontology.patient(patient_id)
    if data is None:
        raise HTTPException(404, f"Пациент «{patient_id}» не найден")
    queries = [q for q in all_queries() if any(p["name"] == PATIENT_PARAM for p in q["params"])]
    summary = [qid for qid in SUMMARY_QUERIES if any(q["id"] == qid for q in queries)]
    return templates.TemplateResponse(request, "patient.html", {
        "active": "patients", "p": data, "queries": queries, "patient_param": PATIENT_PARAM,
        "summary": summary, "form": program_form(patient_id), "is_new": new == "1", "saved": saved,
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
