#!/bin/sh
# Runs every time the container starts. Idempotent: safe to run on a brand
# new setup, or on the 100th restart of an already-running instance.
set -e

cd /app

# --- 1. First-run config setup ------------------------------------------
if [ ! -f config/config.env ]; then
    echo "[entrypoint] No config/config.env found - creating one from the template."
    cp config/config.env.example config/config.env

    # Generate a real secret key instead of shipping with the placeholder.
    NEW_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
    # Escape characters sed treats specially before substituting.
    ESCAPED_SECRET=$(printf '%s\n' "$NEW_SECRET" | sed -e 's/[\/&]/\\&/g')
    sed -i "s/^SECRET_KEY=.*/SECRET_KEY=${ESCAPED_SECRET}/" config/config.env

    echo "[entrypoint] Generated config/config.env with a random SECRET_KEY."
    echo "[entrypoint] Edit config/config.env (e.g. ALLOWED_HOSTS, email settings) as needed, then restart."
fi

# --- 2. Database setup / migrations --------------------------------------
# Migration FILES are committed to the repo (every machine/deploy applies
# the exact same, byte-identical migration history) - only APPLYING them is
# done here. This used to also run `makemigrations` to generate migration
# files on the fly, since they weren't committed; that let the database
# (persisted in a volume across deploys) and the migration history (baked
# fresh into each image) drift out of sync - a schema change made on one
# machine could get a different migration name/number on another, so
# `migrate` would see a name it already considered "applied" and silently
# skip adding a genuinely-missing column. That's a real outage class, not a
# hypothetical one - don't reintroduce it.
cd /app/src
echo "[entrypoint] Applying database migrations..."
python manage.py migrate --noinput

# --- 3. Static files -------------------------------------------------------
python manage.py collectstatic --noinput >/dev/null

# --- 4. Optional one-time superuser creation ------------------------------
# Set DJANGO_SUPERUSER_USERNAME / _EMAIL / _PASSWORD as environment
# variables (e.g. in a .env file consumed by docker-compose) to have an
# admin account created automatically the first time the container starts.
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "[entrypoint] Ensuring superuser '$DJANGO_SUPERUSER_USERNAME' exists..."
    python manage.py createsuperuser --noinput 2>/dev/null || true
fi

echo "[entrypoint] Starting SCloud on port ${SCLOUD_PORT:-5125}..."
exec gunicorn scloud.wsgi:application \
    --bind "0.0.0.0:${SCLOUD_PORT:-5125}" \
    --worker-class gthread \
    --workers "${GUNICORN_WORKERS:-4}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-600}"
