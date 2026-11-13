# -*- coding: utf-8 -*-
"""
Пациенты и программы, добавленные через интерфейс.

Хранятся отдельно от базы знаний — в JSON-файле $REHAB_DATA_DIR/user_data.json — и при каждой
сборке графа добавляются к онтологии тройками той же формы, что у экземпляров из OWL. Файл .owl
не изменяется. Значения попадают в граф только как rdflib.Literal / URIRef проверенных имён,
поэтому в SPARQL-запросы пользовательский текст не подставляется никогда.
"""
import json
import os
import re
import tempfile
import threading
from datetime import datetime
from decimal import Decimal

from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD

from .config import USER_DATA_PATH
from .sparql import LOCAL_NAME_RE

NS = "http://www.semanticweb.org/rehab/ontologies/2026/rehab-program#"
SEXES = ("Мужской", "Женский")
TEXT_FIELDS = {"phone": "Телефон", "history": "Анамнез", "feature": "Особенности"}
MAX_EXERCISES = 15

lock = threading.RLock()          # изменения: выбор id + запись файла + пересборка графа


class StoreError(ValueError):
    """Недопустимые данные (→ HTTP 422)."""


class Conflict(Exception):
    """Нельзя изменить данные из базы знаний (→ HTTP 409)."""


class NotFound(Exception):
    """Нет такого пациента или программы (→ HTTP 404)."""


def P(name):
    return URIRef(NS + name)


# ---------------------------------------------------------------- файл
def load():
    try:
        data = json.loads(USER_DATA_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    data.setdefault("patients", {})
    data.setdefault("programs", {})
    return data


def save(data):
    USER_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=USER_DATA_PATH.parent, prefix=".user_data.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, USER_DATA_PATH)


def program_of_patient(data, patient_id):
    return next((pid for pid, pr in data["programs"].items() if pr["patient"] == patient_id), None)


# ---------------------------------------------------------------- проверка
def _text(raw, label, lo, hi, required=True):
    value = re.sub(r"\s+", " ", str(raw if raw is not None else "")).strip()
    if not value:
        if required:
            raise StoreError(f"Поле «{label}» обязательно")
        return None
    if any(ord(c) < 32 for c in value):
        raise StoreError(f"Поле «{label}» содержит недопустимые символы")
    if not lo <= len(value) <= hi:
        raise StoreError(f"Поле «{label}»: длина от {lo} до {hi} символов")
    return value


def _number(raw, label, lo, hi, integer=True):
    try:
        num = float(str(raw).replace(",", ".").strip())
    except (TypeError, ValueError):
        raise StoreError(f"Поле «{label}»: нужно число")
    if num != num or not lo <= num <= hi:
        raise StoreError(f"Поле «{label}»: допустимо от {lo} до {hi}")
    if integer:
        if not num.is_integer():
            raise StoreError(f"Поле «{label}»: нужно целое число")
        return int(num)
    return round(num, 1)


def _individual(raw, label, cls, is_instance):
    value = str(raw or "").strip()
    if not LOCAL_NAME_RE.match(value) or not is_instance(value, cls):
        raise StoreError(f"Поле «{label}»: выберите значение из списка")
    return value


def validate_patient(raw, is_instance):
    raw = raw or {}
    sex = str(raw.get("sex") or "").strip()
    if sex not in SEXES:
        raise StoreError("Поле «Пол»: выберите «Мужской» или «Женский»")
    fio = _text(raw.get("fio"), "ФИО", 2, 100)
    if not re.search(r"[A-Za-zА-Яа-яЁё]", fio):
        raise StoreError("Поле «ФИО» должно содержать буквы")
    patient = {
        "fio": fio,
        "sex": sex,
        "age": _number(raw.get("age"), "Возраст", 1, 120),
        "height": _number(raw.get("height"), "Рост, см", 100, 230),
        "weight": _number(raw.get("weight"), "Вес, кг", 20, 300, integer=False),
        "level": _number(raw.get("level"), "Уровень подготовки", 1, 5),
        "diagnosis": _individual(raw.get("diagnosis"), "Диагноз", "Диагноз", is_instance),
    }
    for key, label in TEXT_FIELDS.items():
        patient[key] = _text(raw.get(key), label, 1, 300, required=False)
    return patient


def validate_program(raw, is_instance):
    raw = raw or {}
    exercises = raw.get("exercises")
    if not isinstance(exercises, list) or not exercises:
        raise StoreError("Выберите хотя бы одно упражнение")
    if len(exercises) > MAX_EXERCISES:
        raise StoreError(f"Не больше {MAX_EXERCISES} упражнений в программе")
    checked = []
    for e in exercises:
        e = _individual(e, "Упражнения", "Упражнение", is_instance)
        if e not in checked:
            checked.append(e)
    return {
        "name": _text(raw.get("name"), "Название программы", 1, 120),
        "specialist": _individual(raw.get("specialist"), "Специалист", "Специалист", is_instance),
        "weeks": _number(raw.get("weeks"), "Длительность, недель", 1, 52),
        "per_week": _number(raw.get("per_week"), "Занятий в неделю", 1, 7),
        "exercises": checked,
    }


def make_key(fio, taken):
    """Ключ экземпляров из первого слова ФИО: «Маслаева Юлия» → Маслаева (Маслаева2, …)."""
    words = [re.sub(r"[^0-9A-Za-zА-Яа-яЁё]", "", w) for w in fio.split()]
    base = next((w for w in words if w), "") or "Пользователь"
    base = base[:40]
    base = base[0].upper() + base[1:]
    key, n = base, 1
    while taken(key):
        n += 1
        key = f"{base}{n}"
    return key


# ---------------------------------------------------------------- тройки для графа
def add_triples(g, data):
    """Добавляет пациентов и программы из хранилища в граф (до применения правил)."""
    for pid, p in data["patients"].items():
        key = p["key"]
        patient, pdata = P(pid), P(f"Данные_{key}")
        g.add((patient, RDF.type, P("Пациент")))
        g.add((patient, RDF.type, OWL.NamedIndividual))
        g.add((patient, P("ФИО"), Literal(p["fio"], datatype=XSD.string)))
        g.add((patient, P("пол"), Literal(p["sex"], datatype=XSD.string)))
        g.add((patient, P("возраст"), Literal(int(p["age"]), datatype=XSD.integer)))
        g.add((patient, P("ростСм"), Literal(int(p["height"]), datatype=XSD.integer)))
        g.add((patient, P("весКг"), Literal(Decimal(str(p["weight"])), datatype=XSD.decimal)))
        g.add((patient, P("уровеньПодготовки"), Literal(int(p["level"]), datatype=XSD.integer)))
        if p.get("phone"):
            g.add((patient, P("телефон"), Literal(p["phone"], datatype=XSD.string)))
        g.add((patient, P("имеетДанные"), pdata))
        g.add((pdata, RDF.type, P("ДанныеПациента")))
        g.add((pdata, RDF.type, OWL.NamedIndividual))
        g.add((pdata, P("содержитДиагноз"), P(p["diagnosis"])))
        for field, cls, prefix, prop in (("history", "ИсторияБолезни", "Анамнез", "содержитИсториюБолезни"),
                                         ("feature", "ИндивидуальнаяОсобенность", "Особенность",
                                          "содержитОсобенность")):
            if p.get(field):
                node = P(f"{prefix}_{key}")
                g.add((node, RDF.type, P(cls)))
                g.add((node, RDF.type, OWL.NamedIndividual))
                g.add((node, P("описание"), Literal(p[field], datatype=XSD.string)))
                g.add((pdata, P(prop), node))

    for prid, pr in data["programs"].items():
        program, patient = P(prid), P(pr["patient"])
        g.add((program, RDF.type, P("РеабилитационнаяПрограмма")))
        g.add((program, RDF.type, OWL.NamedIndividual))
        g.add((program, P("название"), Literal(pr["name"], datatype=XSD.string)))
        g.add((program, P("предназначенаДля"), patient))
        g.add((program, P("основанаНаОпытеСпециалиста"), P(pr["specialist"])))
        g.add((program, P("длительностьНедель"), Literal(int(pr["weeks"]), datatype=XSD.integer)))
        g.add((program, P("занятийВНеделю"), Literal(int(pr["per_week"]), datatype=XSD.integer)))
        g.add((program, P("датаНазначения"),
               Literal(datetime.fromisoformat(pr["assigned"]), datatype=XSD.dateTime)))
        for e in pr["exercises"]:
            g.add((program, P("содержитУпражнение"), P(e)))
        pdata = g.value(patient, P("имеетДанные"))
        if pdata is not None:
            g.add((program, P("учитываетДанныеПациента"), pdata))
            history = g.value(pdata, P("содержитИсториюБолезни"))
            if history is not None:
                g.add((program, P("основанаНаИсторииБолезни"), history))
            diagnosis = g.value(pdata, P("содержитДиагноз"))
            for goal in g.objects(diagnosis, P("требуетЦели")) if diagnosis is not None else ():
                g.add((program, P("имеетЦель"), goal))
