/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Files an older firmware left in the box's storage that nothing reads any more.
 *
 * Today: the field logo (logo.bin, and logo.new from a fetch a power loss cut short) that the
 * removed box_logo fetch kept (decision LOGO-5). Removed once at boot when present: one stat
 * per name, an unlink only for a file that exists, so a clean box pays nothing.
 */
#ifndef ATALAIA_LEGACY_FILES_H
#define ATALAIA_LEGACY_FILES_H

/* Removes the leftovers under base_path ("/littlefs"). Returns how many files were removed
 * (0 = none, the usual case); NULL or an over-long base_path removes nothing. */
int legacy_files_remove(const char *base_path);

#endif /* ATALAIA_LEGACY_FILES_H */
