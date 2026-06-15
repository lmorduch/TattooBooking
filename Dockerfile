# ABOUTME: Multi-stage Docker build — React frontend then FastAPI backend.
# ABOUTME: Frontend is served as static files from FastAPI in production.

# ── Stage 1: Build frontend ────────────────────────────────────────────────
FROM node:20-slim AS frontend
ENV NODE_ENV=development
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install -g npm@latest && npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Production image ──────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Chromium system dependencies (Debian slim doesn't have ttf-ubuntu-font-family)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libcairo2 libatspi2.0-0 libwayland-client0 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* \
    && playwright install chromium

COPY backend/ .

# Built React app
COPY --from=frontend /app/frontend/dist ../frontend/dist/

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
