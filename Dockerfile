FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY bot /app/bot
COPY alembic /app/alembic
COPY alembic.ini pyproject.toml /app/

ENV BOT_APP_KIND=admin

CMD ["python", "-m", "bot.main"]
