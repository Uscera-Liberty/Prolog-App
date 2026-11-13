# -*- coding: utf-8 -*-
"""Тесты работают с пустым временным хранилищем пользовательских данных — реальный data/ не трогается."""
import os
import tempfile

# до импорта app.config: путь к данным читается при импорте
os.environ["REHAB_DATA_DIR"] = tempfile.mkdtemp(prefix="rehab-test-data-")
