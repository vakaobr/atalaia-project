// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Players' NFC tags (protocol/nfc-tag.md, ADR-P3-9), for the GM, under the Check-in tab: the controller
// signs one tag for a player and a team with the live game's key (POST /api/v1/games/{id}/tags, which
// never shows the key) and this page gets the tag's bytes to write:
//   - with Web NFC (NDEFReader: Chrome on Android, over HTTPS) the page writes the tag itself, the same
//     one NDEF record the Atalaia app writes;
//   - otherwise the bytes are shown as hex (and as a file to download), with the app that can write them:
//     the Atalaia app (the marshal's Players' tags screen asks this controller; a phone controller has
//     its own screen), or an NFC app that writes a raw NDEF record from hex.

import { html, Component, t, inWebView } from '../ui.js';

const MIME = 'application/vnd.atalaia.tag';

function bytesOf(hex) {
    const out = new Uint8Array(hex.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(2 * i, 2 * i + 2), 16);
    return out;
}

/** Whether this browser can write NFC tags (Web NFC needs a secure context). */
export function canWriteNfc() {
    return typeof window.NDEFReader === 'function' && window.isSecureContext !== false;
}

export class TagWriter extends Component {
    constructor() {
        super();
        this.state = { player: '', team: '', tag: null, busy: false, nfc: null };
        this.abort = null;
    }

    componentWillUnmount() {
        if (this.abort) this.abort.abort();
    }

    /** Picking a checked-in player (or typing their id) fills the team they are in. */
    setPlayer(player) {
        const row = (this.props.players || []).find((r) => r.player_id === player);
        this.setState({ player, ...(row && row.team ? { team: row.team } : {}), tag: null, nfc: null });
    }

    async make(e) {
        e.preventDefault();
        const { game, app } = this.props;
        const { player, team } = this.state;
        this.setState({ busy: true, nfc: null });
        const tag = await app.call('POST', `/games/${game.id}/tags`, { player: player.trim(), team: team || null });
        this.setState({ busy: false, tag: tag || null });
    }

    async writeNfc() {
        const { tag } = this.state;
        if (this.abort) this.abort.abort();
        this.abort = new AbortController();
        this.setState({ nfc: { state: 'waiting' } });
        try {
            const reader = new window.NDEFReader();
            await reader.write({ records: [{ recordType: 'mime', mediaType: MIME, data: bytesOf(tag.payload) }] },
                { signal: this.abort.signal });
            this.setState({ nfc: { state: 'done' } });
        } catch (err) {
            if (err && err.name === 'AbortError') return;
            this.setState({ nfc: { state: 'failed', error: (err && (err.message || err.name)) || String(err) } });
        }
    }

    download() {
        const { tag } = this.state;
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([bytesOf(tag.ndef)], { type: 'application/octet-stream' }));
        a.download = `atalaia-tag-${tag.player}.ndef`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }

    renderTag() {
        const { tag, nfc } = this.state;
        const native = canWriteNfc();
        return html`<div class="tag-result" data-testid="tag-result">
            <p><strong data-testid="tag-for">${tag.team
        ? t('tags.for', { player: tag.player, team: tag.team })
        : t('tags.for_no_team', { player: tag.player })}</strong>${
            ` · ${t('tags.bytes', { n: tag.payload.length / 2 })}`}</p>
            ${native && html`<div class="actions"><button type="button" class="primary" data-testid="tag-nfc-write"
                disabled=${nfc && nfc.state === 'waiting'} onClick=${() => this.writeNfc()}>${t('tags.nfc_write')}</button></div>`}
            ${nfc && nfc.state === 'waiting' && html`<p role="status" data-testid="tag-nfc-waiting">${t('tags.nfc_hold')}</p>`}
            ${nfc && nfc.state === 'done' && html`<p class="ok" role="status" data-testid="tag-nfc-done">${t('tags.nfc_done')}</p>`}
            ${nfc && nfc.state === 'failed' && html`<p class="notice" role="alert" data-testid="tag-nfc-failed">${
                t('tags.nfc_failed', { error: nfc.error })}</p>`}
            ${!native && html`<p class="muted small" data-testid="tag-nfc-unsupported">${t('tags.nfc_unsupported')}</p>`}
            <label for="tag-ndef">${t('tags.ndef')}</label>
            <code class="hex" id="tag-ndef" data-testid="tag-ndef">${tag.ndef}</code>
            <details><summary>${t('tags.memory')}</summary>
                <code class="hex" data-testid="tag-memory">${tag.memory}</code></details>
            <div class="actions">
                ${!inWebView() && html`<button type="button" data-testid="tag-download" onClick=${() => this.download()}>${
                    t('tags.download')}</button>`}
                <button type="button" data-testid="tag-hide" onClick=${() => this.setState({ tag: null, nfc: null })}>${
                    t('tags.hide')}</button>
            </div>
        </div>`;
    }

    render(props) {
        const { game, players } = props;
        const { player, team, busy, tag } = this.state;
        const known = (players || []).filter((r) => r.status === 'pending' || r.status === 'checked_in');
        return html`<section class="card" aria-labelledby="tags-h" data-testid="tags">
            <h2 id="tags-h">${t('tags.title')}</h2>
            <p class="muted">${t('tags.intro')}</p>
            <p class="small" data-testid="tags-game">${t('tags.game', { game: game.name })}</p>
            <form class="form" data-testid="tags-form" onSubmit=${(e) => this.make(e)}>
                <div class="field"><label for="tag-player">${t('tags.player')}</label>
                    <input id="tag-player" data-testid="tag-player" list="tag-players" required maxlength="32"
                        pattern="[A-Za-z0-9._\\-]{1,32}" autocomplete="off" autocapitalize="off" spellcheck="false"
                        value=${player} onInput=${(e) => this.setPlayer(e.target.value)} />
                    <datalist id="tag-players">${known.map((r) => html`<option value=${r.player_id}>${
                        r.display_name || ''}</option>`)}</datalist>
                    <p class="muted small">${t('tags.player_hint')}</p></div>
                <div class="field"><label for="tag-team">${t('tags.team')}</label>
                    <select id="tag-team" data-testid="tag-team" value=${team}
                        onChange=${(e) => this.setState({ team: e.target.value, tag: null, nfc: null })}>
                        <option value="">${t('tags.no_team')}</option>
                        ${game.teams.map((tm) => html`<option value=${tm}>${tm}</option>`)}</select></div>
                <button type="submit" class="primary" data-testid="tag-make" disabled=${busy}>${t('tags.make')}</button>
            </form>
            ${tag && this.renderTag()}
        </section>`;
    }
}
