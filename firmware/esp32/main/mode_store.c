/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Fetched mode packages on the box's storage (mode_store.h).
 */
#define _POSIX_C_SOURCE 200809L /* opendir, rmdir in the host tests' strict C11 */

#include "mode_store.h"

#include <dirent.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "preset_store.h"

#define PATH_MAX_LEN 320
#define STAGE        ".new"
#define OLD          ".old"

static char base[128];

static bool path_of(char *buf, size_t cap, const char *dir, const char *name)
{
    int n = name ? snprintf(buf, cap, "%s/modes/%s/%s", base, dir, name)
                 : snprintf(buf, cap, "%s/modes/%s", base, dir);
    return n > 0 && (size_t)n < cap;
}

static bool is_dir(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static bool exists(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0;
}

static void make_dir(const char *path)
{
    mkdir(path, 0755);
}

/* Removes a folder and what it holds (at most a few levels: assets/screens). */
static void remove_tree(const char *path, int depth)
{
    DIR *d = opendir(path);
    if (d != NULL) {
        struct dirent *e;
        while ((e = readdir(d)) != NULL) {
            if (strcmp(e->d_name, ".") == 0 || strcmp(e->d_name, "..") == 0) continue;
            char child[PATH_MAX_LEN];
            int n = snprintf(child, sizeof(child), "%s/%s", path, e->d_name);
            if (n <= 0 || (size_t)n >= sizeof(child)) continue;
            if (is_dir(child)) {
                if (depth < 4) remove_tree(child, depth + 1);
            } else {
                remove(child);
            }
        }
        closedir(d);
    }
    rmdir(path);
}

/* ---- the fetched file ------------------------------------------------------------------ */

static bool line_value(const char *text, const char *key, char *out, size_t cap)
{
    size_t kl = strlen(key);
    for (const char *p = text; p != NULL && *p; p = strchr(p, '\n') ? strchr(p, '\n') + 1 : NULL) {
        if (strncmp(p, key, kl) == 0 && p[kl] == '=') {
            const char *v = p + kl + 1;
            size_t n = strcspn(v, "\n");
            if (n >= cap) return false;
            memcpy(out, v, n);
            out[n] = '\0';
            return true;
        }
    }
    return false;
}

static bool read_meta(const char *dir, ms_fetched_t *out)
{
    char path[PATH_MAX_LEN];
    if (!path_of(path, sizeof(path), dir, "fetched")) return false;
    FILE *f = fopen(path, "r");
    if (f == NULL) return false;
    char text[384];
    size_t n = fread(text, 1, sizeof(text) - 1, f);
    fclose(f);
    text[n] = '\0';
    ms_fetched_t m;
    memset(&m, 0, sizeof(m));
    char bytes[12], used[12];
    if (!line_value(text, "id", m.id, sizeof(m.id)) ||
        !line_value(text, "version", m.version, sizeof(m.version)) ||
        !line_value(text, "key_id", m.key_id, sizeof(m.key_id)) ||
        !line_value(text, "sha256", m.sha256, sizeof(m.sha256)) ||
        !line_value(text, "bytes", bytes, sizeof(bytes)) ||
        !line_value(text, "used", used, sizeof(used))) {
        return false;
    }
    m.bytes = (uint32_t)strtoul(bytes, NULL, 10);
    m.used = (uint32_t)strtoul(used, NULL, 10);
    if (out != NULL) *out = m;
    return true;
}

static bool write_meta(const char *dir, const ms_fetched_t *m)
{
    char path[PATH_MAX_LEN];
    if (!path_of(path, sizeof(path), dir, "fetched")) return false;
    FILE *f = fopen(path, "w");
    if (f == NULL) return false;
    fprintf(f, "id=%s\nversion=%s\nkey_id=%s\nsha256=%s\nbytes=%lu\nused=%lu\n", m->id, m->version,
            m->key_id, m->sha256, (unsigned long)m->bytes, (unsigned long)m->used);
    return fclose(f) == 0;
}

/* ---- the store ------------------------------------------------------------------------- */

/* The fetched modes, on the heap (the store is used now and then: no static RAM for it); the
 * caller frees it. NULL (and *n 0) without memory. A few more than the limit, in case. */
#define LIST_CAP (MS_FETCHED_MAX + 4)

static ms_fetched_t *load_list(int *n)
{
    ms_fetched_t *list = malloc(LIST_CAP * sizeof(ms_fetched_t));
    *n = list != NULL ? mode_store_list(list, LIST_CAP) : 0;
    return list;
}

int mode_store_init(const char *base_path)
{
    if (base_path == NULL || strlen(base_path) >= sizeof(base)) return -1;
    snprintf(base, sizeof(base), "%s", base_path);
    char dir[PATH_MAX_LEN], stage[PATH_MAX_LEN], old[PATH_MAX_LEN];
    snprintf(dir, sizeof(dir), "%s/modes", base);
    make_dir(dir);
    path_of(stage, sizeof(stage), STAGE, NULL);
    path_of(old, sizeof(old), OLD, NULL);
    /* A commit cut short between its two renames: the new version is whole (its fetched file is
     * written last) and its id has no folder: finish it. Anything else on its way is forgotten. */
    ms_fetched_t m;
    if (is_dir(old) && read_meta(STAGE, &m)) {
        char target[PATH_MAX_LEN];
        if (path_of(target, sizeof(target), m.id, NULL) && !exists(target)) rename(stage, target);
    }
    if (is_dir(stage)) remove_tree(stage, 0);
    if (is_dir(old)) remove_tree(old, 0);
    /* Every fetched mode has a preset (a commit cut short after its renames has none yet). */
    int n;
    ms_fetched_t *list = load_list(&n);
    for (int i = 0; i < n; i++) {
        if (preset_store_find_mode(list[i].id) < 0) preset_store_add(list[i].id, list[i].id, "{}");
    }
    free(list);
    return 0;
}

int mode_store_verify(const uint8_t (*keys)[32], size_t key_count)
{
    int n;
    ms_fetched_t *list = load_list(&n);
    int dropped = 0;
    for (int i = 0; i < n; i++) {
        char path[PATH_MAX_LEN], text[MP_RELEASE_TEXT_MAX + 1];
        size_t len = 0;
        FILE *f = path_of(path, sizeof(path), list[i].id, "release") ? fopen(path, "rb") : NULL;
        if (f != NULL) {
            len = fread(text, 1, MP_RELEASE_TEXT_MAX, f);
            fclose(f);
        }
        text[len] = '\0';
        mp_release_t rel;
        bool ok = len > 0 && mp_release_parse(text, len, &rel) && strcmp(rel.id, list[i].id) == 0 &&
                  strcmp(rel.version, list[i].version) == 0 &&
                  strcmp(rel.sha256_hex, list[i].sha256) == 0 &&
                  mp_release_signer(&rel, text, keys, key_count) >= 0;
        if (!ok && mode_store_remove(list[i].id)) dropped++;
    }
    free(list);
    return dropped;
}

bool mode_store_has(const char *id)
{
    return mode_store_source_len(id) >= 0;
}

long mode_store_source_len(const char *id)
{
    char path[PATH_MAX_LEN];
    struct stat st;
    if (base[0] == '\0' || id == NULL || !mp_id_valid(id, strlen(id)) ||
        !path_of(path, sizeof(path), id, "node.lua") || stat(path, &st) != 0) {
        return -1;
    }
    return (long)st.st_size;
}

bool mode_store_fetched(const char *id, ms_fetched_t *out)
{
    if (base[0] == '\0' || id == NULL || !mp_id_valid(id, strlen(id))) return false;
    ms_fetched_t m;
    if (!read_meta(id, &m) || strcmp(m.id, id) != 0) return false;
    if (out != NULL) *out = m;
    return true;
}

int mode_store_list(ms_fetched_t *out, int cap)
{
    if (base[0] == '\0') return 0;
    char dir[PATH_MAX_LEN];
    snprintf(dir, sizeof(dir), "%s/modes", base);
    DIR *d = opendir(dir);
    if (d == NULL) return 0;
    int n = 0;
    struct dirent *e;
    while (n < cap && (e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue; /* ".", "..", .new and .old */
        if (mode_store_fetched(e->d_name, &out[n])) n++;
    }
    closedir(d);
    return n;
}

/* ---- a package on its way ------------------------------------------------------------ */

bool mode_store_stage_begin(void)
{
    if (base[0] == '\0') return false;
    char stage[PATH_MAX_LEN];
    path_of(stage, sizeof(stage), STAGE, NULL);
    if (exists(stage)) remove_tree(stage, 0);
    make_dir(stage);
    return is_dir(stage);
}

FILE *mode_store_stage_open(const char *name, const char *how)
{
    char path[PATH_MAX_LEN];
    if (base[0] == '\0' || name == NULL || strstr(name, "..") != NULL || name[0] == '/' ||
        !path_of(path, sizeof(path), STAGE, name)) {
        return NULL;
    }
    if (strncmp(name, "assets/screens/", 15) == 0 && how[0] == 'w') {
        char dir[PATH_MAX_LEN];
        path_of(dir, sizeof(dir), STAGE, "assets");
        make_dir(dir);
        path_of(dir, sizeof(dir), STAGE, "assets/screens");
        make_dir(dir);
    }
    return fopen(path, how);
}

bool mode_store_stage_remove(const char *name)
{
    char path[PATH_MAX_LEN];
    return path_of(path, sizeof(path), STAGE, name) && remove(path) == 0;
}

void mode_store_stage_abort(void)
{
    char stage[PATH_MAX_LEN];
    if (base[0] != '\0' && path_of(stage, sizeof(stage), STAGE, NULL) && exists(stage)) {
        remove_tree(stage, 0);
    }
}

/* True if part is one of the "+"-separated ids of mode_id. */
static bool part_of(const char *mode_id, const char *part)
{
    size_t n = strlen(part);
    for (const char *p = mode_id; p != NULL && *p;) {
        const char *next = strchr(p, '+');
        size_t len = next != NULL ? (size_t)(next - p) : strlen(p);
        if (len == n && strncmp(p, part, n) == 0) return true;
        p = next != NULL ? next + 1 : NULL;
    }
    return false;
}

bool mode_store_make_room(uint32_t bytes, const char *replacing, const char *keep)
{
    if (bytes > MS_FETCHED_BYTES) return false;
    ms_fetched_t *list = malloc(LIST_CAP * sizeof(ms_fetched_t));
    if (list == NULL) return false;
    bool ok = false;
    for (;;) {
        int n = mode_store_list(list, LIST_CAP);
        int count = 1;
        uint64_t total = bytes;
        int victim = -1;
        for (int i = 0; i < n; i++) {
            if (replacing != NULL && strcmp(list[i].id, replacing) == 0) continue;
            count++;
            total += list[i].bytes;
            if (keep != NULL && part_of(keep, list[i].id)) continue;
            if (victim < 0 || list[i].used < list[victim].used) victim = i;
        }
        if (count <= MS_FETCHED_MAX && total <= MS_FETCHED_BYTES) {
            ok = true;
            break;
        }
        if (victim < 0 || !mode_store_remove(list[victim].id)) break;
    }
    free(list);
    return ok;
}

bool mode_store_commit(const ms_fetched_t *meta, const char *release_text, size_t len)
{
    if (base[0] == '\0' || !mp_id_valid(meta->id, strlen(meta->id))) return false;
    char path[PATH_MAX_LEN], stage[PATH_MAX_LEN], old[PATH_MAX_LEN], target[PATH_MAX_LEN];
    path_of(stage, sizeof(stage), STAGE, NULL);
    path_of(old, sizeof(old), OLD, NULL);
    path_of(target, sizeof(target), meta->id, NULL);
    if (!path_of(path, sizeof(path), STAGE, "release")) return false;
    FILE *f = fopen(path, "wb");
    if (f == NULL) return false;
    bool ok = fwrite(release_text, 1, len, f) == len;
    if (fclose(f) != 0 || !ok) return false;
    /* The most recently used: the game that asked for it is about to play it. */
    ms_fetched_t m = *meta;
    int n;
    ms_fetched_t *list = load_list(&n);
    for (int i = 0; i < n; i++) {
        if (list[i].used >= m.used) m.used = list[i].used + 1;
    }
    free(list);
    if (!write_meta(STAGE, &m)) return false; /* last: the package is whole */
    if (exists(old)) remove_tree(old, 0);
    bool replacing = exists(target);
    if (replacing && rename(target, old) != 0) return false;
    if (rename(stage, target) != 0) {
        if (replacing) rename(old, target); /* the older version stays */
        return false;
    }
    if (replacing) remove_tree(old, 0);
    if (preset_store_find_mode(m.id) < 0) preset_store_add(m.id, m.id, "{}");
    return true;
}

bool mode_store_remove(const char *id)
{
    if (!mode_store_fetched(id, NULL)) return false; /* never a built-in mode */
    char path[PATH_MAX_LEN];
    path_of(path, sizeof(path), id, NULL);
    preset_store_remove_mode(id);
    remove_tree(path, 0);
    return !exists(path);
}

int mode_store_forget_all(void)
{
    int n;
    ms_fetched_t *list = load_list(&n);
    int removed = 0;
    for (int i = 0; i < n; i++) {
        if (mode_store_remove(list[i].id)) removed++;
    }
    free(list);
    return removed;
}

void mode_store_touch(const char *mode_id)
{
    if (base[0] == '\0' || mode_id == NULL) return;
    int n;
    ms_fetched_t *list = load_list(&n);
    uint32_t top = 0;
    for (int i = 0; i < n; i++) {
        if (list[i].used > top) top = list[i].used;
    }
    for (int i = 0; i < n; i++) {
        if (part_of(mode_id, list[i].id) && list[i].used != top) {
            list[i].used = ++top;
            write_meta(list[i].id, &list[i]);
        }
    }
    free(list);
}

/* ---- screens ---------------------------------------------------------------------------- */

static struct {
    char mode[MP_ID_MAX + 1];
    char name[40];
    char *yaml; /* MS_SCREEN_MAX + 1 bytes, allocated at the first fetched screen */
    builtin_screen_t screen;
} cache;

const builtin_screen_t *mode_store_screen(const char *part, size_t n, const char *name)
{
    if (base[0] == '\0' || part == NULL || name == NULL || n == 0 || n > MP_ID_MAX) return NULL;
    size_t nl = strlen(name);
    if (nl == 0 || nl >= sizeof(cache.name) || name[0] == '.') return NULL;
    for (size_t i = 0; i < nl; i++) {
        char c = name[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
              c == '_' || c == '-' || c == '.')) {
            return NULL;
        }
    }
    char id[MP_ID_MAX + 1];
    memcpy(id, part, n);
    id[n] = '\0';
    if (!mp_id_valid(id, n)) return NULL;
    if (cache.yaml != NULL && strcmp(cache.mode, id) == 0 && strcmp(cache.name, name) == 0) {
        return &cache.screen;
    }
    if (!mode_store_fetched(id, NULL)) return NULL; /* built-in modes' screens are in the image */
    char file[64], path[PATH_MAX_LEN];
    snprintf(file, sizeof(file), "assets/screens/%s.yaml", name);
    if (!path_of(path, sizeof(path), id, file)) return NULL;
    FILE *f = fopen(path, "rb");
    if (f == NULL) return NULL;
    if (cache.yaml == NULL) cache.yaml = malloc(MS_SCREEN_MAX + 1);
    size_t len = cache.yaml != NULL ? fread(cache.yaml, 1, MS_SCREEN_MAX + 1, f) : 0;
    fclose(f);
    cache.mode[0] = '\0';
    if (len == 0 || len > MS_SCREEN_MAX) return NULL;
    cache.yaml[len] = '\0';
    snprintf(cache.mode, sizeof(cache.mode), "%s", id);
    snprintf(cache.name, sizeof(cache.name), "%s", name);
    cache.screen.mode_id = cache.mode;
    cache.screen.name = cache.name;
    cache.screen.yaml = cache.yaml;
    cache.screen.len = len;
    return &cache.screen;
}
