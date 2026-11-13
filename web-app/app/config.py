# -*- coding: utf-8 -*-
"""
Где лежит база знаний (ontology/, rules/, queries/, expected/).

1. Переменная окружения REHAB_KB_DIR, если задана (так работает Docker-образ).
2. Иначе — корень приложения, если там есть ontology/ (исходная раскладка rehab_pack).
3. Иначе — соседний каталог ../knowledge-base (раскладка репозитория web-app + knowledge-base).
"""
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
OWL_RELATIVE = Path("ontology") / "rehab_program.owl"


def _find_kb_dir():
    env = os.environ.get("REHAB_KB_DIR")
    if env:
        return Path(env).expanduser().resolve()
    for candidate in (APP_ROOT, APP_ROOT.parent / "knowledge-base"):
        if (candidate / OWL_RELATIVE).is_file():
            return candidate
    return APP_ROOT.parent / "knowledge-base"


KB_DIR = _find_kb_dir()
OWL_PATH = KB_DIR / OWL_RELATIVE
RULES_PATH = KB_DIR / "rules" / "materialize_rules.ru"
QUERIES_DIR = KB_DIR / "queries" / "recommend"
EXPECTED_PATH = KB_DIR / "expected" / "expected_results.json"

# пациенты и программы, добавленные через интерфейс (база знаний остаётся только для чтения)
DATA_DIR = Path(os.environ.get("REHAB_DATA_DIR") or APP_ROOT / "data").expanduser().resolve()
USER_DATA_PATH = DATA_DIR / "user_data.json"
