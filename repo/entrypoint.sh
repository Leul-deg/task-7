#!/bin/sh
# StudioOps container entrypoint
# Runs migrations, seeds admin, then starts gunicorn.
set -e

echo "[entrypoint] Running database migrations …"
flask db upgrade

echo "[entrypoint] Seeding admin account …"
flask seed admin

echo "[entrypoint] Starting gunicorn …"
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - \
    --error-logfile - \
    "app:create_app('production')"
