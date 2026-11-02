# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The project page's browser test (tools/site_browser_test.py): Playwright's own image (it has Chromium 1148
# but a python3 without the `playwright` module) plus the pinned, hashed Python client of requirements.txt,
# and nothing else. The repository is mounted read-only at /src.
#   python3 tools/docker_site_browser.py   (builds this image and runs the test)
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages --require-hashes --no-deps --only-binary=:all: \
      -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 && python3 -c "import playwright.sync_api" \
 && PLAYWRIGHT_BROWSERS_PATH=/ms-playwright python3 -m playwright install --dry-run chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
