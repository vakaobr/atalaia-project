// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Names the box cannot draw (PKE-3, follow-up of decision P5K-5). The Field Box's fonts carry the letters of
// Portuguese, German and English and, in Traditional Chinese, only those of the box's own texts and the built-in
// modes' templates (a field's every Han letter would not fit the 2 MB slot). A name a GM types (a team's, a game
// preset's, the field's) with a letter the fonts lack shows on a box as "?" in a mode's template and as an empty
// square on the box's own screens, while the app and this console draw every letter. This warns where the name is
// typed, with the letters concerned, from box-glyphs.json (made by tools/gen_box_fonts.py together with the fonts,
// so it cannot drift from them). A warning only: the name is accepted as typed, since it reads fine everywhere else.

import { html, Component, t } from '../ui.js';

const SIZES = ['14', '20', '28']; // where names are drawn; the 48 px font falls back on the 28 px one
const LISTED = 12;

let loaded = null;

/** The tables, fetched once; null when the file cannot be had (an older controller: no warning then). */
export function loadGlyphs() {
    if (!loaded) {
        loaded = fetch('box-glyphs.json', { cache: 'no-cache' }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    }
    return loaded;
}

/** The distinct letters of ``text`` the box cannot draw in any size (``none``) and those it has in only some
 * sizes (``some``), given the tables ({latin: [[lo, hi]], cjk: {size: [code points]}}). Spaces and control
 * characters are no letters. */
export function glyphProblems(text, glyphs) {
    const none = [];
    const some = [];
    if (!glyphs || typeof text !== 'string') return { none, some };
    const sets = SIZES.map((s) => new Set(glyphs.cjk[s] || []));
    for (const ch of new Set(Array.from(text))) {
        const cp = ch.codePointAt(0);
        if (cp <= 0x20 || (cp >= 0x7f && cp <= 0x9f)) continue;
        if (glyphs.latin.some(([lo, hi]) => cp >= lo && cp <= hi)) continue;
        const has = sets.filter((s) => s.has(cp)).length;
        if (has === 0) none.push(ch);
        else if (has < sets.length) some.push(ch);
    }
    return { none, some };
}

function listed(chars) {
    const shown = chars.slice(0, LISTED).join(' ');
    return chars.length > LISTED ? `${shown} …` : shown;
}

/** Under a name's input: the warning when the text has letters the box's fonts lack; nothing otherwise.
 * ``text`` is one text or a list of them. */
export class GlyphWarning extends Component {
    constructor() {
        super();
        this.state = { glyphs: null };
    }

    componentDidMount() {
        loadGlyphs().then((glyphs) => this.setState({ glyphs }));
    }

    render({ text, testid = 'glyph-warning' }, { glyphs }) {
        if (!glyphs) return null;
        const { none, some } = glyphProblems(Array.isArray(text) ? text.join(' ') : text, glyphs);
        if (!none.length && !some.length) return null;
        return html`<div class="muted small glyph-warning" role="status" data-testid=${testid}>
            ${none.length > 0 && html`<p data-testid="glyph-none">${t('glyphs.none', { letters: listed(none) })}</p>`}
            ${some.length > 0 && html`<p data-testid="glyph-some">${t('glyphs.some', { letters: listed(some) })}</p>`}
        </div>`;
    }
}
