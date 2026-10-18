# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Browser tests of the GM console (controller/console/tests/): headless
# Chromium through Playwright, plus what the field controller needs to run
# for real (the core library, the C host modem, Mosquitto) and zbarimg to
# read the join QR code back. The base image ships Chromium 1148, the
# browser build Playwright 1.49.0 expects; the Python package is pinned to
# match. The controller's Python dependencies are Ubuntu 24.04's own
# packages, as in tools/dev/Dockerfile and on a Raspberry Pi.
#   python tools/docker_console.py      (builds this image and runs the tests)
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

ARG PLAYWRIGHT_VERSION=1.49.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake libmbedtls-dev mosquitto zbar-tools \
      python3-yaml python3-cryptography python3-fastapi python3-uvicorn python3-websockets \
      python3-httpx python3-paho-mqtt python3-serial \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir --break-system-packages "playwright==${PLAYWRIGHT_VERSION}" \
 && python3 -c "import playwright, fastapi, uvicorn, paho.mqtt.client, serial, yaml" \
 && PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python3 -m playwright install --dry-run chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /src
