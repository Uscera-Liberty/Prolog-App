# -*- coding: utf-8 -*-
"""Свои пациенты и программы: создание, правила, рекомендации, назначение программы, ограничения."""
import pytest
from fastapi.testclient import TestClient

from app import ontology, store
from app.config import USER_DATA_PATH
from app.main import app

NEW_PATIENT = {
    "fio": "Тестова Анна Петровна", "sex": "Женский", "age": 65, "height": 170, "weight": 95,
    "level": 1, "diagnosis": "Диагноз_Гипертония", "history": "Давление до 150/95",
    "feature": "Сидячая работа", "phone": "+7-900-000-00-00",
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_store(client):
    """После каждого теста хранилище пустое — порядок тестов не важен."""
    yield
    store.save({"patients": {}, "programs": {}})
    ontology.rebuild()


@pytest.fixture
def patient_id(client):
    r = client.post("/api/patients", json=NEW_PATIENT)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def rec(client, query_id, **params):
    r = client.post(f"/api/recommend/{query_id}", json={"params": params})
    assert r.status_code == 200, r.text
    return r.json()


def program_body(client, pid, extra=()):
    """Тело программы из подсказок формы: только подходящие упражнения (+ extra)."""
    form = client.get(f"/api/patients/{pid}/program-form").json()
    suitable = [e["id"] for e in form["exercises"] if e["status"] == "ok"]
    return dict(form["defaults"], exercises=suitable + list(extra))


# ---------------------------------------------------------------- создание и выводы правил
def test_create_patient_and_rules(client, patient_id):
    assert patient_id == "Пациент_Тестова"
    p = client.get(f"/api/patients/{patient_id}").json()
    assert p["user_added"] is True
    assert p["fio"] == NEW_PATIENT["fio"]
    assert p["bmi"] == 32.9
    assert p["diagnosis"]["id"] == "Диагноз_Гипертония"
    assert p["history"] == NEW_PATIENT["history"]
    assert {"Ожирение", "Пожилой"} <= {b["label"] for b in p["badges"]}        # R03, R05
    assert {s["id"] for s in p["specialists"]} == {"Тренер_Белов", "Тренер_Ким"}   # R18
    assert p["program"] is None

    s = client.get("/api/stats").json()
    assert (s["пациенты"], s["безПрограммы"]) == (12, 5)
    assert any(x["id"] == patient_id and x["user_added"] for x in client.get("/api/patients").json())
    assert patient_id in {o["id"] for o in client.get("/api/options/Пациент").json()}


def test_recommendations_for_new_patient(client, patient_id):
    ex = {r["упражнение"] for r in rec(client, "exercises_for_patient", пациент=patient_id)["rows"]}
    assert ex == {"Занятие на велотренажёре", "Ходьба на беговой дорожке", "Скандинавская ходьба"}

    bad = {r["у"]: r for r in rec(client, "contraindicated_for_patient", пациент=patient_id)["rows"]}
    assert set(bad) == {"Упр_ЯгодичныйМостик", "Упр_ПланкаНаФитболе", "Упр_СтановаяТягаСГирей",
                        "Упр_СтойкаНаПодушке"}
    assert "Противопоказано при диагнозе" in bad["Упр_ЯгодичныйМостик"]["причины"]
    assert "Ожирение" in bad["Упр_ПланкаНаФитболе"]["причины"]
    assert "Возраст 60+" in bad["Упр_ПланкаНаФитболе"]["причины"]

    specialists = {r["специалист"] for r in rec(client, "specialist_for_patient", пациент=patient_id)["rows"]}
    assert specialists == {"Белов Артём Игоревич", "Ким Сергей Алексеевич"}
    equipment = [r["инвентарь"] for r in rec(client, "equipment_for_patient", пациент=patient_id, бюджет=5000)["rows"]]
    assert equipment == ["Палки для скандинавской ходьбы"]
    assert rec(client, "can_patient_do", пациент=patient_id, упражнение="Упр_ЯгодичныйМостик") == {"answer": False}
    assert rec(client, "can_patient_do", пациент=patient_id, упражнение="Упр_Велотренажёр") == {"answer": True}
    waiting = {r["пац"] for r in rec(client, "waiting_list")["rows"]}
    assert patient_id in waiting


def test_contraindicated_matches_rules(client, patient_id):
    """Запрос 13 содержит все выводы правила неРекомендуетсяУпражнение (R08–R11)."""
    for pid in [patient_id, "Пациент_Кузнецова", "Пациент_Новиков", "Пациент_Сидоров", "Пациент_Волков"]:
        inferred = {e["id"] for e in client.get(f"/api/patients/{pid}").json()["not_recommended"]}
        listed = {r["у"] for r in rec(client, "contraindicated_for_patient", пациент=pid)["rows"]}
        assert inferred <= listed, pid


def test_duplicate_surname_gets_suffix(client, patient_id):
    r = client.post("/api/patients", json=dict(NEW_PATIENT, fio="Тестова Мария"))
    assert r.status_code == 201
    assert r.json()["id"] == "Пациент_Тестова2"


def test_surname_of_base_patient_not_reused(client):
    r = client.post("/api/patients", json=dict(NEW_PATIENT, fio="Иванов Пётр"))
    assert r.json()["id"] == "Пациент_Иванов2"
    assert client.get("/api/patients/Пациент_Иванов").json()["fio"] == "Иванов Иван Иванович"


# ---------------------------------------------------------------- валидация
@pytest.mark.parametrize("change", [
    {"age": -1}, {"age": 121}, {"age": "abc"}, {"age": 30.5},
    {"height": 50}, {"weight": 10}, {"level": 6}, {"level": 0},
    {"diagnosis": "Диагноз_Несуществующий"}, {"diagnosis": "Пациент_Иванов"},
    {"diagnosis": "Диагноз_Гипертония } . ?a ?b ?c"},
    {"fio": ""}, {"fio": "   "}, {"fio": "1"}, {"fio": "x" * 101}, {"sex": "Другое"},
    {"history": "a" * 301},
])
def test_invalid_patient_422(client, change):
    r = client.post("/api/patients", json=dict(NEW_PATIENT, **change))
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert client.get("/api/stats").json()["пациенты"] == 11


def test_not_json_object_422(client):
    assert client.post("/api/patients", json=["fio"]).status_code == 422


def test_special_characters_stored_as_text(client):
    fio = 'x } . ?a ?b ?c <script>alert(1)</script>'
    r = client.post("/api/patients", json=dict(NEW_PATIENT, fio=fio))
    assert r.status_code == 201
    pid = r.json()["id"]
    assert pid == "Пациент_X"
    assert client.get(f"/api/patients/{pid}").json()["fio"] == fio
    html = client.get(f"/patients/{pid}").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert rec(client, "exercises_for_patient", пациент=pid)["rows"]


# ---------------------------------------------------------------- изменение и удаление пациента
def test_update_patient_recomputes_rules(client, patient_id):
    r = client.put(f"/api/patients/{patient_id}",
                   json=dict(NEW_PATIENT, age=30, weight=60, level=3, diagnosis="Диагноз_Плоскостопие"))
    assert r.status_code == 200
    p = client.get(f"/api/patients/{patient_id}").json()
    assert not {"Ожирение", "Пожилой"} & {b["label"] for b in p["badges"]}
    assert p["diagnosis"]["id"] == "Диагноз_Плоскостопие"
    assert p["fio"] == NEW_PATIENT["fio"]


def test_delete_patient(client, patient_id):
    assert client.delete(f"/api/patients/{patient_id}").status_code == 200
    assert client.get(f"/api/patients/{patient_id}").status_code == 404
    assert client.get("/api/stats").json()["пациенты"] == 11
    assert client.delete(f"/api/patients/{patient_id}").status_code == 404


@pytest.mark.parametrize("method", ["put", "delete"])
def test_base_patient_is_read_only(client, method):
    kwargs = {"json": NEW_PATIENT} if method == "put" else {}
    r = getattr(client, method)("/api/patients/Пациент_Иванов", **kwargs)
    assert r.status_code == 409
    assert client.get("/patients/Пациент_Иванов/edit").status_code == 409


# ---------------------------------------------------------------- программы
def test_program_form_suggestions(client, patient_id):
    f = client.get(f"/api/patients/{patient_id}/program-form").json()
    assert f["editable"] is True and f["current"] is None
    assert f["defaults"]["specialist"] in {"Тренер_Белов", "Тренер_Ким"}
    assert (f["defaults"]["weeks"], f["defaults"]["per_week"]) == (14, 3)
    assert set(f["defaults"]["exercises"]) == {"Упр_Велотренажёр", "Упр_ХодьбаНаДорожке", "Упр_СкандинавскаяХодьба"}
    statuses = {e["id"]: e["status"] for e in f["exercises"]}
    assert len(statuses) == 15
    assert statuses["Упр_ЯгодичныйМостик"] == "bad" and statuses["Упр_Велотренажёр"] == "ok"
    assert {t["id"] for t in f["templates"]} >= {"Программа_Кузнецова"}


def test_assign_safe_program(client, patient_id):
    r = client.post(f"/api/patients/{patient_id}/program", json=program_body(client, patient_id))
    assert r.status_code == 201
    program_id = r.json()["id"]
    assert program_id == "Программа_Тестова"
    p = client.get(f"/api/patients/{patient_id}").json()
    assert p["program"]["id"] == program_id and p["program"]["user_added"]
    assert p["program"]["badges"] == []
    assert p["program"]["goals"][0]["id"] == "Цель_ПрофилактикаОсложненийГипертонии"
    s = client.get("/api/stats").json()
    assert (s["программы"], s["программыСРиском"], s["безПрограммы"]) == (8, 3, 4)
    assert patient_id not in {r["пац"] for r in rec(client, "waiting_list")["rows"]}
    assert rec(client, "replace_exercise", пациент=patient_id)["rows"] == []


def test_assign_risky_program_then_replace_and_delete(client, patient_id):
    body = program_body(client, patient_id, extra=["Упр_ЯгодичныйМостик"])
    assert client.post(f"/api/patients/{patient_id}/program", json=body).status_code == 201
    p = client.get(f"/api/patients/{patient_id}").json()
    assert "Программа с риском" in {b["label"] for b in p["program"]["badges"]}        # R16
    assert client.get("/api/stats").json()["программыСРиском"] == 4
    audit = rec(client, "audit_programs")["rows"]
    assert len(audit) == 4 and any(r["пр"] == "Программа_Тестова" for r in audit)
    replacements = rec(client, "replace_exercise", пациент=patient_id)["rows"]
    assert replacements and all(r["проблемное"] == "Ягодичный мостик" for r in replacements)

    # замена программы: та же программа, без опасного упражнения
    r = client.post(f"/api/patients/{patient_id}/program", json=program_body(client, patient_id))
    assert r.json()["id"] == "Программа_Тестова"
    assert client.get("/api/stats").json()["программыСРиском"] == 3
    assert client.get("/api/stats").json()["программы"] == 8

    assert client.delete(f"/api/patients/{patient_id}/program").status_code == 200
    assert client.get(f"/api/patients/{patient_id}").json()["program"] is None
    assert patient_id in {r["пац"] for r in rec(client, "waiting_list")["rows"]}
    assert client.delete(f"/api/patients/{patient_id}/program").status_code == 404


def test_program_for_base_patient_without_program(client):
    body = program_body(client, "Пациент_Новиков")
    r = client.post("/api/patients/Пациент_Новиков/program", json=body)
    assert r.status_code == 201
    assert r.json()["id"] == "Программа_Новиков"
    assert "Пациент_Новиков" not in {r["пац"] for r in rec(client, "waiting_list")["rows"]}
    assert client.delete("/api/patients/Пациент_Новиков/program").status_code == 200


def test_base_program_is_read_only(client):
    body = program_body(client, "Пациент_Новиков")
    assert client.post("/api/patients/Пациент_Иванов/program", json=body).status_code == 409
    assert client.delete("/api/patients/Пациент_Иванов/program").status_code == 409
    assert client.get("/api/patients/Пациент_Иванов/program-form").json()["editable"] is False


@pytest.mark.parametrize("change", [
    {"exercises": []}, {"exercises": ["Упр_Несуществующее"]}, {"exercises": "Упр_КошкаКорова"},
    {"exercises": ["Упр_КошкаКорова } . ?a ?b ?c"]},
    {"specialist": "Пациент_Иванов"}, {"weeks": 0}, {"weeks": 53}, {"per_week": 8}, {"name": ""},
])
def test_invalid_program_422(client, patient_id, change):
    body = dict(program_body(client, patient_id), **change)
    assert client.post(f"/api/patients/{patient_id}/program", json=body).status_code == 422
    assert client.get(f"/api/patients/{patient_id}").json()["program"] is None


def test_program_for_unknown_patient_404(client):
    assert client.post("/api/patients/Пациент_Никто/program", json={"exercises": []}).status_code == 404


def test_deleting_patient_removes_program(client, patient_id):
    client.post(f"/api/patients/{patient_id}/program", json=program_body(client, patient_id))
    client.delete(f"/api/patients/{patient_id}")
    s = client.get("/api/stats").json()
    assert (s["пациенты"], s["программы"]) == (11, 7)
    assert store.load() == {"patients": {}, "programs": {}}


# ---------------------------------------------------------------- хранение
def test_data_persisted_and_reloaded(client, patient_id):
    client.post(f"/api/patients/{patient_id}/program", json=program_body(client, patient_id))
    assert USER_DATA_PATH.is_file()
    ontology.rebuild()                       # как после перезапуска сервера: граф из .owl + файл
    p = client.get(f"/api/patients/{patient_id}").json()
    assert p["fio"] == NEW_PATIENT["fio"] and p["program"]["id"] == "Программа_Тестова"


def test_owl_untouched(client, patient_id):
    from app.config import OWL_PATH
    assert "Тестова" not in OWL_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------- страницы
def test_pages(client, patient_id):
    for path in ["/patients/new", f"/patients/{patient_id}", f"/patients/{patient_id}?new=1",
                 f"/patients/{patient_id}/edit", "/patients/Пациент_Новиков", "/patients/Пациент_Иванов"]:
        r = client.get(path)
        assert r.status_code == 200, path
    html = client.get(f"/patients/{patient_id}").text
    assert "Добавлен вручную" in html and 'id="program-form"' in html and 'id="delete-patient"' in html
    assert 'id="program-form"' not in client.get("/patients/Пациент_Иванов").text
    assert "Подобрать программу для себя" in client.get("/").text
    assert client.get("/patients/Пациент_Никто/edit").status_code == 404
