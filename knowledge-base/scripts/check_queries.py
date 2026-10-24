# -*- coding: utf-8 -*-
"""
Проверка онтологии, правил и рекомендательных запросов без Protégé (только rdflib).

Запуск из корня пакета:   python3 scripts/check_queries.py            — краткий отчёт
                          python3 scripts/check_queries.py --full     — все строки результатов
                          python3 scripts/check_queries.py --write    — обновить expected/expected_results.json

Что делает:
  1. Загружает ontology/rehab_program.owl.
  2. Применяет rules/materialize_rules.ru до неподвижной точки и сравнивает выводы
     с expected/pellet_inferences.json (вывод Pellet по SWRL-правилам).
  3. Запускает каждый запрос queries/recommend/*.rq со значениями параметров по умолчанию
     и печатает результат. Этот же код — эталон для веб-приложения (см. CLAUDE.md).
"""
import json
import os
import re
import sys
from decimal import Decimal

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NS = "http://www.semanticweb.org/rehab/ontologies/2026/rehab-program#"
OWL_PATH = os.path.join(ROOT, "ontology", "rehab_program.owl")
RULES_PATH = os.path.join(ROOT, "rules", "materialize_rules.ru")
QUERIES_DIR = os.path.join(ROOT, "queries", "recommend")

LOCAL_NAME_RE = re.compile(r"^[0-9A-Za-zА-Яа-яЁё_]+$")


# ---------------------------------------------------------------- загрузка
def load_graph(materialize=True):
    g = Graph()
    g.parse(OWL_PATH, format="xml")
    if materialize:
        rules = open(RULES_PATH, encoding="utf-8").read()
        before = -1
        while len(g) != before:          # до неподвижной точки
            before = len(g)
            # initNs обязателен: rdflib не переносит PREFIX на операции после ';'
            g.update(rules, initNs={"reh": NS, "xsd": "http://www.w3.org/2001/XMLSchema#"})
    return g


# ---------------------------------------------------------------- запросы
def parse_query_file(path):
    """Читает заголовок (# key: value) и текст запроса."""
    text = open(path, encoding="utf-8").read()
    meta = {"params": [], "file": os.path.basename(path)}
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
    res = g.query(q)
    if meta["kind"] == "ask":
        return {"answer": bool(res.askAnswer)}
    cols = [str(v) for v in res.vars]
    rows = [{c: to_py(r[c]) for c in cols} for r in res]
    return {"columns": cols, "rows": rows}


def load_queries():
    return [parse_query_file(os.path.join(QUERIES_DIR, f))
            for f in sorted(os.listdir(QUERIES_DIR)) if f.endswith(".rq")]


# ---------------------------------------------------------------- проверка правил
def compare_with_pellet(g):
    path = os.path.join(ROOT, "expected", "pellet_inferences.json")
    if not os.path.exists(path):
        print("pellet_inferences.json не найден — пропуск сравнения"); return True
    exp = json.load(open(path, encoding="utf-8"))
    ok = True
    for key, expected in exp.items():
        if key.startswith("весПри"):
            got = sorted([to_py(s), round(float(o), 2)] for s, o in g.subject_objects(URIRef(NS + key)))
            expected = sorted([a, round(b, 2)] for a, b in expected)
        elif key[0].isupper():   # класс
            got = sorted(to_py(s) for s in g.subjects(RDF.type, URIRef(NS + key)))
        else:                    # объектное свойство
            got = sorted([to_py(s), to_py(o)] for s, o in g.subject_objects(URIRef(NS + key)))
            expected = sorted(expected)
        same = got == expected
        ok &= same
        print(f"  {'OK ' if same else 'ERR'} {key}: {len(got)}")
        if not same:
            print("     ожидалось:", expected, "\n     получено:  ", got)
    return ok


if __name__ == "__main__":
    full = "--full" in sys.argv
    g = load_graph()
    print(f"Троек после применения правил: {len(g)}")
    print("Сравнение с Pellet:")
    rules_ok = compare_with_pellet(g)

    results = {}
    for meta in load_queries():
        r = run_query(g, meta)
        results[meta["id"]] = r
        if "answer" in r:
            print(f"\n[{meta['file']}] {meta['title']}  →  ASK = {r['answer']}")
            continue
        print(f"\n[{meta['file']}] {meta['title']}  →  строк: {len(r['rows'])}")
        for row in (r["rows"] if full else r["rows"][:4]):
            print("   ", {k: v for k, v in row.items() if v is not None})
    if "--write" in sys.argv:
        out = os.path.join(ROOT, "expected", "expected_results.json")
        json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\nЗаписано:", out)
    sys.exit(0 if rules_ok else 1)
