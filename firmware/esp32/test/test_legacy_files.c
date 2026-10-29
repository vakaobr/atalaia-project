/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/* Tests for legacy_files: the old field logo is removed once, nothing else is touched. */
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>

#include "check.h"
#include "legacy_files.h"

static void touch(const char *dir, const char *name)
{
    char p[300];
    snprintf(p, sizeof(p), "%s/%s", dir, name);
    FILE *f = fopen(p, "wb");
    if (f != NULL) {
        fputs("x", f);
        fclose(f);
    }
}

static int present(const char *dir, const char *name)
{
    char p[300];
    snprintf(p, sizeof(p), "%s/%s", dir, name);
    struct stat st;
    return stat(p, &st) == 0;
}

static void test_removes_old_logo_once(void)
{
    char dir[256];
    snprintf(dir, sizeof(dir), "/tmp/atalaia_legacy_%d", getpid());
    mkdir(dir, 0755);
    touch(dir, "logo.bin");
    touch(dir, "logo.new");
    touch(dir, "keep.bin");

    CHECK(legacy_files_remove(dir) == 2);
    CHECK(!present(dir, "logo.bin"));
    CHECK(!present(dir, "logo.new"));
    CHECK(present(dir, "keep.bin"));
    CHECK(legacy_files_remove(dir) == 0); /* the second boot: nothing to do */

    char p[300];
    snprintf(p, sizeof(p), "%s/keep.bin", dir);
    unlink(p);
    rmdir(dir);
}

static void test_absent_and_bad_paths(void)
{
    CHECK(legacy_files_remove(NULL) == 0);
    CHECK(legacy_files_remove("/tmp/atalaia_no_such_dir_legacy") == 0);
}

void run_legacy_files_tests(void)
{
    test_removes_old_logo_once();
    test_absent_and_bad_paths();
}
