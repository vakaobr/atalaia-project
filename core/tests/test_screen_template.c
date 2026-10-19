/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Declarative screen templates (atalaia/screen_template.h): the YAML subset,
 * the template checks and the expressions.
 */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "atalaia/screen_template.h"
#include "check.h"

static atalaia_tpl_t tpl; /* 6 KB: not on the stack */
static char err[160];

static bool parse(const char *src)
{
    return atalaia_tpl_parse(&tpl, src, strlen(src), err, sizeof(err));
}

/* The template is refused and the reason mentions `why`. */
static void refused(const char *src, const char *why)
{
    if (parse(src)) {
        fprintf(stderr, "FAIL template accepted, expected \"%s\":\n%s\n", why, src);
        check_failures++;
    } else if (strstr(err, why) == NULL) {
        fprintf(stderr, "FAIL template refused with \"%s\", expected \"%s\"\n", err, why);
        check_failures++;
    }
}

static const char *text(const char *t, const char *data, const char *params)
{
    static char out[ATALAIA_TPL_TEXT_MAX];
    atalaia_tpl_scope_t scope = {data, params};
    atalaia_tpl_text(t, &scope, out, sizeof(out));
    return out;
}

static void same(const char *got, const char *want, int line)
{
    if (strcmp(got, want) != 0) {
        fprintf(stderr, "FAIL %s:%d: got \"%s\", want \"%s\"\n", __FILE__, line, got, want);
        check_failures++;
    }
}
#define SAME(got, want) same((got), (want), __LINE__)

/* The ADR-P3-4 example, as written there (flow mappings for style). */
static const char *countdown = "# modes/bomb/assets/screens/countdown.yaml\n"
                               "template: countdown\n"
                               "layout:\n"
                               "  - type: label\n"
                               "    id: time_left\n"
                               "    text: \"{left}\"\n"
                               "    style: { font_size: 72, align: center, color: team }\n"
                               "  - type: progress_bar\n"
                               "    id: fuse_bar\n"
                               "    value: \"{left / params.fuse_s}\"\n"
                               "    style: { height: 16, color: team }\n"
                               "  - type: label\n"
                               "    id: status_text\n"
                               "    text: \"ARMED\"   # a comment\n"
                               "    style: { font_size: 24, align: center }\n";

static void test_adr_example(void)
{
    CHECK(parse(countdown));
    if (err[0]) fprintf(stderr, "  %s\n", err);
    CHECK(strcmp(atalaia_tpl_str(&tpl, tpl.name), "countdown") == 0);
    CHECK(tpl.count == 3);
    const atalaia_tpl_widget_t *w = tpl.w;
    CHECK(w[0].type == ATALAIA_TPL_LABEL && w[0].parent == -1 && w[0].depth == 0);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[0].id), "time_left") == 0);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[0].content), "{left}") == 0);
    CHECK(w[0].font_size == 72 && w[0].align == ATALAIA_TPL_ALIGN_CENTER);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[0].color), "team") == 0);
    CHECK(w[0].width == ATALAIA_TPL_AUTO && w[0].height == ATALAIA_TPL_AUTO);
    CHECK(w[1].type == ATALAIA_TPL_PROGRESS_BAR && w[1].height == 16);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[1].content), "{left / params.fuse_s}") == 0);
    CHECK(w[2].type == ATALAIA_TPL_LABEL && w[2].visible == 0);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[2].content), "ARMED") == 0);
    CHECK(atalaia_tpl_str(&tpl, w[2].color) == NULL);

    /* Interpolation as the plan's test asks: {left} and {left / params.fuse_s}. */
    atalaia_tpl_scope_t scope = {"{\"left\":150}", "{\"fuse_s\":300,\"attackers\":\"red\"}"};
    char out[ATALAIA_TPL_TEXT_MAX];
    atalaia_tpl_text(atalaia_tpl_str(&tpl, w[0].content), &scope, out, sizeof(out));
    SAME(out, "150");
    CHECK(fabs(atalaia_tpl_fraction(atalaia_tpl_str(&tpl, w[1].content), &scope) - 0.5) < 1e-9);
}

static void test_layout_and_styles(void)
{
    CHECK(parse("template: zone_a1\n"
                "style:\n"
                "  background: \"{team}\"\n"
                "layout:\n"
                "- type: row\n"
                "  style: { width: fill, height: 44, background: panel, padding: 4 }\n"
                "  children:\n"
                "    - type: icon\n"
                "      icon: ok\n"
                "    - type: column\n"
                "      style:\n"
                "        padding: { top: 1, right: 2, bottom: 3, left: 4 }\n"
                "        visible: \"{team && !error}\"\n"
                "      children:\n"
                "      - type: label\n"
                "        text: 'it''s {team|upper}'\n"
                "        style: { color: '#A0b1C2', align: left }\n"
                "      - { type: qr_code, data: \"atalaia:join:{code}\" }\n"
                "- type: spacer\n"
                "  height: fill\n"
                "- type: label\n"
                "  text: \"tab\\there \\u00e7 \\\"q\\\" {{literal}}\"\n"
                "  style: { visible: false, width: 200 }\n"));
    if (err[0]) fprintf(stderr, "  %s\n", err);
    CHECK(tpl.count == 7);
    CHECK(strcmp(atalaia_tpl_str(&tpl, tpl.background), "{team}") == 0);
    const atalaia_tpl_widget_t *w = tpl.w;
    CHECK(w[0].type == ATALAIA_TPL_ROW && w[0].width == ATALAIA_TPL_FILL && w[0].height == 44);
    CHECK(w[0].pad[0] == 4 && w[0].pad[3] == 4);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[0].background), "panel") == 0);
    CHECK(w[1].type == ATALAIA_TPL_ICON && w[1].parent == 0 && w[1].depth == 1);
    CHECK(w[2].type == ATALAIA_TPL_COLUMN && w[2].parent == 0);
    CHECK(w[2].pad[0] == 1 && w[2].pad[1] == 2 && w[2].pad[2] == 3 && w[2].pad[3] == 4);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[2].visible), "{team && !error}") == 0);
    CHECK(w[3].type == ATALAIA_TPL_LABEL && w[3].parent == 2 && w[3].depth == 2);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[3].content), "it's {team|upper}") == 0);
    CHECK(w[3].align == ATALAIA_TPL_ALIGN_LEFT);
    CHECK(w[4].type == ATALAIA_TPL_QR_CODE && w[4].parent == 2);
    CHECK(w[5].type == ATALAIA_TPL_SPACER && w[5].height == ATALAIA_TPL_FILL && w[5].parent == -1);
    CHECK(w[6].width == 200);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[6].content), "tab\there \xc3\xa7 \"q\" {{literal}}") == 0);
    CHECK(strcmp(atalaia_tpl_str(&tpl, w[6].visible), "false") == 0);
    SAME(text(atalaia_tpl_str(&tpl, w[6].content), "{}", NULL),
         "tab\there \xc3\xa7 \"q\" {literal}");
    SAME(text(atalaia_tpl_str(&tpl, w[4].content), "{\"code\":\"AbC\"}", NULL), "atalaia:join:AbC");

    atalaia_tpl_scope_t s = {"{\"team\":\"red\",\"error\":false}", NULL};
    CHECK(atalaia_tpl_truthy(atalaia_tpl_str(&tpl, w[2].visible), &s));
    s.data = "{\"team\":\"red\",\"error\":true}";
    CHECK(!atalaia_tpl_truthy(atalaia_tpl_str(&tpl, w[2].visible), &s));
    CHECK(!atalaia_tpl_truthy("false", &s));
    CHECK(atalaia_tpl_truthy(NULL, &s));
    CHECK(strcmp(atalaia_tpl_type_name(ATALAIA_TPL_QR_CODE), "qr_code") == 0);
}

static void test_expressions(void)
{
    const char *d = "{\"left\":7,\"big\":5400,\"huge\":1e22,\"team\":\"red\",\"zero\":0,\"f\":2.5,"
                    "\"neg\":-3,"
                    "\"ok\":true,\"no\":false,\"none\":null,\"name\":\"a\\\"b\\u00e7\","
                    "\"obj\":{\"inner\":{\"x\":4},\"s\":\"deep\"},\"list\":[1,2]}";
    const char *p = "{\"fuse_s\":300,\"attackers\":\"blue\"}";
    SAME(text("{left}", d, p), "7");
    SAME(text("{left|clock}", d, p), "0:07");
    SAME(text("{big|clock}", d, p), "1:30:00");
    SAME(text("{neg|clock}", d, p), "0:00");
    /* Beyond long long's range: clamped to 1e15 s, not converted (undefined). */
    SAME(text("{huge|clock}", d, p), "277777777777:46:40");
    SAME(text("{-huge|clock}", d, p), "0:00");
    SAME(text("{f}", d, p), "2.5");
    SAME(text("{f|int}", d, p), "2");
    SAME(text("{1/3}", d, p), "0.33");
    SAME(text("{team|upper} wins", d, p), "RED wins");
    SAME(text("Armed by {params.attackers|upper}", d, p), "Armed by BLUE");
    SAME(text("{missing}|{missing|upper}|{missing + 1}", d, p), "||1");
    SAME(text("{obj.inner.x * 2}", d, p), "8");
    SAME(text("{obj.s}", d, p), "deep");
    SAME(text("{obj}{list}", d, p), "");
    SAME(text("{name}", d, p), "a\"b\xc3\xa7");
    SAME(text("{ok} {no} {none}", d, p), "true false ");
    /* Division by zero is 0. */
    SAME(text("{left / zero}", d, p), "0");
    SAME(text("{left / missing}", d, p), "0");
    SAME(text("{(left + 3) * 2 - -1}", d, p), "21");
    SAME(text("{left - 2 * 3}", d, p), "1");
    SAME(text("{left <= 10}{left > 10}{left == 7}{left != 7}", d, p), "1010");
    SAME(text("{team == 'red'}{team != 'red'}{team < 'z'}{team == 7}{team != 7}", d, p), "10101");
    SAME(text("{!team}{!missing}{!0}{!!left}", d, p), "0111");
    /* && and || give the deciding operand, as in Lua. */
    SAME(text("{left <= 10 && 'danger' || 'white'}", d, p), "danger");
    SAME(text("{big <= 10 && 'danger' || 'white'}", d, p), "white");
    SAME(text("{missing || 'none'}", d, p), "none");
    SAME(text("{team && left}", d, p), "7");
    SAME(text("{{}} {{{left}}}", d, p), "{} {7}");
    /* No data at all. */
    SAME(text("[{left}]", NULL, NULL), "[]");

    atalaia_tpl_scope_t s = {d, p};
    CHECK(fabs(atalaia_tpl_fraction("{left / params.fuse_s}", &s) - 7.0 / 300.0) < 1e-12);
    CHECK(atalaia_tpl_fraction("{big}", &s) == 1.0);
    CHECK(atalaia_tpl_fraction("{neg}", &s) == 0.0);
    CHECK(atalaia_tpl_fraction("0.25", &s) == 0.25);
    CHECK(atalaia_tpl_fraction("{left / zero}", &s) == 0.0);
    CHECK(atalaia_tpl_truthy("{ok && left > 5}", &s));
    CHECK(!atalaia_tpl_truthy("{no || none}", &s));

    /* Output is cut to fit. */
    char small[5];
    atalaia_tpl_scope_t sc = {d, p};
    CHECK(atalaia_tpl_text("{big|clock}", &sc, small, sizeof(small)) == 4);
    CHECK(strcmp(small, "1:30") == 0);

    char why[64];
    CHECK(atalaia_tpl_expr_ok("a + (b * 2)", 11, why, sizeof(why)));
    CHECK(!atalaia_tpl_expr_ok("a +", 3, why, sizeof(why)));
    CHECK(!atalaia_tpl_expr_ok("(a", 2, why, sizeof(why)) && strstr(why, ")") != NULL);
    CHECK(!atalaia_tpl_expr_ok("a b", 3, why, sizeof(why)));
    CHECK(!atalaia_tpl_expr_ok("'open", 5, why, sizeof(why)));
    CHECK(!atalaia_tpl_expr_ok("f(x)", 4, why, sizeof(why)));
    CHECK(!atalaia_tpl_expr_ok("a = 1", 5, why, sizeof(why)));
    CHECK(!atalaia_tpl_expr_ok("1.2.3", 5, why, sizeof(why)));
}

static void test_colors(void)
{
    uint32_t rgb = 0;
    CHECK(atalaia_tpl_color("red", &rgb) && rgb == 0xE53935);
    CHECK(atalaia_tpl_color("Blue", &rgb) && rgb == 0x1E88E5);
    CHECK(atalaia_tpl_color("#0a0B0c", &rgb) && rgb == 0x0A0B0C);
    CHECK(atalaia_tpl_color("panel", &rgb) && rgb == 0x222B35);
    CHECK(!atalaia_tpl_color("#12345", &rgb));
    CHECK(!atalaia_tpl_color("#12345g", &rgb));
    CHECK(!atalaia_tpl_color("verde", &rgb));
    CHECK(!atalaia_tpl_color("", &rgb));
    CHECK(!atalaia_tpl_color(NULL, &rgb));
}

static void test_invalid_yaml(void)
{
    refused("template: x\nlayout:\n\t- type: label\n", "tabs");
    refused("template: \"x\nlayout: []\n", "unterminated");
    refused("template: x\nlayout:\n  - type: label\n     text: a\n", "indentation");
    refused("template: x\nlayout: [a, b]\n", "flow sequences");
    refused("template: &a x\nlayout:\n  - type: label\n", "anchors");
    refused("template: x\nlayout:\n  - type: label\n    text: |\n      hi\n", "block scalars");
    refused("template: x\ntemplate: y\nlayout:\n  - type: spacer\n    height: 4\n",
            "duplicate key");
    refused("template: x\n---\nlayout:\n  - type: spacer\n", "one YAML document");
    refused("template: x\nlayout:\n  - type: label\n    style: { color: red, }\n", "trailing ','");
    refused("template: x\nlayout:\n  - type: label\n    style: { color: { a: 1 } }\n", "nested");
    refused("template: x\nlayout:\n  - type: label\n    text: a: b\n", "': '");
    refused("template: x\nlayout:\n  - type: label\n    text: \"a\" b\n", "after a quoted");
    refused("template: x\nlayout:\n  - type: label\n    text: \"\\q\"\n", "unknown escape");
    refused("  template: x\n", "column 1");
    refused("just text\n", "key: value");
    refused("", "empty");
    refused("# only a comment\n\n", "empty");
    refused("- a\n- b\n", "mapping");
}

static void test_invalid_templates(void)
{
    refused("layout:\n  - type: spacer\n    height: 4\n", "no name");
    refused("template: Bad-Name\nlayout:\n  - type: spacer\n    height: 4\n", "template names");
    refused("template: x\n", "layout");
    refused("template: x\nlayout:\n", "layout");
    refused("template: x\nlayout:\n  - type: slider\n", "unknown widget type 'slider'");
    refused("template: x\nlayout:\n  - text: a\n", "needs a type");
    refused("template: x\nlayout:\n  - type: label\n", "needs text");
    refused("template: x\nlayout:\n  - type: label\n    text: a\n    value: 1\n",
            "no property 'value'");
    refused("template: x\nlayout:\n  - type: label\n    text: a\n    style: { blink: true }\n",
            "unknown style property 'blink'");
    refused("template: x\nlayout:\n  - type: label\n    text: a\n    style: { color: pink }\n",
            "not a colour");
    refused("template: x\nlayout:\n  - type: label\n    text: a\n    style: { font_size: big }\n",
            "font_size");
    refused("template: x\nlayout:\n  - type: label\n    text: a\n    style: { align: middle }\n",
            "align");
    refused("template: x\nlayout:\n  - type: label\n    text: a\n    style: { width: half }\n",
            "width");
    refused("template: x\nlayout:\n  - type: label\n    text: a\n    style:\n      padding: { up: "
            "1 }\n",
            "padding");
    /* A flow mapping inside a flow mapping is not part of the subset. */
    refused(
        "template: x\nlayout:\n  - type: label\n    text: a\n    style: { padding: { top: 1 } }\n",
        "cannot be nested");
    refused("template: x\nlayout:\n  - type: label\n    text: a\n    style: { visible: maybe }\n",
            "visible must be");
    refused("template: x\nlayout:\n  - type: label\n    text: \"{left +}\"\n", "{left +}");
    refused("template: x\nlayout:\n  - type: label\n    text: \"{left|bold}\"\n", "unknown filter");
    refused("template: x\nlayout:\n  - type: label\n    text: \"{left\"\n", "without its '}'");
    refused("template: x\nlayout:\n  - type: label\n    text: \"a}\"\n", "without its '{'");
    refused(
        "template: x\nlayout:\n  - type: label\n    text: a\n    style: { color: \"{t|upper}\" }\n",
        "filters are only for text");
    refused("template: x\nlayout:\n  - type: progress_bar\n    value: lots\n",
            "progress_bar value");
    refused("template: x\nlayout:\n  - type: icon\n    icon: dragon\n", "unknown icon");
    refused("template: x\nlayout:\n  - type: spacer\n", "spacer needs a height");
    refused("template: x\nlayout:\n  - type: row\n", "needs children");
    refused("template: x\nlayout:\n  - type: row\n    children: a\n", "list of widgets");
    refused("template: x\nstyle: { color: red }\nlayout:\n  - type: spacer\n    height: 1\n",
            "only a background");
    refused("template: x\nscreen: 2\nlayout:\n  - type: spacer\n    height: 1\n", "unknown key");

    /* Nesting depth: rows and columns at most ATALAIA_TPL_DEPTH_MAX deep. */
    char deep[1024];
    size_t n = (size_t)snprintf(deep, sizeof(deep), "template: x\nlayout:\n");
    int levels = ATALAIA_TPL_DEPTH_MAX + 1;
    for (int i = 0; i < levels; i++) {
        n += (size_t)snprintf(deep + n, sizeof(deep) - n, "%*s- type: column\n%*schildren:\n",
                              2 + 4 * i, "", 4 + 4 * i, "");
    }
    snprintf(deep + n, sizeof(deep) - n, "%*s- type: spacer\n%*sheight: 1\n", 2 + 4 * levels, "",
             4 + 4 * levels, "");
    refused(deep, "nest at most");

    /* Too many widgets. */
    static char many[4096];
    n = (size_t)snprintf(many, sizeof(many), "template: x\nlayout:\n");
    for (int i = 0; i <= ATALAIA_TPL_WIDGETS_MAX; i++) {
        n += (size_t)snprintf(many + n, sizeof(many) - n, "  - { type: spacer, height: 1 }\n");
    }
    refused(many, "too many widgets");

    /* Too large a source. */
    static char big[ATALAIA_TPL_SOURCE_MAX + 2];
    memset(big, ' ', sizeof(big) - 1);
    big[sizeof(big) - 1] = '\0';
    refused(big, "larger than");
}

void run_screen_template_tests(void)
{
    test_adr_example();
    test_layout_and_styles();
    test_expressions();
    test_colors();
    test_invalid_yaml();
    test_invalid_templates();
}
