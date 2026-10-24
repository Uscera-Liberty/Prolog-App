# -*- coding: utf-8 -*-
"""Тесты API и страниц (раздел «Тесты» в CLAUDE.md)."""
import json
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app.config import EXPECTED_PATH
from app.main import app, registry

EXPECTED = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:       # with — чтобы отработал lifespan (загрузка графа)
        yield c


def normalize(query_id, result):
    """Мультимножество строк; значения GROUP_CONCAT разбиваются по разделителю и сортируются."""
    concat = registry.get(query_id)["group_concat"]

    def cell(col, v):
        if col in concat and isinstance(v, str):
            return tuple(sorted(v.split(concat[col])))
        return v

    cols = sorted(result["columns"])
    rows = Counter(tuple(cell(c, row.get(c)) for c in cols) for row in result["rows"])
    return set(result["columns"]), rows


def assert_matches_expected(query_id, got):
    expected = EXPECTED[query_id]
    if "answer" in expected:
        assert got == {"answer": expected["answer"]}
        return
    exp_cols, exp_rows = normalize(query_id, expected)
    got_cols, got_rows = normalize(query_id, got)
    assert got_cols == exp_cols
    assert got_rows == exp_rows


# ---------------------------------------------------------------- 12 запросов против эталона
def test_all_expected_queries_registered():
    assert set(registry.by_id) == set(EXPECTED)
    assert len(registry.queries) == 12


@pytest.mark.parametrize("query_id", sorted(EXPECTED))
def test_recommend_defaults_match_expected(client, query_id):
    r = client.post(f"/api/recommend/{query_id}", json={"params": {}})
    assert r.status_code == 200, r.text
    assert_matches_expected(query_id, r.json())


@pytest.mark.parametrize("query_id", sorted(EXPECTED))
def test_recommend_explicit_defaults_match_expected(client, query_id):
    meta = next(q for q in client.get("/api/queries").json() if q["id"] == query_id)
    params = {p["name"]: p["default"] for p in meta["params"]}
    r = client.post(f"/api/recommend/{query_id}", json={"params": params})
    assert r.status_code == 200, r.text
    assert_matches_expected(query_id, r.json())


def test_recommend_without_body_uses_defaults(client):
    r = client.post("/api/recommend/waiting_list")
    assert r.status_code == 200
    assert_matches_expected("waiting_list", r.json())


def test_recommend_other_patient(client):
    r = client.post("/api/recommend/specialist_for_patient", json={"params": {"пациент": "Пациент_Сидоров"}})
    assert r.status_code == 200
    names = {row["специалист"] for row in r.json()["rows"]}
    assert names == {"Орлов Виктор Семёнович"}      # разрыв связки требует врача — тренеров нет


def test_budget_parameter_filters(client):
    r = client.post("/api/recommend/equipment_for_patient",
                    json={"params": {"пациент": "Пациент_Лебедева", "бюджет": 1000}})
    assert r.status_code == 200
    assert [row["инвентарь"] for row in r.json()["rows"]] == ["Массажный мяч с шипами 8 см"]


def test_iri_columns_marked(client):
    r = client.post("/api/recommend/exercises_for_patient", json={"params": {}})
    assert r.json()["iri_columns"] == ["у"]


# ---------------------------------------------------------------- безопасность параметров
@pytest.mark.parametrize("params", [
    {"пациент": "Пациент_X } . ?a ?b ?c"},
    {"пациент": "Пациент_Несуществующий"},
    {"пациент": "Диагноз_Плоскостопие"},                 # экземпляр не того класса
    {"пациент": "<http://evil/x>"},
])
def test_bad_individual_param_422(client, params):
    r = client.post("/api/recommend/exercises_for_patient", json={"params": params})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)


@pytest.mark.parametrize("budget", ["abc", "5000 } FILTER(true)", "inf", "nan"])
def test_bad_number_param_422(client, budget):
    r = client.post("/api/recommend/equipment_for_patient", json={"params": {"бюджет": budget}})
    assert r.status_code == 422


def test_unknown_query_404(client):
    r = client.post("/api/recommend/no_such_query", json={"params": {}})
    assert r.status_code == 404


def test_malformed_body_422(client):
    r = client.post("/api/recommend/waiting_list", json={"params": "не словарь"})
    assert r.status_code == 422


# ---------------------------------------------------------------- справочники
def test_stats(client):
    s = client.get("/api/stats").json()
    assert s["пациенты"] == 11
    assert s["безПрограммы"] == 4
    assert s["программы"] == 7
    assert s["программыСРиском"] == 3
    assert s["упражнения"] == 15
    assert s["специалисты"] == 5
    assert s["инвентарь"] == 10


@pytest.mark.parametrize("cls,count", [
    ("Пациент", 11), ("Диагноз", 8), ("ЦельРеабилитации", 8), ("Упражнение", 15),
])
def test_options(client, cls, count):
    r = client.get(f"/api/options/{cls}")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == count
    assert all(o["id"] and o["label"] for o in data)


def test_options_unknown_class_404(client):
    assert client.get("/api/options/НетТакогоКласса").status_code == 404


def test_queries_metadata(client):
    data = client.get("/api/queries").json()
    assert len(data) == 12
    by_id = {q["id"]: q for q in data}
    eq = by_id["equipment_for_patient"]
    assert [p["name"] for p in eq["params"]] == ["пациент", "бюджет"]
    assert eq["params"][0]["type"] == "individual" and len(eq["params"][0]["options"]) == 11
    assert eq["params"][1] == {"name": "бюджет", "type": "number", "class": None, "default": "5000"}
    assert by_id["can_patient_do"]["card"] == {"boolean": True}
    assert by_id["program_for_patient"]["card"]["warn"] == "неПодходит"
    assert all(q["title"] and q["button"] and q["description"] for q in data)


def test_patients(client):
    data = client.get("/api/patients").json()
    assert len(data) == 11
    by_id = {p["id"]: p for p in data}
    assert by_id["Пациент_Новиков"]["program"] is None
    labels = {b["label"] for b in by_id["Пациент_Кузнецова"]["badges"]}
    assert {"Ожирение", "Пожилой", "Программа с риском"} <= labels


def test_patient_profile(client):
    p = client.get("/api/patients/Пациент_Иванов").json()
    assert p["fio"] == "Иванов Иван Иванович"
    assert p["diagnosis"]["mkb"] == "M42.1"
    assert p["program"]["label"] == "Укрепление мышц спины"
    bad = {e["label"] for e in p["program"]["exercises"] if e["bad"]}
    assert bad == {"Планка с упором на фитбол"}
    assert client.get("/api/patients/Пациент_Нет").status_code == 404


@pytest.mark.parametrize("kind,count", [
    ("exercises", 15), ("specialists", 5), ("equipment", 10), ("programs", 7),
])
def test_catalog(client, kind, count):
    r = client.get(f"/api/catalog/{kind}")
    assert r.status_code == 200
    assert len(r.json()) == count


def test_catalog_unknown_404(client):
    assert client.get("/api/catalog/drugs").status_code == 404


# ---------------------------------------------------------------- HTML-страницы
@pytest.mark.parametrize("path", [
    "/", "/patients", "/patients/Пациент_Новиков", "/patients/Пациент_Кузнецова",
    "/recommend", "/recommend?q=equipment_for_patient", "/recommend?q=can_patient_do&run=1",
    "/catalog", "/catalog?tab=programs",
])
def test_pages_200(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert '<html lang="ru">' in r.text


def test_index_has_all_query_buttons(client):
    html = client.get("/").text
    for meta in registry.queries:
        assert meta["button"] in html


def test_patient_page_has_patient_queries(client):
    html = client.get("/patients/Пациент_Новиков").text
    for qid in ["exercises_for_patient", "program_for_patient", "specialist_for_patient",
                "equipment_for_patient", "replace_exercise", "similar_patients", "schedule_for_patient"]:
        assert f'data-query="{qid}"' in html
    assert 'data-query="audit_programs"' not in html


def test_unknown_patient_page_404(client):
    r = client.get("/patients/Пациент_Никто")
    assert r.status_code == 404
    assert "не найден" in r.text
