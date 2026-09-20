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
# Migrations aren't committed to the repo, so they're (re)generated here.
# This is idempotent: once applied, Django's django_migrations table means
# re-running migrate on an unchanged schema is a no-op.
cd /app/src
echo "[entrypoint] Preparing database..."
python manage.py makemigrations accounts storage --noinput
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
    --workers "${GUNICORN_WORKERS:-4}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-600}"
