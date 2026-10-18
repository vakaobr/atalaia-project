/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef ATALAIA_VERSION_H
#define ATALAIA_VERSION_H

#define ATALAIA_VERSION_MAJOR 0
#define ATALAIA_VERSION_MINOR 2
#define ATALAIA_VERSION_PATCH 0

/* ATALAIA_PROTOCOL_VERSION, the Skirmesh-RF version this core speaks. */
#include "atalaia/protocol.h"

/* Returns the core version as "major.minor.patch". */
const char *atalaia_version(void);

#endif /* ATALAIA_VERSION_H */
