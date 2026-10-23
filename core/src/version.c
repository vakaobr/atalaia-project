/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "atalaia/version.h"

#define ATALAIA_STR2(x) #x
#define ATALAIA_STR(x)  ATALAIA_STR2(x)
#define NUMBERS                                                                                    \
    ATALAIA_STR(ATALAIA_VERSION_MAJOR)                                                             \
    "." ATALAIA_STR(ATALAIA_VERSION_MINOR) "." ATALAIA_STR(ATALAIA_VERSION_PATCH)
#define WITH_PRERELEASE NUMBERS "-" ATALAIA_VERSION_PRERELEASE

const char *atalaia_version(void)
{
    /* Two literals: nothing is made at run time. */
    return sizeof(ATALAIA_VERSION_PRERELEASE) > 1 ? WITH_PRERELEASE : NUMBERS;
}
