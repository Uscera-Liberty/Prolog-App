# Образ веб-приложения «Подбор реабилитационной программы».
# Контекст сборки — КОРЕНЬ репозитория (нужны и web-app/, и knowledge-base/):
#   docker build -f web-app/Dockerfile -t rehab-web-app .
# или проще:  cd web-app && docker compose up --build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REHAB_KB_DIR=/srv/knowledge-base \
    REHAB_DATA_DIR=/srv/data

WORKDIR /srv/web-app

# зависимости отдельным слоем — пересобираются только при изменении requirements.txt
COPY web-app/requirements.txt .
RUN pip install -r requirements.txt

# база знаний (онтология, правила, запросы, эталоны) и код приложения
COPY knowledge-base/ /srv/knowledge-base/
COPY web-app/ /srv/web-app/

# /srv/data — пациенты и программы, добавленные через интерфейс (user_data.json)
RUN useradd --create-home --uid 1000 rehab \
    && mkdir -p /srv/data \
    && chown -R rehab /srv/web-app /srv/data
USER rehab

EXPOSE 8000

# порт берётся из $PORT (его задаёт хостинг, например Render), по умолчанию 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/stats', timeout=4)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
