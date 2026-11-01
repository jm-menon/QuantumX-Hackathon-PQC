FROM python:3.12-slim

ARG APP_DIR=servers/p1
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY ${APP_DIR}/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY servers/shared /app/shared
COPY ${APP_DIR}/apps /app/apps

EXPOSE 8000
CMD ["uvicorn", "apps.main:app", "--host", "0.0.0.0", "--port", "8000"]
