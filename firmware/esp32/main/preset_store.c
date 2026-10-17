/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Preset storage backed by the filesystem. On ESP32 the base path points
 * at a LittleFS mount; on Linux tests it points at a temporary directory.
 * File layout:
 *   <base>/presets/NNN.json  -- preset metadata (JSON)
 *   <base>/modes/<mode_id>/node.lua -- mode source
 */
#include "preset_store.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

static char store_base[128];

/* Simple helper to build paths. */
static void preset_path(int index, char *buf, size_t sz)
{
    snprintf(buf, sz, "%s/presets/%03d.json", store_base, index);
}

static void mode_source_path(const char *mode_id, char *buf, size_t sz)
{
    snprintf(buf, sz, "%s/modes/%s/node.lua", store_base, mode_id);
}

static void ensure_dir(const char *path)
{
#ifdef _WIN32
    (void)path;
#else
    mkdir(path, 0755);
#endif
}

int preset_store_init(const char *base_path)
{
    if (!base_path) return -1;
    snprintf(store_base, sizeof(store_base), "%s", base_path);

    /* Ensure directories exist. */
    char dir[160];
    snprintf(dir, sizeof(dir), "%s/presets", store_base);
    ensure_dir(dir);
    snprintf(dir, sizeof(dir), "%s/modes", store_base);
    ensure_dir(dir);

    return 0;
}

/*
 * Minimal JSON writing/reading for preset metadata. Format:
 * {"label":"...", "mode_id":"...", "params":..., "duration_s":N}
 */

static void write_json_string(FILE *f, const char *key, const char *val)
{
    fprintf(f, "\"%s\":\"", key);
    for (const char *p = val; *p; p++) {
        if (*p == '"' || *p == '\\') fputc('\\', f);
        fputc(*p, f);
    }
    fputc('"', f);
}

bool preset_store_save(int index, const preset_t *preset)
{
    if (index < 1 || index > PRESET_MAX_SLOTS || !preset) return false;

    /* Save mode source. */
    char dir[256];
    snprintf(dir, sizeof(dir), "%s/modes/%.64s", store_base, preset->mode_id);
    ensure_dir(dir);

    char path[256];
    mode_source_path(preset->mode_id, path, sizeof(path));
    FILE *f = fopen(path, "wb");
    if (!f) return false;
    fwrite(preset->source, 1, preset->source_len, f);
    fclose(f);

    /* Save preset metadata. */
    preset_path(index, path, sizeof(path));
    f = fopen(path, "w");
    if (!f) return false;
    fputc('{', f);
    write_json_string(f, "mode_id", preset->mode_id);
    fprintf(f, ",\"duration_s\":%u,", (unsigned)preset->duration_s);
    /* params_json is already a JSON object, embed it directly */
    fprintf(f, "\"params\":%s", preset->params_json[0] ? preset->params_json : "{}");
    fputc('}', f);
    fclose(f);

    return true;
}

/* Minimal JSON string value parser. Finds "key":"value" and copies value. */
static bool json_get_string(const char *json, const char *key, char *out, size_t out_sz)
{
    char pattern[80];
    snprintf(pattern, sizeof(pattern), "\"%s\":\"", key);
    const char *p = strstr(json, pattern);
    if (!p) return false;
    p += strlen(pattern);
    size_t i = 0;
    while (*p && *p != '"' && i < out_sz - 1) {
        if (*p == '\\' && *(p + 1)) {
            p++;
        }
        out[i++] = *p++;
    }
    out[i] = '\0';
    return true;
}

/* Find "key":number and return the number. */
static uint32_t json_get_uint(const char *json, const char *key)
{
    char pattern[80];
    snprintf(pattern, sizeof(pattern), "\"%s\":", key);
    const char *p = strstr(json, pattern);
    if (!p) return 0;
    p += strlen(pattern);
    uint32_t val = 0;
    while (*p >= '0' && *p <= '9') {
        val = val * 10 + (uint32_t)(*p - '0');
        p++;
    }
    return val;
}

/* Find "params":{...} and extract the JSON object. */
static bool json_get_params(const char *json, char *out, size_t out_sz)
{
    const char *p = strstr(json, "\"params\":");
    if (!p) return false;
    p += 9; /* strlen("\"params\":") */
    /* Find the matching brace. */
    if (*p != '{') return false;
    int depth = 0;
    const char *start = p;
    while (*p) {
        if (*p == '{')
            depth++;
        else if (*p == '}') {
            depth--;
            if (depth == 0) {
                p++;
                size_t len = (size_t)(p - start);
                if (len >= out_sz) len = out_sz - 1;
                memcpy(out, start, len);
                out[len] = '\0';
                return true;
            }
        }
        p++;
    }
    return false;
}

bool preset_store_load(int index, preset_t *out)
{
    if (index < 1 || index > PRESET_MAX_SLOTS || !out) return false;
    memset(out, 0, sizeof(*out));

    char path[256];
    preset_path(index, path, sizeof(path));
    FILE *f = fopen(path, "r");
    if (!f) return false;

    char buf[1024];
    size_t len = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[len] = '\0';

    if (!json_get_string(buf, "mode_id", out->mode_id, sizeof(out->mode_id))) return false;
    out->duration_s = json_get_uint(buf, "duration_s");
    json_get_params(buf, out->params_json, sizeof(out->params_json));

    /* Load mode source. */
    mode_source_path(out->mode_id, path, sizeof(path));
    f = fopen(path, "rb");
    if (!f) return false;
    out->source_len = fread(out->source, 1, sizeof(out->source) - 1, f);
    fclose(f);
    out->source[out->source_len] = '\0';

    return true;
}

int preset_store_list(preset_summary_t *out, int max_out)
{
    int count = 0;
    for (int i = 1; i <= PRESET_MAX_SLOTS && count < max_out; i++) {
        char path[256];
        preset_path(i, path, sizeof(path));
        FILE *f = fopen(path, "r");
        if (!f) continue;

        char buf[1024];
        size_t len = fread(buf, 1, sizeof(buf) - 1, f);
        fclose(f);
        buf[len] = '\0';

        out[count].index = i;
        json_get_string(buf, "mode_id", out[count].mode_id, sizeof(out[count].mode_id));
        /* Use mode_id as label if no label field. */
        snprintf(out[count].label, sizeof(out[count].label), "%.47s", out[count].mode_id);
        count++;
    }
    return count;
}

bool preset_store_delete(int index)
{
    if (index < 1 || index > PRESET_MAX_SLOTS) return false;
    char path[256];
    preset_path(index, path, sizeof(path));
    return remove(path) == 0;
}
