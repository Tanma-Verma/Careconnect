FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --uid 10001 --create-home careconnect && mkdir -p /data/documents && chown -R careconnect:careconnect /data

FROM base AS test
USER root
COPY backend/requirements-test.txt /app/requirements-test.txt
RUN pip install --no-cache-dir -r requirements-test.txt
COPY backend/app /app/app
COPY frontend /app/frontend
COPY backend/tests /app/tests
COPY backend/scripts /app/scripts
CMD ["python", "-m", "pytest", "-q", "tests"]

FROM base AS runtime
COPY backend/app /app/app
COPY backend/scripts /app/scripts
COPY frontend /app/frontend
USER careconnect
EXPOSE 3000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
