// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Adopting boxes (protocol/adoption.md, decisions AD-*), for the GM, under the
// Adopt tab: a new Field Box gets the field join key once, by
//   - the NFC field card: its bytes, to write on an NTAG215/216 and tap on each
//     new box; the card is the field's master secret, and the page says so;
//   - the USB cable: the boxes plugged into the controller, each with its name,
//     MAC and adoption state; the GM confirms the one to adopt (with the box's
//     admin PIN when it belongs to another field or to this field's old key).
// A pairing code over LoRa (the third way) comes with the radio invites.

import { html, Component, t } from '../ui.js';

const OK = ['adopted', 'same', 'readopted'];

export class AdoptPanel extends Component {
    constructor() {
        super();
        this.state = { info: null, card: null, scan: null, scanning: false, confirm: null, pin: '',
                       result: null, adopting: false };
    }

    componentDidMount() {
        if (this.props.app.state.role === 'gm') this.load(); // GM only: a read token is refused
    }

    async load() {
        const info = await this.props.app.call('GET', '/adopt');
        if (info) this.setState({ info });
    }

    async makeCard() {
        const card = await this.props.app.call('POST', '/adopt/card');
        if (card) this.setState({ card });
        this.load();
    }

    async scan() {
        this.setState({ scanning: true, result: null, confirm: null });
        const scan = await this.props.app.call('POST', '/adopt/usb/scan');
        this.setState({ scanning: false, scan: scan || this.state.scan });
    }

    async adopt(e) {
        e.preventDefault();
        const box = this.state.confirm;
        const body = { port: box.port, mac: box.mac };
        if (this.state.pin) body.pin = this.state.pin;
        this.setState({ adopting: true });
        const out = await this.props.app.call('POST', '/adopt/usb', body);
        this.setState({ adopting: false });
        if (!out) return;
        const scan = this.state.scan
            ? { ...this.state.scan, boxes: this.state.scan.boxes.map((b) => (b.port === out.box.port ? out.box : b)) }
            : null;
        const keep = out.result === 'need_pin' || out.result === 'bad_pin';
        this.setState({ result: { ...out, name: box.name, mac: box.mac }, scan,
                        confirm: keep ? out.box : null, pin: '' });
        this.load();
    }

    stateText(b) {
        if (b.relation === 'this_field') return t('adopt.state.this_field');
        if (b.relation === 'previous_key') return t('adopt.state.previous_key', { field: b.field });
        if (b.relation === 'other_field') {
            return t('adopt.state.other_field', { field: b.field, name: b.field_name || '—' });
        }
        return t('adopt.state.none');
    }

    renderField() {
        const { info } = this.state;
        return html`<section class="card" aria-labelledby="adopt-h">
            <h2 id="adopt-h">${t('adopt.title')}</h2>
            <p class="muted">${t('adopt.intro')}</p>
            ${info && html`<p data-testid="adopt-field">${t('adopt.field', { name: info.field_name || '—' })}
                <strong class="mono">${info.fingerprint}</strong></p>
                ${info.previous_fingerprint && html`<p class="muted small" data-testid="adopt-previous">${
                    t('adopt.previous', { field: info.previous_fingerprint })}</p>`}`}
        </section>`;
    }

    renderCard() {
        const { card } = this.state;
        return html`<section class="card" aria-labelledby="adopt-card-h">
            <h2 id="adopt-card-h">${t('adopt.card_title')}</h2>
            <p class="muted">${t('adopt.card_intro')}</p>
            <p class="warning" role="note" data-testid="adopt-card-warning">${t('adopt.card_warning')}</p>
            ${!card && html`<button type="button" class="primary" data-testid="adopt-card-make"
                onClick=${() => this.makeCard()}>${t('adopt.card_make')}</button>`}
            ${card && html`<div data-testid="adopt-card">
                <p><strong>${t('adopt.card_for', { name: card.field_name || '—', field: card.fingerprint })}</strong>
                    ${` · ${t('join.bytes', { n: card.bytes })}`}</p>
                <p class="muted small">${t('adopt.card_hint')}</p>
                <code class="hex" data-testid="adopt-card-ndef">${card.ndef_tag_hex}</code>
                <div class="actions"><button type="button" onClick=${() => this.setState({ card: null })}>${
                    t('adopt.card_hide')}</button></div>
            </div>`}
            <p class="muted small" data-testid="adopt-card-lost">${t('adopt.card_lost')}</p>
        </section>`;
    }

    renderConfirm() {
        const b = this.state.confirm;
        const needPin = b.relation === 'other_field' || b.relation === 'previous_key';
        return html`<form class="form confirm-box" data-testid="adopt-confirm" onSubmit=${(e) => this.adopt(e)}>
            <p><strong>${t('adopt.confirm', { name: b.name, mac: b.mac })}</strong></p>
            <p class="muted small">${t('adopt.confirm_hint')}</p>
            ${needPin && html`<div class="field"><label for="adopt-pin">${t('adopt.pin')}</label>
                <input id="adopt-pin" data-testid="adopt-pin" inputmode="numeric" pattern="[0-9]{1,8}"
                    autocomplete="off" required value=${this.state.pin}
                    onInput=${(e) => this.setState({ pin: e.target.value })} />
                <p class="muted small">${t('adopt.pin_hint')}</p></div>`}
            <div class="actions">
                <button type="submit" class="primary" data-testid="adopt-confirm-yes" disabled=${this.state.adopting}>${
                    t('adopt.adopt')}</button>
                <button type="button" onClick=${() => this.setState({ confirm: null, pin: '' })}>${t('common.cancel')}</button>
            </div>
        </form>`;
    }

    renderUsb() {
        const { scan, scanning, confirm, result, info } = this.state;
        const usbOff = info && !info.usb;
        return html`<section class="card" aria-labelledby="adopt-usb-h">
            <h2 id="adopt-usb-h">${t('adopt.usb_title')}</h2>
            <p class="muted">${t('adopt.usb_intro')}</p>
            ${usbOff ? html`<p class="notice">${t('adopt.usb_off')}</p>` : html`<button type="button" data-testid="adopt-scan"
                disabled=${scanning} onClick=${() => this.scan()}>${scanning ? t('adopt.scanning') : t('adopt.scan')}</button>`}
            ${scan && scan.boxes.length === 0 && html`<p class="muted" data-testid="adopt-none">${t('adopt.none')}</p>`}
            ${scan && scan.boxes.length > 0 && html`<ul class="list" data-testid="adopt-boxes">
                ${scan.boxes.map((b) => html`<li data-testid=${`adopt-box-${b.mac}`}>
                    <strong>${b.name || '—'}</strong> <span class="mono">${b.mac}</span>
                    <span class="muted small">${b.port}</span><br />
                    <span data-testid="adopt-box-state">${this.stateText(b)}</span>
                    ${b.busy && html` · <span class="notice">${t('adopt.busy')}</span>`}
                    ${b.locked && html` · <span class="notice">${t('adopt.locked')}</span>`}
                    ${b.relation !== 'this_field' && !b.busy && html` <button type="button" data-testid="adopt-box-adopt"
                        onClick=${() => this.setState({ confirm: b, pin: '', result: null })}>${t('adopt.adopt')}</button>`}
                </li>`)}
            </ul>`}
            ${scan && scan.silent.length > 0 && html`<details><summary>${t('adopt.silent', { n: scan.silent.length })}</summary>
                <ul class="muted small">${scan.silent.map((s) => html`<li>${s.port}: ${s.error}</li>`)}</ul></details>`}
            ${confirm && this.renderConfirm()}
            ${result && html`<p class=${OK.includes(result.result) ? 'ok' : 'notice'} role="status" data-testid="adopt-result">${
                t(`adopt.result.${result.result}`, { name: result.name, mac: result.mac })}</p>`}
        </section>`;
    }

    renderLog() {
        const log = (this.state.info && this.state.info.log) || [];
        if (log.length === 0) return null;
        return html`<section class="card" aria-labelledby="adopt-log-h">
            <h2 id="adopt-log-h">${t('adopt.log_title')}</h2>
            <ul class="list small" data-testid="adopt-log">${log.map((r) => html`<li>
                <span class="mono">${r.at}</span> · ${t(`adopt.method.${r.method}`)} · ${
                    r.method === 'usb' ? `${r.box || '—'} (${r.mac}) · ` : ''}${t(`adopt.result.${r.result}`, { name: r.box, mac: r.mac })}
            </li>`)}</ul>
        </section>`;
    }

    render(props) {
        if (props.app.state.role !== 'gm') {
            return html`<section class="card"><p class="muted">${t('adopt.gm_only')}</p></section>`;
        }
        return html`<div>
            ${this.renderField()}
            ${this.renderUsb()}
            ${this.renderCard()}
            <section class="card" aria-labelledby="adopt-code-h">
                <h2 id="adopt-code-h">${t('adopt.code_title')}</h2>
                <p class="muted" data-testid="adopt-code">${t('adopt.code_later')}</p>
            </section>
            ${this.renderLog()}
        </div>`;
    }
}
