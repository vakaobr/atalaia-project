/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "atalaia/version.h"

#define ATALAIA_STR2(x) #x
#define ATALAIA_STR(x) ATALAIA_STR2(x)

const char *atalaia_version(void)
{
    return ATALAIA_STR(ATALAIA_VERSION_MAJOR) "."
           ATALAIA_STR(ATALAIA_VERSION_MINOR) "."
           ATALAIA_STR(ATALAIA_VERSION_PATCH);
}
