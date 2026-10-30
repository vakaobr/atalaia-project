/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Builds Lua's lstate.c with a fixed string-hash seed, so table iteration
 * order is identical between runs and a game replays exactly from its event
 * log. The vendored file stays unmodified.
 *
 * It also clears the main thread's extra space when a state opens (Lua leaves
 * it uninitialised): the patched ltablib.c keeps its metering remainder there
 * (decision SR-130).
 */
#include <string.h>

#define luai_makeseed(L)      0u
#define luai_userstateopen(L) ((void)memset(lua_getextraspace(L), 0, LUA_EXTRASPACE))
#include "lstate.c"
