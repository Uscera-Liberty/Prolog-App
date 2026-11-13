# -*- coding: utf-8 -*-
"""
Изменение пользовательских данных: пациенты и программы.

Каждое действие под store.lock: проверка → выбор id → сборка нового графа с правилами → запись файла.
Граф собирается до записи: если что-то пошло не так, файл не меняется.
"""
from datetime import datetime

from . import ontology, store
from .store import Conflict, NotFound

PREFIXES = ("Пациент", "Данные", "Анамнез", "Особенность", "Программа")


def _now():
    return datetime.now().replace(microsecond=0).isoformat()


def _commit(data):
    ontology.rebuild(data)
    store.save(data)


def _require_user_patient(data, patient_id):
    if patient_id in data["patients"]:
        return data["patients"][patient_id]
    if ontology.is_instance(patient_id, "Пациент"):
        raise Conflict("Это пациент из базы знаний (OWL) — его данные изменить нельзя. "
                       "Добавьте себя как нового пациента.")
    raise NotFound(f"Пациент «{patient_id}» не найден")


def create_patient(raw):
    with store.lock:
        patient = store.validate_patient(raw, ontology.is_instance)
        data = store.load()
        keys = {p["key"] for p in data["patients"].values()}
        key = store.make_key(patient["fio"], lambda k: k in keys or any(
            ontology.name_taken(f"{prefix}_{k}") for prefix in PREFIXES))
        patient_id = f"Пациент_{key}"
        data["patients"][patient_id] = dict(patient, key=key, created=_now())
        _commit(data)
        return patient_id


def update_patient(patient_id, raw):
    with store.lock:
        data = store.load()
        old = _require_user_patient(data, patient_id)
        patient = store.validate_patient(raw, ontology.is_instance)
        data["patients"][patient_id] = dict(patient, key=old["key"], created=old["created"])
        _commit(data)
        return patient_id


def delete_patient(patient_id):
    with store.lock:
        data = store.load()
        _require_user_patient(data, patient_id)
        del data["patients"][patient_id]
        program_id = store.program_of_patient(data, patient_id)
        if program_id:
            del data["programs"][program_id]
        _commit(data)


def assign_program(patient_id, raw):
    """Назначить программу (или заменить ранее назначенную через интерфейс)."""
    with store.lock:
        if not ontology.is_instance(patient_id, "Пациент"):
            raise NotFound(f"Пациент «{patient_id}» не найден")
        program = store.validate_program(raw, ontology.is_instance)
        data = store.load()
        program_id = store.program_of_patient(data, patient_id)
        if program_id is None:
            if ontology.program_of(ontology.P(patient_id)) is not None:
                raise Conflict("У пациента уже есть программа из базы знаний (OWL) — заменить её нельзя. "
                               "Воспользуйтесь кнопкой «Найти замену упражнениям».")
            key = data["patients"].get(patient_id, {}).get("key") or patient_id.split("_", 1)[-1]
            program_id = f"Программа_{key}"
            n = 1
            while ontology.name_taken(program_id) or program_id in data["programs"]:
                n += 1
                program_id = f"Программа_{key}{n}"
        data["programs"][program_id] = dict(program, patient=patient_id, assigned=_now())
        _commit(data)
        return program_id


def delete_program(patient_id):
    with store.lock:
        data = store.load()
        program_id = store.program_of_patient(data, patient_id)
        if program_id is None:
            if ontology.program_of(ontology.P(patient_id)) is not None:
                raise Conflict("Программа из базы знаний (OWL) — удалить её нельзя")
            raise NotFound("У пациента нет назначенной программы")
        del data["programs"][program_id]
        _commit(data)
