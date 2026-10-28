# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# The preview's live demo field (decisions DEMO-*; docs/runbooks/preview-server.md "The live demo"): a field
# controller playing a looping game with simulated Field Boxes, behind a read-only proxy.
# The boxes are the Field Box firmware's own game and radio code built for Linux (the "host box" and the "host
# modem" that the controller's end-to-end tests use), sharing a UDP "air" in one process group; nothing here
# touches a radio, a serial port or hardware.
# The build context is the repository root; Dockerfile.dockerignore next to this file lets only what is used in.
#   docker build -f server/preview/demo/Dockerfile -t atalaia-demo .
# The base image is pinned by digest (Ubuntu 24.04, whose own Python packages are what the controller is tested
# with, as in tools/dev/Dockerfile); both stages use it, so what is built links against the libraries it runs on.
ARG UBUNTU_IMAGE=ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3

FROM ${UBUNTU_IMAGE} AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake libmbedtls-dev \
 && rm -rf /var/lib/apt/lists/*
COPY core /src/core
COPY firmware/esp32 /src/firmware/esp32
RUN cmake -S /src/core -B /out/core -DCMAKE_BUILD_TYPE=Release -DATALAIA_SHARED=ON -DBUILD_TESTING=OFF > /dev/null \
 && cmake --build /out/core --parallel > /dev/null \
 && cmake -S /src/firmware/esp32/test/modem_host -B /out/modem_host -DCMAKE_BUILD_TYPE=Release > /dev/null \
 && cmake --build /out/modem_host --parallel > /dev/null \
 && cmake -S /src/firmware/esp32/test/box_host -B /out/box_host -DCMAKE_BUILD_TYPE=Release > /dev/null \
 && cmake --build /out/box_host --parallel > /dev/null \
 && mkdir -p /opt/atalaia \
 && cp /out/core/libatalaia_core.so /out/modem_host/modem_host /out/box_host/box_host /opt/atalaia/ \
 && ldd /opt/atalaia/box_host /opt/atalaia/modem_host /opt/atalaia/libatalaia_core.so | grep -i "not found" && exit 1 || true

FROM ${UBUNTU_IMAGE} AS demo
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/controller:/app/simulator \
    ATALAIA_CORE_LIB=/opt/atalaia/libatalaia_core.so \
    ATALAIA_MODEM_HOST=/opt/atalaia/modem_host \
    ATALAIA_BOX_HOST=/opt/atalaia/box_host
# libmbedcrypto: the boxes' AES-CCM. The controller's Python packages are Ubuntu's own, as on a Raspberry Pi.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-yaml python3-cryptography python3-fastapi python3-uvicorn python3-websockets python3-httpx \
      python3-serial python3-paho-mqtt libmbedcrypto7t64 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin demo \
 && mkdir -p /data && chown demo /data
COPY --from=build /opt/atalaia /opt/atalaia
COPY simulator/atalaia_sim /app/simulator/atalaia_sim
COPY controller/atalaia_controller /app/controller/atalaia_controller
COPY controller/console/src /app/controller/console/src
COPY controller/templates /app/controller/templates
COPY modes /app/modes
COPY protocol /app/protocol
COPY app/lib/chrono/limit_templates /app/app/lib/chrono/limit_templates
COPY registry/apds /app/registry/apds
COPY server/preview/demo/field /app/demo
WORKDIR /app/demo
USER demo
VOLUME /data
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/demo/health', timeout=4)"]
CMD ["python3", "/app/demo/demo_field.py"]
