# -*- coding: utf-8 -*-
"""
Реестр рекомендательных запросов queries/recommend/*.rq: разбор заголовка, проверка параметров,
подстановка и запуск.

parse_query_file, bind_params, param_value, to_py, run_query перенесены из scripts/check_queries.py
(эталонный код) без изменения логики. Тексты запросов в Python не хранятся — всё берётся из .rq.
"""
import math
import re
import threading
from decimal import Decimal
from pathlib import Path

from rdflib import Literal, URIRef

from .config import QUERIES_DIR

LOCAL_NAME_RE = re.compile(r"^[0-9A-Za-zА-Яа-яЁё_]+$")
GROUP_CONCAT_RE = re.compile(
    r'GROUP_CONCAT\s*\((?:[^()]|\([^()]*\))*?SEPARATOR\s*=\s*"([^"]*)"\s*\)\s*AS\s+\?(\w+)', re.S)

_query_lock = threading.Lock()


class ParamError(ValueError):
    """Недопустимое значение параметра запроса (→ HTTP 422)."""


# ---------------------------------------------------------------- из scripts/check_queries.py
def parse_query_file(path):
    """Читает заголовок (# key: value) и текст запроса."""
    text = open(path, encoding="utf-8").read()
    meta = {"params": [], "file": Path(path).name}
    for line in text.splitlines():
        m = re.match(r"^#\s*(\w+):\s*(.*)$", line)
        if not m:
            if line.strip() and not line.startswith("#"):
                break
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "param":
            name, ptype, default = [x.strip() for x in val.split("|")]
            meta["params"].append({"name": name, "type": ptype, "default": default})
        else:
            meta[key] = val
    meta["kind"] = "ask" if re.search(r"^\s*ASK\b", text, re.M) else "select"
    meta["text"] = text
    return meta


def bind_params(text, values):
    """Подставляет значения в строки вида  VALUES ?x { ... }   # PARAM имя."""
    def repl(m):
        name = m.group(3)
        if name not in values:
            return m.group(0)
        return f"{m.group(1)}{{ {values[name]} }}{m.group(2)}"
    return re.sub(r"^(\s*VALUES\s+\?\S+\s+)\{[^}]*\}(\s*#\s*PARAM\s+(\S+).*)$", repl, text, flags=re.M)


def param_value(ptype, raw):
    """Проверяет и приводит значение параметра к SPARQL-терму (защита от инъекций)."""
    raw = str(raw).strip()
    if ptype.startswith("individual"):
        local = raw.split(":", 1)[1] if raw.startswith("reh:") else raw.split("#")[-1]
        if not LOCAL_NAME_RE.match(local):
            raise ValueError(f"Недопустимое имя экземпляра: {raw}")
        return f"reh:{local}"
    if ptype == "number":
        return str(float(raw)) if "." in raw else str(int(raw))
    raise ValueError(ptype)


def to_py(v):
    if v is None:
        return None
    if isinstance(v, URIRef):
        return str(v).split("#")[-1]
    if isinstance(v, Literal):
        p = v.toPython()
        if isinstance(p, Decimal):
            p = float(p)
        if isinstance(p, float):
            p = round(p, 2)
        return p if isinstance(p, (int, float, bool)) else str(p)
    return str(v)


def run_query(g, meta, values=None):
    vals = {p["name"]: param_value(p["type"], (values or {}).get(p["name"], p["default"]))
            for p in meta["params"]}
    q = bind_params(meta["text"], vals)
    with _query_lock:
        res = g.query(q)
        if meta["kind"] == "ask":
            return {"answer": bool(res.askAnswer)}
        cols = [str(v) for v in res.vars]
        raw_rows = list(res)
    rows = [{c: to_py(r[c]) for c in cols} for r in raw_rows]
    # колонки-IRI (?у, ?пр, ?с …) — служебные: ключ/ссылка, на карточке не показываются
    iri_cols = [c for c in cols if any(isinstance(r[c], URIRef) for r in raw_rows)]
    return {"columns": cols, "rows": rows, "iri_columns": iri_cols}


# ---------------------------------------------------------------- метаданные
def parse_card(spec):
    """'title=a; score=b; fields=x,y' → {'title': 'a', 'score': 'b', 'fields': ['x', 'y']}."""
    spec = (spec or "").strip()
    if spec == "boolean":
        return {"boolean": True}
    card = {}
    for part in spec.split(";"):
        if "=" not in part:
            continue
        key, val = (x.strip() for x in part.split("=", 1))
        card[key] = [f.strip() for f in val.split(",") if f.strip()] if key == "fields" else val
    return card


def group_concat_columns(text):
    """{колонка: разделитель} для агрегатов GROUP_CONCAT(... SEPARATOR="…") AS ?колонка."""
    return {col: sep for sep, col in GROUP_CONCAT_RE.findall(text)}


def param_class(ptype):
    """'individual:Пациент' → 'Пациент'; для number — None."""
    return ptype.split(":", 1)[1] if ptype.startswith("individual:") else None


def local_name(value):
    value = str(value).strip()
    return value.split(":", 1)[1] if value.startswith("reh:") else value.split("#")[-1]


class Registry:
    """Все запросы из queries/recommend/*.rq, по порядку имён файлов."""

    def __init__(self, directory=QUERIES_DIR):
        self.queries = []
        for path in sorted(Path(directory).glob("*.rq")):
            meta = parse_query_file(path)
            if "id" not in meta:
                continue
            meta["card_spec"] = parse_card(meta.get("card"))
            meta["group_concat"] = group_concat_columns(meta["text"])
            self.queries.append(meta)
        self.by_id = {q["id"]: q for q in self.queries}

    def get(self, query_id):
        return self.by_id.get(query_id)


def validate_params(meta, raw_params, is_instance):
    """
    Проверяет пользовательские значения и возвращает {имя: значение} для run_query.
    is_instance(local, класс) → bool — существует ли экземпляр класса (с учётом подклассов).
    Отсутствующий параметр берёт значение по умолчанию из заголовка; лишние ключи игнорируются.
    """
    raw_params = raw_params or {}
    values = {}
    for p in meta["params"]:
        name, ptype = p["name"], p["type"]
        raw = raw_params.get(name)
        if raw is None or str(raw).strip() == "":
            raw = p["default"]
        raw = str(raw).strip()
        if ptype.startswith("individual"):
            try:
                param_value(ptype, raw)
            except ValueError:
                raise ParamError(f"Параметр «{name}»: недопустимое имя экземпляра «{raw}»")
            cls = param_class(ptype)
            local = local_name(raw)
            if cls and not is_instance(local, cls):
                raise ParamError(f"Параметр «{name}»: экземпляр «{local}» класса «{cls}» не найден")
            values[name] = local
        elif ptype == "number":
            try:
                num = float(raw.replace(",", "."))
            except ValueError:
                raise ParamError(f"Параметр «{name}»: нужно число, получено «{raw}»")
            if not math.isfinite(num):
                raise ParamError(f"Параметр «{name}»: нужно конечное число")
            values[name] = str(int(num)) if num.is_integer() else f"{num:.6f}"
        else:
            raise ParamError(f"Параметр «{name}»: неизвестный тип «{ptype}»")
    return values
