# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Development environment matching CI, for machines without a C toolchain.
#   docker build -t atalaia-dev tools/dev
#   docker run --rm -v "$PWD:/src" atalaia-dev sh tools/check.sh
# tools/docker_sim.py rebuilds this image when this file changes.
FROM ubuntu:24.04

# StyLua formats the Lua in modes/; pinned with its checksums, as in CI.
ARG STYLUA_VERSION=2.6.0
ARG STYLUA_SHA256_X86_64=a485f72bbfa22e4642e77a84b5edc2611a5cab7477b34e2e709dd8f78e919895
ARG STYLUA_SHA256_AARCH64=8e67539e5fdf7a81cd03cf592b0df18d3bb96ee17a5ea5d9bf67b86387b903b0

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build python3 python3-yaml clang-format-18 \
      ca-certificates curl unzip \
 && ln -s /usr/bin/clang-format-18 /usr/local/bin/clang-format \
 && arch="$(uname -m)" \
 && case "$arch" in \
      x86_64) sum="$STYLUA_SHA256_X86_64" ;; \
      aarch64) sum="$STYLUA_SHA256_AARCH64" ;; \
      *) echo "no StyLua build for $arch" >&2; exit 1 ;; \
    esac \
 && curl -sSfL -o /tmp/stylua.zip \
      "https://github.com/JohnnyMorganz/StyLua/releases/download/v${STYLUA_VERSION}/stylua-linux-${arch}.zip" \
 && echo "${sum}  /tmp/stylua.zip" | sha256sum -c - \
 && unzip -q /tmp/stylua.zip -d /usr/local/bin \
 && rm /tmp/stylua.zip \
 && apt-get purge -y curl unzip && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
