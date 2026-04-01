FROM python:3.10-slim

WORKDIR /app

# System deps needed to compile Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (including gunicorn for production)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==21.2.0

# Copy application source
COPY app/            ./app/
COPY migrations/     ./migrations/
COPY entrypoint.sh   ./entrypoint.sh

RUN chmod +x /app/entrypoint.sh

# Runtime directories (overridden by volume mounts in compose)
RUN mkdir -p /data/db /data/uploads /data/backups /data/logs

# Environment defaults (override via docker-compose or -e flags)
ENV FLASK_APP=app \
    FLASK_ENV=production \
    DATABASE_URL="sqlite:////data/db/studioops.db" \
    LOG_DIR=/data/logs \
    LOG_FILE=/data/logs/app.log \
    UPLOAD_FOLDER=/data/uploads

EXPOSE 5000

ENTRYPOINT ["/app/entrypoint.sh"]
