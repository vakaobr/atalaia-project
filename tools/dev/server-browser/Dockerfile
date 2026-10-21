# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Browser tests of the site server's staff pages (server/tests_browser/,
# decision FU2-10): headless Chromium through Playwright, the same base image
# and Playwright version as the GM console's (tools/dev/console/Dockerfile),
# plus the site server's own pinned and hashed Python packages, and a compiler
# for the core library the scenario check loads. The repository is mounted
# read-only at /src; server/tests_browser/run.sh builds the core in /tmp.
#   python3 tools/docker_server.py browser   (builds this image through
#   server/docker-compose.test.yml and runs the tests next to PostgreSQL 16)
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

ARG PLAYWRIGHT_VERSION=1.49.0
ARG PYEE_VERSION=12.0.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake \
 && rm -rf /var/lib/apt/lists/*
COPY server/requirements.txt server/requirements-test.txt /tmp/
# The server's packages exactly as its image has them (hashes); then Playwright's Python client without
# its dependency pins, since the server's greenlet is newer than the one it names (its async API is used).
RUN pip install --no-cache-dir --break-system-packages --require-hashes --no-deps --only-binary=:all: \
      -r /tmp/requirements.txt -r /tmp/requirements-test.txt \
 && pip install --no-cache-dir --break-system-packages --no-deps "playwright==${PLAYWRIGHT_VERSION}" \
      "pyee==${PYEE_VERSION}" \
 && rm /tmp/requirements.txt /tmp/requirements-test.txt \
 && python3 -c "import playwright.async_api, fastapi, sqlalchemy, asyncpg, alembic, httpx, uvicorn" \
 && PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python3 -m playwright install --dry-run chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /src
