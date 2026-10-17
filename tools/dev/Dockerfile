# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Development environment matching CI, for machines without a C toolchain.
#   docker build -t atalaia-dev tools/dev
#   docker run --rm -v "$PWD:/src" atalaia-dev sh tools/check.sh
FROM ubuntu:24.04
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build python3 python3-yaml \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
