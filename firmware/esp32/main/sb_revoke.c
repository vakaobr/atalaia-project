/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Secure boot digest revocation (sb_revoke.h): the instruction's form, its Ed25519 signature
 * (Monocypher, as the release texts: fw_update.c's base64 decoder) and the checks on the box's
 * eFuses before anything is burned.
 */
#include "sb_revoke.h"

#include <stdio.h>
#include <string.h>

#include "fw_update.h"
#include "monocypher-ed25519.h"

const char *sb_revoke_result_name(sb_revoke_result_t r)
{
    static const char *const names[] = {
        "done",           "bad_form", "no_key",      "bad_signature", "no_state", "not_secure_boot",
        "unknown_digest", "already",  "running_key", "last_key",      "efuse"};
    return (unsigned)r < sizeof(names) / sizeof(names[0]) ? names[r] : "unknown";
}

size_t sb_revoke_message(const uint8_t digest[SB_DIGEST_LEN], char *out, size_t cap)
{
    if (cap < SB_REVOKE_MESSAGE_LEN + 1) return 0;
    int n = snprintf(out, cap, "%s\nplatform=%s\ndigest=", SB_REVOKE_HEADER, SB_REVOKE_PLATFORM);
    if (n < 0) return 0;
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < SB_DIGEST_LEN; i++) {
        out[n++] = hex[digest[i] >> 4];
        out[n++] = hex[digest[i] & 15];
    }
    out[n++] = '\n';
    out[n] = '\0';
    return (size_t)n;
}

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool sb_revoke_parse(const char *text, sb_revoke_instruction_t *out)
{
    memset(out, 0, sizeof(*out));
    if (text == NULL || strlen(text) != 64 + 1 + 88 || text[64] != ' ') return false;
    for (size_t i = 0; i < SB_DIGEST_LEN; i++) {
        int hi = hex_nibble(text[2 * i]), lo = hex_nibble(text[2 * i + 1]);
        if (hi < 0 || lo < 0) return false;
        out->digest[i] = (uint8_t)(hi << 4 | lo);
    }
    return fw_signature_decode(text + 65, 88, out->signature);
}

bool sb_revoke_signed(const sb_revoke_instruction_t *ins, const uint8_t (*keys)[32],
                      size_t key_count)
{
    char msg[SB_REVOKE_MESSAGE_LEN + 1];
    size_t n = sb_revoke_message(ins->digest, msg, sizeof(msg));
    if (n != SB_REVOKE_MESSAGE_LEN) return false;
    for (size_t k = 0; k < key_count; k++) {
        if (crypto_ed25519_check(ins->signature, keys[k], (const uint8_t *)msg, n) == 0) {
            return true;
        }
    }
    return false;
}

sb_revoke_result_t sb_revoke_decide(const sb_state_t *s, const uint8_t digest[SB_DIGEST_LEN],
                                    int *slot)
{
    *slot = -1;
    if (!s->secure_boot) return SB_REVOKE_NOT_SECURE_BOOT;
    if (s->running_count == 0 || s->running_count > SB_DIGEST_SLOTS) return SB_REVOKE_NO_STATE;
    int found = -1;
    for (int i = 0; i < SB_DIGEST_SLOTS; i++) {
        if (s->present[i] && memcmp(s->digest[i], digest, SB_DIGEST_LEN) == 0) {
            found = i;
            break;
        }
    }
    if (found < 0) return SB_REVOKE_UNKNOWN_DIGEST;
    *slot = found;
    if (s->revoked[found]) return SB_REVOKE_ALREADY;
    /* Never the key the running image carries a signature block of: the bootloader verified it
     * with one of them, and after the revocation the next boot would find no trusted signature. */
    for (size_t i = 0; i < s->running_count; i++) {
        if (memcmp(s->running[i], digest, SB_DIGEST_LEN) == 0) return SB_REVOKE_RUNNING;
    }
    /* Never the last trusted slot (an image signed by no trusted key would never boot again). */
    int others = 0;
    for (int i = 0; i < SB_DIGEST_SLOTS; i++) {
        if (i != found && s->present[i] && !s->revoked[i]) others++;
    }
    if (others == 0) return SB_REVOKE_LAST;
    return SB_REVOKE_DONE;
}

sb_revoke_result_t sb_revoke_run(const char *text, const uint8_t (*keys)[32], size_t key_count,
                                 const sb_revoke_ops_t *ops, int *slot)
{
    int s_slot = -1;
    if (slot == NULL) slot = &s_slot;
    *slot = -1;
    sb_revoke_instruction_t ins;
    if (!sb_revoke_parse(text, &ins)) return SB_REVOKE_BAD_FORM;
    if (keys == NULL || key_count == 0) return SB_REVOKE_NO_KEY;
    if (!sb_revoke_signed(&ins, keys, key_count)) return SB_REVOKE_BAD_SIGNATURE;
    sb_state_t state;
    memset(&state, 0, sizeof(state));
    if (!ops->read_state(&state, ops->ctx)) return SB_REVOKE_NO_STATE;
    sb_revoke_result_t r = sb_revoke_decide(&state, ins.digest, slot);
    if (r != SB_REVOKE_DONE) return r;
    if (!ops->burn_revoke(*slot, ops->ctx)) return SB_REVOKE_EFUSE;
    memset(&state, 0, sizeof(state));
    if (!ops->read_state(&state, ops->ctx) || !state.revoked[*slot]) return SB_REVOKE_EFUSE;
    return SB_REVOKE_DONE;
}

int sb_revoke_run_list(const char *list, const uint8_t (*keys)[32], size_t key_count,
                       const sb_revoke_ops_t *ops,
                       void (*report)(int index, sb_revoke_result_t r, int slot, void *ctx),
                       void *report_ctx)
{
    int refused = 0, index = 0;
    const char *p = list == NULL ? "" : list;
    while (*p != '\0') {
        while (*p == ',' || *p == ' ') p++;
        if (*p == '\0') break;
        const char *end = strchr(p, ',');
        size_t n = end == NULL ? strlen(p) : (size_t)(end - p);
        while (n > 0 && p[n - 1] == ' ') n--;
        char one[SB_REVOKE_TEXT_MAX];
        sb_revoke_result_t r;
        int slot = -1;
        if (n >= sizeof(one)) {
            r = SB_REVOKE_BAD_FORM;
        } else {
            memcpy(one, p, n);
            one[n] = '\0';
            r = sb_revoke_run(one, keys, key_count, ops, &slot);
        }
        if (r != SB_REVOKE_DONE && r != SB_REVOKE_ALREADY) refused++;
        if (report != NULL) report(index, r, slot, report_ctx);
        index++;
        p = end == NULL ? p + strlen(p) : end + 1;
    }
    return refused;
}
