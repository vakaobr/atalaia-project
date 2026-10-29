/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "legacy_files.h"

#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>

static const char *const legacy_names[] = {"logo.bin", "logo.new"};

int legacy_files_remove(const char *base_path)
{
    if (base_path == NULL) return 0;
    int removed = 0;
    for (unsigned i = 0; i < sizeof(legacy_names) / sizeof(legacy_names[0]); i++) {
        char p[160];
        if (snprintf(p, sizeof(p), "%s/%s", base_path, legacy_names[i]) >= (int)sizeof(p)) continue;
        struct stat st;
        if (stat(p, &st) == 0 && S_ISREG(st.st_mode) && unlink(p) == 0) removed++;
    }
    return removed;
}
