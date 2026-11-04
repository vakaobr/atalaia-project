# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The expansion port's module firmware (firmware/target-module/; draft RFC "The expansion port",
# increment 8): GCC for Arm, pico-sdk and picotool, each pinned (the image by digest, the SDK
# and picotool by tag and commit, checked after the clone), so a UF2 built here is built from
# the same sources every time. tools/docker_module.py builds this image when this file changes.
#   docker build -t atalaia-module tools/dev/module
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852

ARG PICO_SDK_TAG=2.2.0
ARG PICO_SDK_COMMIT=a1438dff1d38bd9c65dbd693f0e5db4b9ae91779
ARG PICOTOOL_TAG=2.2.0
ARG PICOTOOL_COMMIT=a7eb3988f0645239185fadb4e25d8279478c2dbb

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build python3 git ca-certificates pkg-config libusb-1.0-0-dev \
      gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib \
 && rm -rf /var/lib/apt/lists/*

# pico-sdk without its submodules: the target module uses no USB (TinyUSB), Wi-Fi or Bluetooth.
RUN git clone --depth 1 --branch "$PICO_SDK_TAG" https://github.com/raspberrypi/pico-sdk.git /opt/pico-sdk \
 && test "$(git -C /opt/pico-sdk rev-parse HEAD)" = "$PICO_SDK_COMMIT" \
 && rm -rf /opt/pico-sdk/.git
ENV PICO_SDK_PATH=/opt/pico-sdk

# picotool makes the UF2 (pico-sdk 2.x would otherwise fetch it from GitHub at build time).
RUN git clone --depth 1 --branch "$PICOTOOL_TAG" https://github.com/raspberrypi/picotool.git /tmp/picotool \
 && test "$(git -C /tmp/picotool rev-parse HEAD)" = "$PICOTOOL_COMMIT" \
 && cmake -S /tmp/picotool -B /tmp/picotool-build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DPICOTOOL_FLAT_INSTALL=1 -DCMAKE_INSTALL_PREFIX=/opt/picotool \
 && cmake --build /tmp/picotool-build \
 && cmake --install /tmp/picotool-build \
 && rm -rf /tmp/picotool /tmp/picotool-build
ENV picotool_DIR=/opt/picotool/picotool
WORKDIR /src
