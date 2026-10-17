/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef ATALAIA_VERSION_H
#define ATALAIA_VERSION_H

#define ATALAIA_VERSION_MAJOR 0
#define ATALAIA_VERSION_MINOR 0
#define ATALAIA_VERSION_PATCH 1

/* Skirmesh-RF protocol version spoken by this core. */
#define ATALAIA_PROTOCOL_VERSION 1

/* Returns the core version as "major.minor.patch". */
const char *atalaia_version(void);

#endif /* ATALAIA_VERSION_H */
