# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/config.env.example ./config/config.env.example
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Data/config are always mounted as volumes in docker-compose.yml, but create
# the directories so the image also runs standalone (docker run) without them.
RUN mkdir -p /app/data /app/config

WORKDIR /app/src

# Documentation only - the actual bind port is controlled by $SCLOUD_PORT
# (see docker/entrypoint.sh and docker-compose.yml), which defaults to 5125.
EXPOSE 5125

ENTRYPOINT ["/entrypoint.sh"]
