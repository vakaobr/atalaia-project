/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef ATALAIA_VERSION_H
#define ATALAIA_VERSION_H

/* The project's version, which is the core's (decision FV-1): the release being developed,
 * with a pre-release while it is ("dev": 0.3.0-dev sorts after 0.2.0 and before 0.3.0). A
 * release empties ATALAIA_VERSION_PRERELEASE and is tagged v<MAJOR.MINOR.PATCH>; the next
 * commit raises the numbers and sets "dev" again. A firmware build adds its commit
 * (tools/docker_fw.py: 0.3.0-dev.<commits>+g<hash>; firmware/esp32/CMakeLists.txt). */
#define ATALAIA_VERSION_MAJOR      0
#define ATALAIA_VERSION_MINOR      5
#define ATALAIA_VERSION_PATCH      0
#define ATALAIA_VERSION_PRERELEASE ""

/* ATALAIA_PROTOCOL_VERSION, the Skirmesh-RF version this core speaks. */
#include "atalaia/protocol.h"

/* Returns the core version: "major.minor.patch", or "major.minor.patch-pre-release". */
const char *atalaia_version(void);

#endif /* ATALAIA_VERSION_H */
