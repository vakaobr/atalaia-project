# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# The site server's image (ADR-P4-10 as amended, decisions P4R9 and P4R16).
# The build context is the repository root; Dockerfile.dockerignore next to
# this file lets only core/, the shared Python, the chrono limit templates and server/ in.
#   docker build -f server/Dockerfile -t atalaia-server .                    the server
#   docker build -f server/Dockerfile --target test -t atalaia-server-test .  plus its tests
# tools/docker_server.py builds both through Docker Compose.
#
# Stage "core" compiles libatalaia_core.so, so the site server can load a
# scenario's Lua as the controller does (P4R9); the final image has no
# compiler. Python packages come only from server/requirements.txt, pinned
# with their PyPI hashes. The base image is pinned by digest (3.12.14-slim,
# Debian 13); both stages use it, so the core links against the same libc.
ARG PYTHON_IMAGE=python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

FROM ${PYTHON_IMAGE} AS core
RUN apt-get update \
 && apt-get install -y --no-install-recommends cmake gcc libc6-dev make \
 && rm -rf /var/lib/apt/lists/*
COPY core /build/core
# No mbedtls: the site server never encrypts radio packets.
RUN cmake -S /build/core -B /build/out -DCMAKE_BUILD_TYPE=Release -DATALAIA_SHARED=ON -DATALAIA_MBEDTLS=OFF \
      -DBUILD_TESTING=OFF \
 && cmake --build /build/out --parallel \
 && test -f /build/out/libatalaia_core.so

FROM ${PYTHON_IMAGE} AS server
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/server:/app/controller:/app/simulator \
    ATALAIA_CORE_LIB=/opt/atalaia/lib/libatalaia_core.so
COPY server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --no-deps --only-binary=:all: --root-user-action=ignore \
      -r /tmp/requirements.txt \
 && pip check \
 && rm /tmp/requirements.txt \
 && useradd --uid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin atalaia
COPY --from=core /build/out/libatalaia_core.so /opt/atalaia/lib/libatalaia_core.so
# The pure-Python code shared with the field controller (P4R16).
COPY simulator/atalaia_sim /app/simulator/atalaia_sim
COPY controller/atalaia_controller /app/controller/atalaia_controller
# The chrono limit templates the controller and the app use: a registration's replica classes (plan phase 16).
COPY app/lib/chrono/limit_templates /app/app/lib/chrono/limit_templates
COPY server/atalaia_server /app/server/atalaia_server
COPY server/migrations /app/server/migrations
COPY server/alembic.ini /app/server/alembic.ini
# The erasure ledger's folder (PRIV-4): a named volume mounted here takes this owner.
RUN mkdir /ledger && chown atalaia /ledger
WORKDIR /app/server
USER atalaia
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
# Migrate, then serve behind Caddy (server/docker-compose.yml). One worker process, always
# (ADR-P4-2; decision S19-4): the rate limits and the remote GM's links live in its memory;
# --workers 1 also overrides a WEB_CONCURRENCY in the environment. --proxy-headers takes the
# client's address from Caddy, for the peers FORWARDED_ALLOW_IPS names (decision S22-4).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory atalaia_server.app:create_app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --no-server-header"]

FROM server AS test
USER root
COPY server/requirements-test.txt /tmp/requirements-test.txt
RUN pip install --no-cache-dir --require-hashes --no-deps --only-binary=:all: --root-user-action=ignore \
      -r /tmp/requirements-test.txt \
 && pip check \
 && rm /tmp/requirements-test.txt
# The built-in modes, for the core load check in tests/test_shared_imports.py and the
# controller's engine in tests/test_sync_e2e.py; the shared sync and chrono vectors for
# tests/test_sync.py, test_chrono.py and test_chrono_verify.py.
COPY modes /app/modes
COPY protocol/vectors/sync.json protocol/vectors/chrono_record.json protocol/vectors/apd.json /app/protocol/vectors/
COPY registry/apds/apds.json /app/registry/apds/apds.json
COPY server/schemas /app/server/schemas
COPY server/tests /app/server/tests
ENV ATALAIA_REQUIRE_ALL=1
USER atalaia
CMD ["sh", "tests/run.sh", "test"]
