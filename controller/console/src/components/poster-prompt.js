// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// "Print the check-in poster?": a suggestion shown after a GM creates a game (decisions
// check-R10 to check-R17). It names the game, offers the poster page (the Check-in tab's own
// link) and closes itself after ten seconds, with the seconds left in sight; Esc or the Close
// button close it sooner; "Don't show this again" is kept in this browser (localStorage, like
// the other console preferences).
//
// Keyboard and screen readers: focus moves to the dialog (its box, not a button, so a key the GM
// was still typing cannot press one) and returns to where it was, or to the page's content when
// that is gone (the create form is replaced by the game). A GM who is typing in a field when it
// opens keeps the focus there: the dialog then shows without a backdrop (aria-modal false) and
// Esc still closes it. The countdown is a visible number (hidden from screen readers) and a
// polite live region that says "closes in N seconds" when it opens and halfway.

import { html, Component, createRef, t } from '../ui.js';

export const PROMPT_SECONDS = 10;
const KEY = 'atalaia.posterPrompt';
const TYPING_TYPES = new Set(['button', 'submit', 'reset', 'checkbox', 'radio', 'range', 'color', 'file', 'image']);

/** Whether the prompt is wanted in this browser (the GM has not chosen "Don't show this again"). */
export function posterPromptWanted() {
    try {
        return window.localStorage.getItem(KEY) !== 'off';
    } catch (e) {
        return true;
    }
}

export function setPosterPromptWanted(wanted) {
    try {
        if (wanted) window.localStorage.removeItem(KEY);
        else window.localStorage.setItem(KEY, 'off');
    } catch (e) {
        /* private mode: the choice is just not remembered */
    }
}

/** An element in which a person types text (a key pressed now would go into it). */
export function isTyping(el) {
    if (!el || !el.tagName) return false;
    if (el.isContentEditable || el.tagName === 'TEXTAREA') return true;
    return el.tagName === 'INPUT' && !TYPING_TYPES.has((el.type || 'text').toLowerCase());
}

/** The page's content, as a place for focus to go back to when the element that had it is gone. */
function pageContent() {
    const main = document.querySelector('main.content');
    if (main && !main.hasAttribute('tabindex')) main.setAttribute('tabindex', '-1');
    return main;
}

export class PosterPrompt extends Component {
    // props: app, game ({id, name}), typing (the GM was typing in a field), onClose()
    constructor(props) {
        super(props);
        this.state = { left: PROMPT_SECONDS, never: false, announce: '' };
        this.box = createRef();
        this.onKeyDown = (e) => this.keyDown(e);
    }

    componentDidMount() {
        const active = document.activeElement;
        this.typing = this.props.typing || isTyping(active);
        this.modal = !this.typing;
        this.opener = active && active !== document.body ? active : null;
        if (this.modal && this.box.current) this.box.current.focus();
        this.setState({ announce: t('poster_prompt.announce', { n: PROMPT_SECONDS }) });
        this.deadline = Date.now() + PROMPT_SECONDS * 1000;
        this.timer = setInterval(() => this.tick(), 250);
        document.addEventListener('keydown', this.onKeyDown, true);
    }

    componentDidUpdate() {
        // The boxes' dialog is the GM's next step: it takes over (and keeps the focus it moves).
        if (this.props.app.state.invitePicker) this.close(false);
    }

    componentWillUnmount() {
        clearInterval(this.timer);
        document.removeEventListener('keydown', this.onKeyDown, true);
    }

    tick() {
        const left = Math.max(0, Math.ceil((this.deadline - Date.now()) / 1000));
        if (left !== this.state.left) {
            const half = Math.floor(PROMPT_SECONDS / 2);
            this.setState({ left, announce: left === half ? t('poster_prompt.announce', { n: left }) : this.state.announce });
        }
        if (left <= 0) this.close(true);
    }

    keyDown(e) {
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            this.close(true);
        } else if (e.key === 'Tab' && this.modal && this.box.current) {
            // A modal keeps Tab inside it.
            const items = [...this.box.current.querySelectorAll('a[href], button, input')];
            if (!items.length) return;
            const first = items[0];
            const last = items[items.length - 1];
            const active = document.activeElement;
            if (e.shiftKey && (active === first || active === this.box.current)) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && active === last) {
                e.preventDefault();
                first.focus();
            } else if (!this.box.current.contains(active)) {
                e.preventDefault();
                first.focus();
            }
        }
    }

    /** Closes it; `giveBack`: the focus goes back to where it was (not when another dialog has taken it). */
    close(giveBack) {
        if (this.closed) return;
        this.closed = true;
        if (this.state.never) setPosterPromptWanted(false);
        const had = this.box.current && this.box.current.contains(document.activeElement);
        this.props.onClose();
        if (giveBack && this.modal && had) {
            const to = this.opener && this.opener.isConnected ? this.opener : pageContent();
            if (to) to.focus();
        }
    }

    render(props, state) {
        const { game } = props;
        const sr = 'sr-only';
        return html`<div class=${this.modal ? 'modal-backdrop' : 'modal-floating'}
            onClick=${(e) => this.modal && e.target === e.currentTarget && this.close(true)}>
            <div class="modal card poster-prompt" role="dialog" aria-modal=${this.modal ? 'true' : 'false'}
                aria-labelledby="pp-h" aria-describedby="pp-body" tabindex="-1" ref=${this.box}
                data-testid="poster-prompt" data-modal=${this.modal ? 'true' : 'false'}>
                <h2 id="pp-h">${t('poster_prompt.title')}</h2>
                <p id="pp-body" data-testid="poster-prompt-body">${t('poster_prompt.body', { game: game.name })}</p>
                <p class="muted small" aria-hidden="true" data-testid="poster-prompt-countdown">${
                    t('poster_prompt.countdown', { n: state.left })}</p>
                <div class=${sr} role="status" aria-live="polite" data-testid="poster-prompt-live">${state.announce}</div>
                <div class="field"><label><input type="checkbox" data-testid="poster-prompt-never" checked=${state.never}
                    onChange=${(e) => this.setState({ never: e.target.checked })} /> ${t('poster_prompt.never')}</label></div>
                <div class="actions">
                    <a class="button primary" href="poster.html" target="_blank" rel="noopener"
                        data-testid="poster-prompt-open" onClick=${() => setTimeout(() => this.close(false), 0)}>${t('poster_prompt.open')}</a>
                    <button type="button" data-testid="poster-prompt-close" onClick=${() => this.close(true)}>${
                        t('poster_prompt.close')}</button>
                </div>
            </div>
        </div>`;
    }
}

/** Settings: bring the suggestion back after "Don't show this again". */
export class PosterPromptSetting extends Component {
    constructor(props) {
        super(props);
        this.state = { wanted: posterPromptWanted() };
    }

    render(props, state) {
        return html`<section class="card" aria-labelledby="pps-h">
            <h2 id="pps-h">${t('poster_prompt.setting_title')}</h2>
            <label><input type="checkbox" data-testid="poster-prompt-setting" checked=${state.wanted}
                onChange=${(e) => { setPosterPromptWanted(e.target.checked); this.setState({ wanted: e.target.checked }); }} />
                ${' '}${t('poster_prompt.setting')}</label>
        </section>`;
    }
}
