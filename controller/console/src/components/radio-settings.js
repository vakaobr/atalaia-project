// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Settings: the field's radio region and channel (RFC 0001 Amendments 3 and
// 11). The region (EU868, or AS923 as Taiwan uses it) is picked once, after a
// confirmation: the boxes and the USB modem must be built for it, and the
// channel goes back to the region's default. The GM keeps the recommended
// channel, scans for a quiet one with the USB modem, draws one at random or
// picks one from the list; the controller keeps the choice, tunes the modem
// and puts the channel and the region in every join payload. Only while no
// game is live. Also FirstSetupNotice, shown on the game tab until the
// channel has been chosen once.

import { html, Component, t, decimal } from '../ui.js';

/** 869525000 -> "869,525" (pt, de) or "869.525" (en, zh-tw). */
export function mhz(hz) {
    return decimal((hz / 1e6).toFixed(3));
}

/** A sweep the controller's hourly cap on air time refused (decision RL-9): why, and in how many
 * minutes the next one is possible (retry_after_s counted from the request; null: never on this
 * channel's sub-band). Never an empty sweep without a reason. */
function SweepRefused({ refused, at }) {
    const duty = decimal(refused.duty_pct);
    if (refused.retry_after_s == null) {
        return html`<p class="warning small" data-testid="invite-discover-capped" data-retry="never">${
            t('invites.discover_never', { duty })}</p>`;
    }
    const left = Math.max(0, refused.retry_after_s * 1000 - (Date.now() - at));
    const minutes = Math.max(1, Math.ceil(left / 60000));
    return html`<p class="warning small" data-testid="invite-discover-capped" data-retry=${refused.retry_after_s}>${
        t('invites.discover_capped', { duty, share: decimal(refused.share_pct), minutes })}</p>`;
}

/** After "Look for boxes" (RFC 0001 Amendment 19, decision RB-13): that it was asked, the earlier
 * channels swept for boxes that were away when the field moved, how many boxes have answered since
 * (heard after the request), and what to do about one that is still missing. */
export function DiscoverResult({ app }) {
    const { discovered, boxesAt, boxes } = app.state;
    if (!discovered) return null;
    const heard = ((boxes && boxes.boxes) || []).filter((b) => b.seen_s_ago != null
        && (boxesAt || Date.now()) - b.seen_s_ago * 1000 >= discovered.at - 1500).length;
    const sweep = discovered.sweep || [];
    return html`<div data-testid="invite-discover-result" role="status" aria-live="polite">
        <p class="small" data-testid="invite-discover-sent">${t(discovered.sent ? 'invites.discover_sent'
            : 'invites.discover_recent')}</p>
        ${sweep.length > 0 && html`<p class="small" data-testid="invite-discover-sweep">${t('invites.discover_sweep',
            { channels: sweep.map((hz) => mhz(hz)).join(' MHz, ') })}</p>`}
        ${discovered.sweep_refused && html`<${SweepRefused} refused=${discovered.sweep_refused} at=${discovered.at} />`}
        <p class="small" data-testid="invite-discover-answered">${t('invites.discover_answered', { n: heard })}</p>
        <p class="muted small" data-testid="invite-missing-help">${t('invites.missing_help')}</p>
    </div>`;
}

function pct(value) {
    return decimal(value);
}

/** "10% of the time · 500 mW ERP" for a channel description from the API: the power limit
 * with what it is measured as (ERP in EU868, at the antenna port in AS923-TW, or EIRP). An
 * older controller gives only erp_mw. */
export function limits(ch) {
    const ref = ch.limit_ref || 'erp';
    const mw = ch.limit_mw !== undefined ? ch.limit_mw : ch.erp_mw;
    const key = ref === 'conducted' ? 'radio.limits_conducted' : ref === 'eirp' ? 'radio.limits_eirp' : 'radio.limits';
    return t(key, { duty: pct(ch.duty_pct), mw });
}

/** A region's name in the console's language ("eu868", "as923-tw"), else the API's. */
export function regionName(code, region) {
    const key = `radio.region_names.${code}`;
    const name = t(key);
    return name !== key ? name : (region && region.name) || code;
}

/** Whether the field is in Taiwan's region: some explanations differ (EU868 is the default). */
function taiwan(radio) {
    return !!radio.region && radio.region.code === 'as923-tw';
}

function bandRange(ch) {
    return t('radio.band_range', { lo: mhz(ch.band_lo_hz), hi: mhz(ch.band_hi_hz), erc: ch.erc_band });
}

function notes(ch) {
    return (ch.notes || []).map((n) => t(`radio.notes.${n}`)).join(' · ');
}

export class FirstSetupNotice extends Component {
    render(props) {
        const app = props.app;
        const { status, role } = app.state;
        if (role !== 'gm' || !status || status.channel_confirmed !== false || !app.serves('radio')) return null;
        return html`<div class="notice" data-testid="radio-first-setup">
            <p>${t('radio.first_setup', { channel: mhz(status.field_channel_hz) })}</p>
            <button type="button" data-testid="radio-first-setup-go"
                onClick=${() => app.setState({ tab: 'settings' })}>${t('radio.choose')}</button>
        </div>`;
    }
}

export class RadioSettings extends Component {
    constructor() {
        super();
        this.state = { manual: '', random: null, region: '' };
    }

    async changeRegion(code) {
        const app = this.props.app;
        const name = regionName(code, (app.state.radio.regions || []).find((r) => r.code === code));
        if (!window.confirm(t('radio.region_confirm', { region: name }))) return;
        const out = await app.call('PUT', '/radio/region', { region: code });
        if (out) {
            app.setState({ radio: out });
            this.setState({ manual: '', random: null, region: '' });
            app.refreshStatus();
        }
    }

    renderRegion(radio, gm, disabled) {
        const region = radio.region;
        if (!region) return null; // a controller from before regions: EU868
        const value = this.state.region || region.code;
        return html`<section aria-labelledby="radio-region-h" data-testid="radio-region-section">
            <h3 id="radio-region-h">${t('radio.region_title')}</h3>
            <dl class="facts">
                <dt>${t('radio.region')}</dt>
                <dd><strong data-testid="radio-region">${regionName(region.code, region)}</strong></dd>
                <dt>${t('radio.region_band')}</dt>
                <dd data-testid="radio-region-lora">${t('radio.region_lora', { lo: mhz(region.lo_hz), hi: mhz(region.hi_hz),
                                                                              sf: region.sf, bw: region.bw_khz })}</dd>
                <dt>${t('radio.source')}</dt>
                <dd data-testid="radio-region-source">${t(`radio.region_sources.${radio.region_source || 'config'}`)}</dd>
            </dl>
            ${radio.region_mismatch && html`<p class="warning" data-testid="radio-region-mismatch">${t('radio.region_mismatch', {
                modem: regionName(radio.modem_region), field: regionName(region.code, region) })}</p>`}
            ${gm && (radio.regions || []).length > 1 && html`<div class="form inline">
                <label for="radio-region-select">${t('radio.region')}</label>
                <select id="radio-region-select" data-testid="radio-region-select" value=${value} disabled=${disabled}
                    onChange=${(e) => this.setState({ region: e.target.value })}>
                    ${radio.regions.map((r) => html`<option value=${r.code}>${regionName(r.code, r)}</option>`)}
                </select>
                <button type="button" data-testid="radio-region-apply" disabled=${disabled || value === region.code}
                    onClick=${() => this.changeRegion(value)}>${t('radio.region_apply')}</button>
            </div>
            <p class="muted small">${t('radio.region_hint')}</p>`}
        </section>`;
    }

    componentDidMount() {
        this.props.app.loadRadio();
    }

    async apply(hz, source) {
        const app = this.props.app;
        const out = await app.call('PUT', '/radio/channel', { channel_hz: hz, source });
        if (out) {
            app.setState({ radio: out });
            this.setState({ random: null });
            app.refreshStatus();
        }
    }

    async scan() {
        const app = this.props.app;
        const out = await app.call('POST', '/radio/scan', {});
        if (out) app.setState((s) => ({ radio: s.radio ? { ...s.radio, scan: out } : s.radio }));
    }

    async random() {
        const out = await this.props.app.call('POST', '/radio/random');
        if (out) this.setState({ random: out.suggestion });
    }

    /** The field's change of channel, told to the free boxes on the old channel first (RFC 0001
     * Amendment 19, decision RB-13): while the MOVEs are said, then that the controller has moved. */
    renderMove(radio) {
        const mv = radio.move;
        if (!mv || mv.to_hz !== radio.channel.channel_hz) return null;
        if (mv.state === 'telling') {
            return html`<p class="notice" role="status" data-testid="radio-move-telling">${t('radio.move_telling',
                { from: mhz(mv.from_hz), to: mhz(mv.to_hz), sent: mv.sent, repeats: mv.repeats })}</p>`;
        }
        if (this.state.moveSeen === mv.rev) return null;
        return html`<div class="notice" role="status" data-testid="radio-move-moved">
            <p>${t('radio.move_moved', { to: mhz(mv.to_hz) })}</p>
            <p class="small">${t('invites.missing_help')}</p>
            <button type="button" class="link" data-testid="radio-move-dismiss"
                onClick=${() => this.setState({ moveSeen: mv.rev })}>${t('radio.move_dismiss')}</button>
        </div>`;
    }

    renderCurrent(radio) {
        const ch = radio.channel;
        return html`<dl class="facts" data-testid="radio-current">
            <dt>${t('radio.channel')}</dt>
            <dd><strong data-testid="radio-channel">${mhz(ch.channel_hz)} MHz</strong>${ch.channel_hz === radio.recommended_hz
                ? html` <span class="pill">${t('radio.recommended')}</span>` : null}</dd>
            <dt>${t('radio.band')}</dt><dd>${bandRange(ch)}</dd>
            <dt>${t('radio.allowed')}</dt><dd data-testid="radio-limits">${limits(ch)}</dd>
            <dt>${t('radio.source')}</dt>
            <dd data-testid="radio-source">${radio.confirmed ? t(`radio.sources.${radio.source}`) : t('radio.not_chosen')}</dd>
        </dl>
        ${!ch.full_power && html`<p class="warning" data-testid="radio-low-power">${t('radio.low_power_warning')}</p>`}`;
    }

    renderScan(radio, disabled) {
        const scan = radio.scan;
        const unavailable = radio.scan_unavailable;
        const running = scan && scan.state === 'running';
        return html`<section aria-labelledby="radio-scan-h" data-testid="radio-scan-section">
            <h3 id="radio-scan-h">${t('radio.scan_title')}</h3>
            <p class="muted small">${t('radio.scan_hint', { seconds: Math.round(radio.scan_dwell_s) })}</p>
            ${unavailable && html`<p class="warning" data-testid="radio-scan-unavailable">${t(`radio.unavailable.${unavailable}`)}</p>`}
            <div class="actions">
                ${!running && html`<button type="button" data-testid="radio-scan" disabled=${disabled || !!unavailable}
                    onClick=${() => this.scan()}>${t('radio.scan')}</button>`}
                ${running && html`<button type="button" data-testid="radio-scan-cancel"
                    onClick=${() => this.props.app.call('DELETE', '/radio/scan')}>${t('radio.scan_cancel')}</button>`}
            </div>
            ${running && html`<p role="status" data-testid="radio-scan-progress">
                <progress max=${scan.channels} value=${scan.measured}></progress>
                ${' '}${t('radio.scan_progress', { n: scan.measured, total: scan.channels,
                                                  channel: scan.current_hz ? mhz(scan.current_hz) : '–' })}</p>`}
            ${scan && scan.state === 'failed' && html`<p class="error" data-testid="radio-scan-failed">${t('radio.scan_failed', { error: scan.error || '' })}</p>`}
            ${scan && scan.state === 'cancelled' && html`<p class="muted">${t('radio.scan_cancelled')}</p>`}
            ${scan && scan.suggestion && this.renderSuggestion(scan, disabled)}
            ${scan && scan.results && scan.results.length > 0 && this.renderResults(scan, disabled)}
        </section>`;
    }

    renderSuggestion(scan, disabled) {
        const s = scan.suggestion;
        const row = scan.results.find((r) => r.channel_hz === s.channel_hz);
        return html`<div class="notice" data-testid="radio-suggestion">
            <p>${t(`radio.suggest.${s.reason}`, { channel: mhz(s.channel_hz), limits: row ? limits(row) : '' })}</p>
            <button type="button" class="primary" data-testid="radio-accept-suggestion" disabled=${disabled}
                onClick=${() => this.apply(s.channel_hz, 'scan')}>${t('radio.use', { channel: mhz(s.channel_hz) })}</button>
        </div>`;
    }

    renderResults(scan, disabled) {
        const gm = this.props.app.state.role === 'gm';
        const suggested = scan.suggestion ? scan.suggestion.channel_hz : null;
        return html`<div class="table-wrap"><table class="table" data-testid="radio-results">
            <caption class="muted small">${t('radio.results_caption', { threshold: scan.threshold_dbm })}</caption>
            <thead><tr>
                <th>${t('radio.channel')}</th><th>${t('radio.allowed')}</th><th>${t('radio.p90')}</th>
                <th>${t('radio.mean')}</th><th>${t('radio.activity')}</th><th>${t('radio.quiet')}</th>
                ${gm && html`<th><span class="sr-only">${t('radio.use_short')}</span></th>`}
            </tr></thead>
            <tbody>${scan.results.map((r) => html`<tr data-channel=${r.channel_hz}
                    class=${r.channel_hz === suggested ? 'suggested' : ''}>
                <td>${mhz(r.channel_hz)} MHz${r.channel_hz === suggested ? html` <span class="pill">${t('radio.suggested')}</span>` : null}</td>
                <td>${limits(r)}</td>
                <td>${r.p90_dbm} dBm</td>
                <td>${r.mean_dbm} dBm</td>
                <td>${pct(r.activity_pct)}%</td>
                <td>${r.quiet ? t('common.yes') : t('common.no')}</td>
                ${gm && html`<td><button type="button" class="link" disabled=${disabled}
                    onClick=${() => this.apply(r.channel_hz, 'scan')}>${t('radio.use_short')}</button></td>`}
            </tr>`)}</tbody>
        </table></div>`;
    }

    renderRandom(radio, disabled) {
        const r = this.state.random;
        return html`<section aria-labelledby="radio-random-h">
            <h3 id="radio-random-h">${t('radio.random_title')}</h3>
            <p class="muted small">${t(taiwan(radio) ? 'radio.random_hint_tw' : 'radio.random_hint')}</p>
            <div class="actions">
                <button type="button" data-testid="radio-random" disabled=${disabled}
                    onClick=${() => this.random()}>${t('radio.random')}</button>
            </div>
            ${r && html`<div class=${r.full_power ? 'notice' : 'warning'} data-testid="radio-random-result">
                <p>${t('radio.random_got', { channel: mhz(r.channel_hz), limits: limits(r) })}</p>
                <p class="small">${t('radio.random_odds', { full: r.pool_full_power, pool: r.pool })}</p>
                <button type="button" data-testid="radio-accept-random" disabled=${disabled}
                    onClick=${() => this.apply(r.channel_hz, 'random')}>${t('radio.use', { channel: mhz(r.channel_hz) })}</button>
            </div>`}
        </section>`;
    }

    renderManual(radio, disabled) {
        const groups = [];
        for (const c of radio.candidates) {
            let g = groups.find((x) => x.band === c.band);
            if (!g) {
                g = { band: c.band, label: `${bandRange(c)} · ${limits(c)}`, items: [] };
                groups.push(g);
            }
            g.items.push(c);
        }
        const value = this.state.manual || String(radio.channel.channel_hz);
        const picked = radio.candidates.find((c) => String(c.channel_hz) === value);
        return html`<section aria-labelledby="radio-manual-h">
            <h3 id="radio-manual-h">${t('radio.manual_title')}</h3>
            <div class="form inline">
                <label for="radio-manual">${t('radio.channel')}</label>
                <select id="radio-manual" data-testid="radio-manual" value=${value} disabled=${disabled}
                    onChange=${(e) => this.setState({ manual: e.target.value })}>
                    ${groups.map((g) => html`<optgroup label=${g.label}>
                        ${g.items.map((c) => html`<option value=${String(c.channel_hz)}>${mhz(c.channel_hz)} MHz${
                            c.notes.length ? ` (${notes(c)})` : ''}</option>`)}
                    </optgroup>`)}
                </select>
                <button type="button" data-testid="radio-apply-manual" disabled=${disabled || !picked}
                    onClick=${() => this.apply(Number(value), Number(value) === radio.recommended_hz ? 'default' : 'manual')}>${t('radio.apply')}</button>
            </div>
            ${picked && !picked.usable && html`<p class="warning">${t('radio.low_airtime_warning')}</p>`}
        </section>`;
    }

    render(props) {
        const app = props.app;
        const { radio, role, game } = app.state;
        if (!radio) return html`<section class="card"><p class="muted">…</p></section>`;
        const gm = role === 'gm';
        const scanning = radio.scan && radio.scan.state === 'running';
        const live = game && game.live && game.state !== 'ended';
        const disabled = !!radio.locked;
        return html`<section class="card" aria-labelledby="radio-h" data-testid="radio-settings">
            <h2 id="radio-h">${t('radio.title')}</h2>
            ${this.renderCurrent(radio)}
            ${this.renderMove(radio)}
            ${gm && !live && app.serves('boxes') && html`<div class="actions" data-testid="radio-find-boxes-row">
                <button type="button" data-testid="radio-find-boxes" title=${t('radio.find_boxes_hint')}
                    onClick=${() => app.loadBoxes(true)}>${t('invites.discover')}</button></div>
                <${DiscoverResult} app=${app} />`}
            <details class="why" data-testid="radio-why">
                <summary>${t('radio.why_title', { channel: mhz(radio.recommended_hz) })}</summary>
                ${taiwan(radio) ? html`<p>${t('radio.why_tw_1')}</p><p>${t('radio.why_tw_2')}</p><p>${t('radio.why_tw_3')}</p>`
                    : html`<p>${t('radio.why_1')}</p><p>${t('radio.why_2')}</p><p>${t('radio.why_3')}</p>`}
            </details>
            ${this.renderRegion(radio, gm, disabled)}
            ${radio.locked && html`<p class="notice" data-testid="radio-locked">${live ? t('radio.locked_game')
                : scanning ? t('radio.locked_scan') : radio.locked}</p>`}
            ${gm ? html`
                <section aria-labelledby="radio-default-h">
                    <h3 id="radio-default-h">${t('radio.default_title')}</h3>
                    <p class="muted small">${t(taiwan(radio) ? 'radio.default_hint_tw' : 'radio.default_hint',
                                               { channel: mhz(radio.recommended_hz) })}</p>
                    <div class="actions"><button type="button" class="primary" data-testid="radio-keep-default"
                        disabled=${disabled} onClick=${() => this.apply(radio.recommended_hz, 'default')}>${
                        t('radio.keep_default', { channel: mhz(radio.recommended_hz) })}</button></div>
                </section>
                ${this.renderScan(radio, disabled)}
                ${this.renderRandom(radio, disabled)}
                ${this.renderManual(radio, disabled)}`
            : html`<p class="muted">${t('radio.read_only')}</p>`}
        </section>`;
    }
}
