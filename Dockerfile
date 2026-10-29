# --- 1. Build the React app ---------------------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2. Django API that also serves the built app --------------------------------------------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_DEBUG=false \
    PORT=8000
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
RUN useradd --create-home app && mkdir -p /tmp/truck-routing-cache && chown app /tmp/truck-routing-cache
USER app
EXPOSE 8000
CMD gunicorn config.wsgi --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 120 --access-logfile -
