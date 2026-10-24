# knowledge-base — база знаний «Подбор оптимальной реабилитационной программы» (вариант 22)

Это всё, что знает система. Каталог самодостаточен: его можно открыть в Protégé или проверить скриптом без
веб-приложения. Веб-приложение ([`../web-app`](../web-app)) только читает эти файлы.

| Путь | Что это |
|---|---|
| `ontology/rehab_program.owl` | Онтология OWL (RDF/XML) с 22 SWRL-правилами — **единственный источник данных** |
| `ontology/rehab_program.ttl` | То же в Turtle — удобно читать глазами |
| `rules/materialize_rules.ru` | SWRL-правила как SPARQL UPDATE (rdflib не исполняет SWRL) — их применяет веб-приложение |
| `rules/swrl_rules.txt` | Правила в синтаксисе Protégé (справка) |
| `rules/sqwrl_queries.txt` | 8 SQWRL-запросов для SQWRLTab в Protégé |
| `queries/recommend/*.rq` | 12 рекомендательных SPARQL-запросов с метаданными в заголовке (`# id`, `# title`, `# button`, `# param`, `# card`) |
| `queries/ALL_queries_for_protege.txt` | Те же запросы одним файлом — для вкладки SPARQL Query в Protégé |
| `expected/expected_results.json` | Эталонные результаты запросов при параметрах по умолчанию |
| `expected/pellet_inferences.json` | Эталонный вывод правил (Pellet) |
| `docs/MODEL.md` | Описание модели: 44 класса, 46 объектных и 29 свойств-данных, 189 экземпляров, правила, запросы |
| `docs/PROTEGE_GUIDE.md` | Как работать с онтологией в Protégé 5.5 |
| `docs/diagrams/` | Концептуальная модель, диаграмма классов, пример экземпляров (`.dot`, `.png`, `.svg`) |
| `docs/spec/` | Исходное техническое задание на веб-приложение (`CLAUDE_spec.md`) и промпт |
| `scripts/check_queries.py` | Проверка: правила против Pellet + запуск 12 запросов |
| `scripts/build_ontology.py` | Генератор `.owl` — данные меняются только здесь (нужны rdflib, owlready2) |
| `scripts/make_diagrams.py` | Пересборка диаграмм (нужен graphviz) |
| `scripts/install_protege.sh` | Установка Protégé 5.5.0 в Linux |

## Проверка

Команды выполняются из папки `knowledge-base/`:

```bash
pip install rdflib
python3 scripts/check_queries.py            # краткий отчёт: 18 × OK и 12 запросов
python3 scripts/check_queries.py --full     # все строки результатов
```

## Изменение данных

```bash
# 1. правка в scripts/build_ontology.py
python3 scripts/build_ontology.py           # пересобрать ontology/*.owl и *.ttl
python3 scripts/check_queries.py --write    # обновить expected/expected_results.json
```

Пространство имён — `PREFIX reh: <http://www.semanticweb.org/rehab/ontologies/2026/rehab-program#>`. Имена — кириллица в
CamelCase, экземпляры записываются как `Класс_Ключ` (`reh:Пациент_Новиков`, `reh:Упр_КошкаКорова`).
