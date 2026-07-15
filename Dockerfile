FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system bot && adduser --system --ingroup bot bot
COPY requirements.txt .
RUN pip install --requirement requirements.txt

COPY app ./app
COPY scripts ./scripts
RUN mkdir -p data/backups data/tmp logs && chown -R bot:bot /app

USER bot
CMD ["python", "-m", "app.main"]

