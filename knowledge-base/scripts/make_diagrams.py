# -*- coding: utf-8 -*-
"""Рисует диаграммы в docs/diagrams/ (нужен Graphviz: sudo apt install graphviz).
Запуск из корня пакета: python3 scripts/make_diagrams.py"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_ontology as B  # noqa: E402  (импорт не пересобирает OWL — только списки)

OUT = os.path.join(B.ROOT, "docs", "diagrams")
os.makedirs(OUT, exist_ok=True)
FONT = 'fontname="DejaVu Sans"'


def render(name, dot):
    path = os.path.join(OUT, name + ".dot")
    open(path, "w", encoding="utf-8").write(dot)
    for fmt in ("png", "svg"):
        subprocess.run(["dot", f"-T{fmt}", "-Gdpi=110" if fmt == "png" else "-Gdpi=72", path,
                        "-o", os.path.join(OUT, f"{name}.{fmt}")], check=True)
    print("OK", name)


# ---------------------------------------------------------------- 1. концептуальная модель
concept = f'''digraph C {{
graph [rankdir=LR, {FONT}, fontsize=22, labelloc=t, pad=0.4, nodesep=0.5, ranksep=1.0,
       label="Концептуальная модель: рекомендательная система подбора реабилитационной программы"];
node [{FONT}, fontsize=14, shape=box, style="rounded,filled", penwidth=1.4];
edge [{FONT}, fontsize=11, color="#444444"];
subgraph cluster_in {{ label="ВХОД: кто пациент"; style="rounded,dashed"; color="#4b8f4b"; fontsize=14;
  Пациент [fillcolor="#E2F3E1"]; Диагноз [fillcolor="#E2F3E1"]; Анамнез [label="История болезни\\nи особенности", fillcolor="#E2F3E1"]; }}
subgraph cluster_kb {{ label="БАЗА ЗНАНИЙ: что известно о лечении"; style="rounded,dashed"; color="#2f6db3"; fontsize=14;
  Упражнение [fillcolor="#DCEBFA"]; Показание [label="Показание /\\nПротивопоказание", fillcolor="#DCEBFA"];
  Цель [label="Цель\\nреабилитации", fillcolor="#F6E1EC"]; Испытание [label="Клиническое испытание\\n(эффективность, безопасность)", fillcolor="#ECE4F7"];
  Инвентарь [label="Спортивный инвентарь\\n(цена, производитель)", fillcolor="#EFEFEF"]; Специалист [label="Специалист\\n(реабилитолог / тренер)", fillcolor="#E2F3E1"]; }}
subgraph cluster_out {{ label="ВЫХОД: рекомендация"; style="rounded,dashed"; color="#c47a12"; fontsize=14;
  Программа [label="Реабилитационная\\nпрограмма", fillcolor="#FDE9C9", penwidth=3]; }}
Пациент -> Диагноз [label="имеет"]; Пациент -> Анамнез [label="имеет"];
Диагноз -> Цель [label="требует цели"];
Показание -> Диагноз [label="показано / противопоказано при"];
Упражнение -> Показание [label="имеет"]; Упражнение -> Цель [label="влияет на"];
Упражнение -> Испытание [label="основано на"]; Упражнение -> Инвентарь [label="требует"];
Специалист -> Диагноз [label="специализируется на"];
Программа -> Пациент [label="предназначена для"]; Программа -> Упражнение [label="содержит"];
Программа -> Цель [label="имеет цель"]; Программа -> Специалист [label="ведёт"];
Программа -> Анамнез [label="основана на"];
}}'''
render("conceptual_model", concept)


# ---------------------------------------------------------------- 2. диаграмма классов (UML-стиль)
COLORS = {}
for col, names in {
    "#FDE9C9": ["РеабилитационнаяПрограмма", "ПрограммаСРиском"],
    "#DCEBFA": ["Упражнение", "ЭффективноеУпражнение", "БезопасноеУпражнение", "ОптимальноеУпражнение", "УпражнениеСОсторожностью",
                "СвойствоУпражнения", "Противопоказание", "Показание", "ТехникаВыполнения", "Эффект", "ЛечебныйЭффект", "ПобочныйЭффект"],
    "#E2F3E1": ["Пациент", "ПациентСИзбыточнымВесом", "ПациентСОжирением", "ПожилойПациент", "ДанныеПациента", "МедицинскаяИнформация",
                "Диагноз", "ИсторияБолезни", "ИндивидуальнаяОсобенность", "Специалист", "Тренер", "Реабилитолог", "ОпытныйСпециалист"],
    "#F6E1EC": ["ЦельРеабилитации", "УлучшениеКачестваЖизни", "УменьшениеБоли", "ВосстановлениеПослеТравмы", "ПрофилактикаХроническихЗаболеваний"],
    "#ECE4F7": ["КлиническоеИспытание", "РезультатИспытания", "Эффективность", "УровеньБезопасности", "РеакцияПациента", "СтатусИспытания"],
    "#EFEFEF": ["СпортивныйИнвентарь", "БюджетныйИнвентарь", "Производитель", "Автор", "ХарактеристикаИнвентаря", "ПравилаПользования"],
}.items():
    for n in names:
        COLORS[n] = col

attrs = {}
for name, dom, rng, _ in B.DATA:
    t = str(rng).split("#")[-1]
    for cls in ([dom] if dom else []):
        attrs.setdefault(cls, []).append(f"{name}: {t}")
GENERIC = {"Пациент": ["ФИО"], "Специалист": ["ФИО"], "Упражнение": ["название"], "РеабилитационнаяПрограмма": ["название"],
           "Диагноз": ["название"], "ЦельРеабилитации": ["название"], "СпортивныйИнвентарь": ["название"],
           "Производитель": ["название"], "Автор": ["ФИО"]}
for cls, names in GENERIC.items():
    attrs.setdefault(cls, [])
    attrs[cls] = [f"{n}: string" for n in names] + attrs[cls]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


inferred = {n for n, p, c, src in B.CLASSES if src == "правило"}
lines = [f'digraph U {{ graph [rankdir=LR, {FONT}, fontsize=22, labelloc=t, pad=0.4, nodesep=0.25, ranksep=0.7, splines=true, '
         'label="Диаграмма классов онтологии (UML-нотация): атрибуты = свойства-данные, стрелки = объектные свойства, '
         '△ = наследование, пунктир = класс выводится SWRL-правилами"];',
         f'node [shape=plaintext, {FONT}, fontsize=11]; edge [{FONT}, fontsize=9, color="#555555", fontcolor="#1F4E79"];']
for n, p, c, src in B.CLASSES:
    a = "".join(f'<TR><TD ALIGN="LEFT">+ {esc(x)}</TD></TR>' for x in attrs.get(n, []))
    border = 'STYLE="DASHED"' if n in inferred else ""
    stereo = '<TR><TD><FONT POINT-SIZE="9">«выводимый»</FONT></TD></TR>' if n in inferred else ""
    lines.append(f'"{n}" [label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3" BGCOLOR="{COLORS[n]}" {border}>'
                 f'{stereo}<TR><TD><B>{esc(n)}</B></TD></TR><HR/>{a or "<TR><TD> </TD></TR>"}</TABLE>>];')
for n, p, c, src in B.CLASSES:
    if p:
        lines.append(f'"{n}" -> "{p}" [arrowhead=empty, style=dashed, color="#999999"];')
lines.append('"ОптимальноеУпражнение" -> "ЭффективноеУпражнение" [arrowhead=empty, style=dashed, color="#999999"];')
lines.append('"ОптимальноеУпражнение" -> "БезопасноеУпражнение" [arrowhead=empty, style=dashed, color="#999999"];')
for name, d, r, sketch, parent, func, src in B.OBJ:
    if parent:
        continue
    style = ', style=dashed, color="#c47a12", fontcolor="#c47a12"' if src == "правило" else ""
    mult = ' headlabel="1"' if func else ""
    lines.append(f'"{d}" -> "{r}" [label="{name}"{mult}{style}];')
lines.append("}")
render("class_diagram", "\n".join(lines))


# ---------------------------------------------------------------- 3. экземпляры на примере пациента
from rdflib import URIRef  # noqa: E402
g = B.g
N = B.O


def lbl(u):
    return str(u).split("#")[-1]


focus = ["Пациент_Иванов", "Программа_Иванов"]
edges, nodes = set(), set()
for f in focus:
    for p, o in g.predicate_objects(N[f]):
        if isinstance(o, URIRef) and str(o).startswith(str(N)):
            edges.add((f, lbl(p), lbl(o)))
for d in ["Данные_Иванов"]:
    for p, o in g.predicate_objects(N[d]):
        if isinstance(o, URIRef) and str(o).startswith(str(N)):
            edges.add((d, lbl(p), lbl(o)))
for u in ["Упр_КошкаКорова", "Упр_ПланкаНаФитболе", "Упр_ЯгодичныйМостик"]:
    for p in ["имеетПротивопоказание", "требуетИнвентарь", "основаноНаИспытании", "имеетПоказание"]:
        for o in g.objects(N[u], N[p]):
            edges.add((u, p, lbl(o)))
edges.add(("Противопоказание_ОстрыйПериодГрыжи", "противопоказаноПри", "Диагноз_Остеохондроз"))
lines = [f'digraph I {{ graph [rankdir=LR, {FONT}, fontsize=20, labelloc=t, pad=0.4, '
         'label="Экземпляры на примере пациента Иванова (красным — конфликт, который находят правило R16 и запрос 07)"];',
         f'node [shape=box, style="rounded,filled", fillcolor="#F7F7F7", {FONT}, fontsize=11]; edge [{FONT}, fontsize=9];']
for s, p, o in sorted(edges):
    if p == "type":
        continue
    red = ', color="#C0392B", fontcolor="#C0392B", penwidth=2' if (o == "Противопоказание_ОстрыйПериодГрыжи" or
                                                                   (s == "Противопоказание_ОстрыйПериодГрыжи")) else ""
    lines.append(f'"{s}" -> "{o}" [label="{p}"{red}];')
lines.append('"Программа_Иванов" [fillcolor="#FDE9C9"]; "Пациент_Иванов" [fillcolor="#E2F3E1"]; "Упр_ПланкаНаФитболе" [fillcolor="#F5B7B1"];')
lines.append("}")
render("instances_example", "\n".join(lines))
