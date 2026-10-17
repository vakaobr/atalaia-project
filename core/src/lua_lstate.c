/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Builds Lua's lstate.c with a fixed string-hash seed, so table iteration
 * order is identical between runs and a game replays exactly from its event
 * log. The vendored file stays unmodified.
 */
#define luai_makeseed(L) 0u
#include "lstate.c"
