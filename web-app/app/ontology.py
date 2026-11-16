# -*- coding: utf-8 -*-
"""
Граф онтологии (загружается один раз, правила применяются до неподвижной точки) и справочники
для страниц: пациенты, каталог, статистика, бейджи из выведенных SWRL-правилами классов.

Граф = онтология из .owl + пациенты/программы из пользовательского хранилища (app/store.py),
к которым применены правила. В .owl ничего не сохраняется — выводы живут в памяти. После каждого
изменения пользовательских данных граф собирается заново (rebuild): правила только добавляют факты,
поэтому после удаления пациента или программы выводы нужно пересчитать с нуля.
"""
import threading
from datetime import date, datetime

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from . import store
from .config import KB_DIR, OWL_PATH, RULES_PATH
from .sparql import LOCAL_NAME_RE, to_py

NS = "http://www.semanticweb.org/rehab/ontologies/2026/rehab-program#"
XSD = "http://www.w3.org/2001/XMLSchema#"

# выведенный класс → (подпись бейджа, вид бейджа для CSS)
BADGES = [
    ("ПациентСОжирением", "Ожирение", "danger"),
    ("ПациентСИзбыточнымВесом", "Избыточный вес", "warn"),
    ("ПожилойПациент", "Пожилой", "info"),
    ("ОптимальноеУпражнение", "Оптимальное", "ok"),
    ("ЭффективноеУпражнение", "Эффективное", "eff"),
    ("БезопасноеУпражнение", "Безопасное", "info"),
    ("УпражнениеСОсторожностью", "С осторожностью", "danger"),
    ("ПрограммаСРиском", "Программа с риском", "danger"),
    ("БюджетныйИнвентарь", "Бюджетный", "ok"),
    ("ОпытныйСпециалист", "Опытный", "ok"),
]

SPECIALIST_TYPES = {"Реабилитолог": "Врач-реабилитолог", "Тренер": "Тренер ЛФК"}

_base = None                      # разобранный .owl без выводов — парсится один раз
_graph = None
_user = {"patients": {}, "programs": {}, "diagnoses": {}}
_graph_lock = threading.Lock()
_instances_cache = {}


# ---------------------------------------------------------------- граф
def _base_graph():
    global _base
    if _base is None:
        if not OWL_PATH.is_file():
            raise FileNotFoundError(f"Онтология не найдена: {OWL_PATH}. Укажите каталог базы знаний "
                                    f"в REHAB_KB_DIR (сейчас: {KB_DIR})")
        g = Graph()
        g.parse(str(OWL_PATH), format="xml")
        _base = g
    return _base


def build_graph(user_data):
    g = Graph()
    g += _base_graph()
    store.add_triples(g, user_data)
    rules = RULES_PATH.read_text(encoding="utf-8")
    before = -1
    while len(g) != before:              # 2–3 прохода до неподвижной точки
        before = len(g)
        # initNs обязателен: rdflib не переносит PREFIX на операции после ';'
        g.update(rules, initNs={"reh": NS, "xsd": XSD})
    return g


def load_graph():
    return build_graph(store.load())


def rebuild(user_data=None):
    """Собрать граф заново (после изменения пользовательских данных) и подменить текущий."""
    global _graph, _user
    data = store.load() if user_data is None else user_data
    new = build_graph(data)
    with _graph_lock:
        _graph, _user = new, data
        _instances_cache.clear()
    return new


def get_graph():
    global _graph, _user
    if _graph is None:
        with _graph_lock:
            if _graph is None:
                data = store.load()
                _graph, _user = build_graph(data), data
    return _graph


def user_data():
    get_graph()
    return _user


def is_user_patient(name):
    return name in user_data()["patients"]


def is_user_diagnosis(name):
    return name in user_data().get("diagnoses", {})


def is_user_program(name):
    return name in user_data()["programs"]


def name_taken(local_name):
    return (P(local_name), None, None) in get_graph()


def P(name):
    """reh:имя → URIRef."""
    return URIRef(NS + name)


def local(u):
    return str(u).split("#")[-1] if u is not None else None


def value(s, prop):
    """Первое значение свойства-данных как Python-значение (или None)."""
    return to_py(get_graph().value(s, P(prop)))


def objects(s, prop):
    return list(get_graph().objects(s, P(prop)))


def label(u):
    if u is None:
        return None
    g = get_graph()
    for prop in ("ФИО", "название", "описание"):
        v = g.value(u, P(prop))
        if v is not None:
            return str(v)
    v = g.value(u, RDFS.label)
    return str(v) if v is not None else local(u)


def ref(u):
    return {"id": local(u), "label": label(u)} if u is not None else None


def refs(nodes):
    return sorted((ref(u) for u in nodes), key=lambda r: r["label"])


def class_types(u):
    return {local(t) for t in get_graph().objects(u, RDF.type)}


def badges(u):
    types = class_types(u)
    return [{"label": text, "kind": kind} for cls, text, kind in BADGES if cls in types]


# ---------------------------------------------------------------- классы и экземпляры
def class_exists(cls):
    return bool(LOCAL_NAME_RE.match(cls)) and (P(cls), RDF.type, OWL.Class) in get_graph()


def instances_of(cls):
    """Локальные имена экземпляров класса с учётом подклассов (rdf:type/rdfs:subClassOf*)."""
    g = get_graph()
    key = (id(g), cls)                # ключ с id графа: после rebuild старый кеш не используется
    if key not in _instances_cache:
        classes = set(g.transitive_subjects(RDFS.subClassOf, P(cls)))
        found = set()
        for c in classes:
            found.update(local(s) for s in g.subjects(RDF.type, c) if isinstance(s, URIRef))
        _instances_cache[key] = frozenset(found)
    return _instances_cache[key]


def is_instance(name, cls):
    return name in instances_of(cls)


def options(cls):
    return sorted(({"id": n, "label": label(P(n))} for n in instances_of(cls)),
                  key=lambda o: o["label"])


# ---------------------------------------------------------------- вспомогательное
def fmt_date(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, str) and len(v) >= 10:
        y, m, d = v[:10].split("-")
        return f"{d}.{m}.{y}"
    return v


def bmi(weight, height):
    if not weight or not height:
        return None
    return round(float(weight) / (float(height) / 100) ** 2, 1)


def program_of(patient):
    return get_graph().value(predicate=P("предназначенаДля"), object=patient)


def diagnosis_of(patient):
    data = get_graph().value(patient, P("имеетДанные"))
    return get_graph().value(data, P("содержитДиагноз")) if data is not None else None


def trial_info(exercise):
    g = get_graph()
    trial = g.value(exercise, P("основаноНаИспытании"))
    if trial is None:
        return {"trial": None, "efficacy": None, "safety": None, "status": None}
    eff = g.value(trial, P("показываетЭффективность"))
    safe = g.value(trial, P("определяетУровеньБезопасности"))
    return {
        "trial": local(trial),
        "efficacy": value(eff, "процентЭффективности") if eff is not None else None,
        "safety": value(safe, "баллБезопасности") if safe is not None else None,
        "status": label(g.value(trial, P("имеетСтатус"))),
    }


def program_card(pr, patient=None):
    """Программа + упражнения; упражнения, не рекомендованные её пациенту, помечены bad=True."""
    g = get_graph()
    owner = g.value(pr, P("предназначенаДля"))
    patient = patient or owner
    bad = set(objects(patient, "неРекомендуетсяУпражнение")) if patient is not None else set()
    exercises = [dict(ref(u), bad=u in bad) for u in objects(pr, "содержитУпражнение")]
    exercises.sort(key=lambda e: (not e["bad"], e["label"]))
    return {
        "id": local(pr),
        "label": label(pr),
        "patient": ref(owner),
        "specialist": ref(g.value(pr, P("основанаНаОпытеСпециалиста"))),
        "goals": refs(objects(pr, "имеетЦель")),
        "weeks": value(pr, "длительностьНедель"),
        "per_week": value(pr, "занятийВНеделю"),
        "assigned": fmt_date(value(pr, "датаНазначения")),
        "exercises": exercises,
        "badges": badges(pr),
        "user_added": is_user_program(local(pr)),
    }


# ---------------------------------------------------------------- справочники для API/страниц
def stats():
    patients = instances_of("Пациент")
    without = [p for p in patients if program_of(P(p)) is None]
    return {
        "пациенты": len(patients),
        "безПрограммы": len(without),
        "программы": len(instances_of("РеабилитационнаяПрограмма")),
        "программыСРиском": len(instances_of("ПрограммаСРиском")),
        "упражнения": len(instances_of("Упражнение")),
        "специалисты": len(instances_of("Специалист")),
        "инвентарь": len(instances_of("СпортивныйИнвентарь")),
    }


def patients():
    result = []
    for name in instances_of("Пациент"):
        p = P(name)
        dg = diagnosis_of(p)
        pr = program_of(p)
        result.append({
            "id": name,
            "fio": label(p),
            "age": value(p, "возраст"),
            "bmi": bmi(value(p, "весКг"), value(p, "ростСм")),
            "diagnosis": ref(dg),
            "program": ref(pr),
            "badges": badges(p) + (badges(pr) if pr is not None else []),
            "user_added": is_user_patient(name),
        })
    return sorted(result, key=lambda r: r["fio"])


def patient(name):
    if not LOCAL_NAME_RE.match(name or "") or not is_instance(name, "Пациент"):
        return None
    g = get_graph()
    p = P(name)
    data = g.value(p, P("имеетДанные"))
    dg = diagnosis_of(p)
    history = g.value(data, P("содержитИсториюБолезни")) if data is not None else None
    feature = g.value(data, P("содержитОсобенность")) if data is not None else None
    pr = program_of(p)
    weight, height = value(p, "весКг"), value(p, "ростСм")
    specialists = [dict(ref(s), type=specialist_type(s), badges=badges(s))
                   for s in objects(p, "рекомендуемыйСпециалист")]
    return {
        "id": name,
        "fio": label(p),
        "sex": value(p, "пол"),
        "birth": fmt_date(value(p, "датаРождения")),
        "age": value(p, "возраст"),
        "phone": value(p, "телефон"),
        "height": height,
        "weight": weight,
        "bmi": bmi(weight, height),
        "weight_bmi25": value(p, "весПриИМТ25"),
        "weight_bmi30": value(p, "весПриИМТ30"),
        "level": value(p, "уровеньПодготовки"),
        "diagnosis": dict(ref(dg), mkb=value(dg, "кодМКБ"),
                          needs_doctor=bool(value(dg, "требуетВрача")),
                          has_recommendations=diagnosis_has_recommendations(dg),
                          user_added=is_user_diagnosis(local(dg))) if dg is not None else None,
        "history": label(history),
        "feature": label(feature),
        "goals": refs(objects(p, "рекомендуемаяЦель")),
        "specialists": sorted(specialists, key=lambda s: s["label"]),
        "suitable": refs(objects(p, "подходитУпражнение")),
        "not_recommended": refs(objects(p, "неРекомендуетсяУпражнение")),
        "equipment": refs(objects(p, "нуженИнвентарь")),
        "program": program_card(pr, p) if pr is not None else None,
        "badges": badges(p),
        "user_added": is_user_patient(name),
    }


def diagnosis_has_recommendations(diagnosis):
    if diagnosis is None:
        return False
    return bool(objects(diagnosis, "требуетЦели")
                or any(diagnosis in objects(indication, "показаноПри")
                       for indication in map(P, instances_of("Показание"))))


def diagnoses():
    """Диагнозы для формы: id, название, код МКБ, нужен ли врач, цель."""
    result = []
    for name in instances_of("Диагноз"):
        d = P(name)
        result.append({
            "id": name,
            "label": label(d),
            "mkb": value(d, "кодМКБ"),
            "needs_doctor": bool(value(d, "требуетВрача")),
            "goals": [g["label"] for g in refs(objects(d, "требуетЦели"))],
            "has_recommendations": diagnosis_has_recommendations(d),
            "user_added": is_user_diagnosis(name),
        })
    return sorted(result, key=lambda r: r["label"])


def specialist_type(s):
    for t in class_types(s):
        if t in SPECIALIST_TYPES:
            return SPECIALIST_TYPES[t]
    return "Специалист"


def catalog_exercises():
    g = get_graph()
    result = []
    for name in instances_of("Упражнение"):
        u = P(name)
        result.append(dict(
            ref(u),
            difficulty=value(u, "уровеньСложности"),
            sets=value(u, "количествоПодходов"),
            reps=value(u, "количествоПовторений"),
            minutes=value(u, "длительностьМин"),
            technique=label(g.value(u, P("имеетТехникуВыполнения"))),
            effects=refs(objects(u, "имеетЭффект")),
            side_effects=refs(objects(u, "имеетПобочныйЭффект")),
            contraindications=refs(objects(u, "имеетПротивопоказание")),
            indications=refs(objects(u, "имеетПоказание")),
            goals=refs(objects(u, "влияетНа")),
            equipment=refs(objects(u, "требуетИнвентарь")),
            badges=badges(u),
            **trial_info(u),
        ))
    return sorted(result, key=lambda r: r["label"])


def catalog_specialists():
    g = get_graph()
    result = []
    for name in instances_of("Специалист"):
        s = P(name)
        programs = list(g.subjects(P("основанаНаОпытеСпециалиста"), s))
        result.append(dict(
            ref(s),
            type=specialist_type(s),
            experience=value(s, "стажЛет"),
            rating=value(s, "рейтинг"),
            specializations=refs(objects(s, "специализируетсяНа")),
            programs=refs(programs),
            badges=badges(s),
        ))
    return sorted(result, key=lambda r: r["label"])


def catalog_equipment():
    g = get_graph()
    result = []
    for name in instances_of("СпортивныйИнвентарь"):
        i = P(name)
        producer = g.value(i, P("имеетПроизводителя"))
        result.append(dict(
            ref(i),
            price=value(i, "цена"),
            producer=label(producer),
            country=value(producer, "страна") if producer is not None else None,
            characteristics=[label(c) for c in objects(i, "имеетХарактеристику")],
            rules=[label(r) for r in objects(i, "имеетПравилаПользования")],
            authors=[label(a) for a in objects(i, "имеетАвтора")],
            exercises=refs(g.subjects(P("требуетИнвентарь"), i)),
            badges=badges(i),
        ))
    return sorted(result, key=lambda r: r["price"] or 0)


def catalog_programs():
    return sorted((program_card(P(n)) for n in instances_of("РеабилитационнаяПрограмма")),
                  key=lambda r: r["label"])


CATALOG = {
    "exercises": catalog_exercises,
    "specialists": catalog_specialists,
    "equipment": catalog_equipment,
    "programs": catalog_programs,
}
