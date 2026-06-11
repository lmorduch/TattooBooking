# ABOUTME: Multi-stage Docker build — React frontend then FastAPI backend.
# ABOUTME: Frontend is served as static files from FastAPI in production.

# ── Stage 1: Build frontend ────────────────────────────────────────────────
FROM node:20-slim AS frontend
ENV NODE_ENV=development
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install -g npm@latest && npm ci --registry https://registry.npmjs.org
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Production image ──────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Built React app
COPY --from=frontend /app/frontend/dist ../frontend/dist/

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
