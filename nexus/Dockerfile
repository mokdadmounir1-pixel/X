# Image unique : API FastAPI + Dashboard compilé. Construire depuis le dossier nexus/.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv
COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api/app ./app
COPY api/migrations ./migrations
COPY --from=web /web/dist /srv/web
RUN useradd --system --uid 10001 nexus && chown -R nexus /srv
USER nexus
ENV NEXUS_WEB_DIR=/srv/web
EXPOSE 8000
CMD ["sh", "-c", "python -m app.cli migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
