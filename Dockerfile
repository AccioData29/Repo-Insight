# --- Etapa 1: compilar la interfaz ---
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && npm run build:report

# --- Etapa 2: API + interfaz compilada ---
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m app
WORKDIR /srv
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY --from=web /web/dist ./frontend/dist
COPY --from=web /web/dist-report ./frontend/dist-report
ENV FRONTEND_DIST=/srv/frontend/dist REPORT_TEMPLATE=/srv/frontend/dist-report/index.html WORK_DIR=/tmp/repo-insight
USER app
WORKDIR /srv/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
