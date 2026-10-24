# Как открыть всё это в Protégé (Linux Mint)

1. Установка (один раз): `bash scripts/install_protege.sh` — ставит Protégé 5.5.0 в `~/protege`
   (в 5.6.x вкладка SPARQL Query не работает). Запуск: `~/protege/run.sh путь/к/ontology/rehab_program.owl`.
2. Окно обновлений плагинов → **Not now**.
3. **Классы / свойства / экземпляры:** Entities, Individuals by class.
4. **SWRL-правила:** Window → Tabs → **SWRLTab** — там 22 правила R01–R22. Внизу нажать по очереди
   **OWL+SWRL->Drools**, **Run Drools**, **Drools->OWL**. После этого в Individuals by class у пациентов появятся
   выведенные классы (ПациентСОжирением и т.д.) и свойства (подходитУпражнение, рекомендуемыйСпециалист …).
5. **SQWRL:** Window → Tabs → **SQWRLTab** → New → вставить запрос из `rules/sqwrl_queries.txt` → Ok →
   выделить его в списке → **Run** → результат во вкладке S1, S2 …
   (в `sqwrl:columnNames` нельзя ставить запятые — вкладка перестаёт работать до перезапуска Protégé).
6. **SPARQL:** Window → Tabs → **SPARQL Query** → стереть шаблон → вставить файл из `queries/recommend/`
   (или блок из `queries/ALL_queries_for_protege.txt`) целиком → **Execute**.
   Чтобы сменить пациента, поменяй значение в строке `VALUES ?пациент { reh:Пациент_Новиков }`.
   SPARQL в Protégé видит только явно записанные факты — поэтому запросы не зависят от правил и работают сразу.
7. Если что-то правишь руками — File → Save (RDF/XML).
