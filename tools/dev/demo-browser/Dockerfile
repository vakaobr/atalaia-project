# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Headless Chromium for the live demo's page tests (tools/demo_player_browser.py, decision DEMO-20): the same base
# image and Playwright version as the GM console's and the site server's browser tests, and nothing else.
#   docker build -t atalaia-demo-browser tools/dev/demo-browser
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

ARG PLAYWRIGHT_VERSION=1.49.0

RUN pip install --no-cache-dir --break-system-packages "playwright==${PLAYWRIGHT_VERSION}" \
 && python3 -c "import playwright.sync_api" \
 && PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python3 -m playwright install --dry-run chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
