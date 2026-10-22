// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Firmware updates for the Field Boxes (protocol/firmware-update.md, decisions
// FU3-*), for the GM, under the Boxes tab: upload a signed release (the image
// and its .release.json from tools/firmware_release.py; the controller keeps
// it only if one of its release keys signed it), then update one box or all of
// them while the live game has not started. Each box checks the release again
// with the keys in its own firmware, installs it over the field Wi-Fi and
// reports; its next HELLO shows the version it runs.

import { html, Component, t } from '../ui.js';

const ACTIVE = ['sent', 'installed'];

/** -1, 0 or 1, as Semantic Versioning orders a and b (firmware_release.py's version_key). */
export function compareVersions(a, b) {
    const split = (v) => {
        const m = /^(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-([0-9A-Za-z][0-9A-Za-z.]{0,19}))?$/.exec(v || '');
        return m ? [[+m[1], +m[2], +m[3]], m[4] ? m[4].split('.') : null] : null;
    };
    const x = split(a);
    const y = split(b);
    if (!x || !y) return null;
    for (let i = 0; i < 3; i++) if (x[0][i] !== y[0][i]) return x[0][i] < y[0][i] ? -1 : 1;
    if (!x[1] || !y[1]) return x[1] === y[1] ? 0 : (x[1] ? -1 : 1);
    for (let i = 0; i < Math.min(x[1].length, y[1].length); i++) {
        const p = x[1][i];
        const q = y[1][i];
        const pn = /^\d+$/.test(p);
        const qn = /^\d+$/.test(q);
        if (pn && qn && BigInt(p) !== BigInt(q)) return BigInt(p) < BigInt(q) ? -1 : 1;
        if (pn !== qn) return pn ? -1 : 1;
        if (!pn && p !== q) return p < q ? -1 : 1;
    }
    return Math.sign(x[1].length - y[1].length);
}

export class FirmwarePanel extends Component {
    constructor() {
        super();
        this.state = { fw: null, busy: false, results: null };
        this.image = null;
        this.release = null;
    }

    componentDidMount() {
        this.load();
    }

    async load() {
        const fw = await this.props.app.call('GET', '/firmware');
        if (fw) this.setState({ fw });
    }

    async upload(e) {
        e.preventDefault();
        const app = this.props.app;
        const image = this.image && this.image.files[0];
        const releaseFile = this.release && this.release.files[0];
        if (!image || !releaseFile) {
            app.showToast(t('firmware.choose_both'));
            return;
        }
        let rel;
        try {
            rel = JSON.parse(await releaseFile.text());
        } catch (err) {
            app.showToast(t('firmware.bad_release_file'));
            return;
        }
        const query = new URLSearchParams({ platform: rel.platform || '', version: rel.version || '',
                                            signature: rel.signature || '' });
        this.setState({ busy: true });
        const out = await app.call('POST', `/firmware?${query}`, undefined,
                                   { type: 'application/octet-stream', data: image });
        this.setState({ busy: false });
        if (out) {
            this.image.value = '';
            this.release.value = '';
            this.load();
        }
    }

    async install(release, nodes) {
        const out = await this.props.app.call('POST', `/firmware/${release.id}/install`, { nodes });
        if (out) this.setState({ results: out.results });
        this.load();
    }

    async remove(release) {
        if (await this.props.app.call('DELETE', `/firmware/${release.id}`)) this.load();
    }

    async cancel() {
        if (await this.props.app.call('DELETE', '/firmware/updates')) this.load();
    }

    renderReleases(fw, canUpdate) {
        if (fw.releases.length === 0) return html`<p class="muted">${t('firmware.no_releases')}</p>`;
        return html`<div class="table-wrap"><table class="table" data-testid="firmware-releases">
            <thead><tr>
                <th>${t('firmware.version')}</th><th>${t('firmware.board')}</th><th>${t('firmware.size')}</th>
                <th>${t('firmware.key')}</th><th><span class="sr-only">${t('firmware.actions')}</span></th>
            </tr></thead>
            <tbody>${fw.releases.map((r) => html`<tr data-release=${r.id}>
                <td><strong>${r.version}</strong> <span class="muted small">${r.platform}</span></td>
                <td>${r.board}</td>
                <td>${Math.round(r.size / 1024)} KiB</td>
                <td>${r.verified ? html`<code>${r.key_id}</code>`
                    : html`<strong class="warn">${t('firmware.not_verified')}</strong>`}</td>
                <td>
                    <button type="button" class="small" data-testid=${`firmware-all-${r.id}`}
                        disabled=${!canUpdate || !r.verified} onClick=${() => this.install(r, 'all')}>
                        ${t('firmware.update_all')}</button>
                    <button type="button" class="small link" data-testid=${`firmware-delete-${r.id}`}
                        onClick=${() => this.remove(r)}>${t('firmware.delete')}</button>
                </td>
            </tr>`)}</tbody>
        </table></div>`;
    }

    renderBoxes(fw, canUpdate) {
        const app = this.props.app;
        const updates = app.state.firmwareUpdates || fw.updates;
        const byNode = Object.fromEntries(updates.map((u) => [u.node_id, u]));
        const boxes = Object.values(app.state.nodes).filter((n) => n.fw_version)
            .sort((a, b) => a.node_id - b.node_id);
        if (boxes.length === 0) return null;
        const verified = fw.releases.filter((r) => r.verified);
        return html`<div class="table-wrap"><table class="table" data-testid="firmware-boxes">
            <thead><tr>
                <th>${t('nodes.id')}</th><th>${t('nodes.name')}</th><th>${t('firmware.installed_version')}</th>
                <th>${t('firmware.update')}</th>
            </tr></thead>
            <tbody>${boxes.map((n) => {
                const u = byNode[n.node_id];
                // The newest release for this box's platform that is above what it runs.
                const offer = verified.filter((r) => String(n.platform) === (r.platform === 'esp32s3' ? '1' : '0')
                    && compareVersions(r.version, n.fw_version) === 1)
                    .sort((a, b) => compareVersions(b.version, a.version))[0];
                const active = u && ACTIVE.includes(u.state);
                // Sent and not heard of yet: the GM may send it again at once (decision OT-9).
                const again = u && u.state === 'sent' && verified.find((r) => r.id === u.release);
                return html`<tr data-node=${n.node_id}>
                    <td>${n.node_id}</td><td>${n.name}</td><td>${n.fw_version}</td>
                    <td data-testid=${`firmware-state-${n.node_id}`}>
                        ${u && html`<span class=${u.state === 'done' ? 'ok' : (active ? '' : 'warn')}>
                            ${t(`firmware.states.${u.state}`, { version: u.version })}${u.reason
                                ? ` (${t(`firmware.reasons.${u.reason}`) || u.reason})` : ''}</span> `}
                        ${offer && !active && html`<button type="button" class="small"
                            data-testid=${`firmware-update-${n.node_id}`} disabled=${!canUpdate}
                            onClick=${() => this.install(offer, [n.node_id])}>
                            ${t('firmware.update_to', { version: offer.version })}</button>`}
                        ${again && html`<button type="button" class="small link"
                            data-testid=${`firmware-again-${n.node_id}`} disabled=${!canUpdate}
                            title=${t('firmware.send_again_hint')}
                            onClick=${() => this.install(again, [n.node_id])}>${t('firmware.send_again')}</button>`}
                    </td>
                </tr>`;
            })}</tbody>
        </table></div>`;
    }

    render(props, state) {
        const app = props.app;
        if (app.state.role !== 'gm') return null;
        const fw = state.fw;
        if (!fw) return null;
        const game = app.state.game;
        const ready = Boolean(game && game.live && game.state === 'ready');
        const canUpdate = ready && fw.https && fw.keys.length > 0;
        const updates = app.state.firmwareUpdates || fw.updates;
        const active = updates.some((u) => ACTIVE.includes(u.state));
        return html`<section class="card" aria-labelledby="firmware-h" data-testid="firmware-panel">
            <h2 id="firmware-h">${t('firmware.title')}</h2>
            <p class="muted small">${t('firmware.hint')}</p>
            ${fw.keys.length === 0 && html`<p class="warning" data-testid="firmware-no-keys">${t('firmware.no_keys')}</p>`}
            ${!fw.https && html`<p class="warning" data-testid="firmware-no-https">${t('firmware.no_https')}</p>`}
            ${!ready && html`<p class="notice" data-testid="firmware-not-ready">${t('firmware.not_ready')}</p>`}
            <form class="actions" onSubmit=${(e) => this.upload(e)}>
                <label>${t('firmware.image')}
                    <input type="file" accept=".bin,application/octet-stream" data-testid="firmware-image"
                        ref=${(el) => { this.image = el; }} /></label>
                <label>${t('firmware.release_file')}
                    <input type="file" accept=".json,application/json" data-testid="firmware-release"
                        ref=${(el) => { this.release = el; }} /></label>
                <button type="submit" data-testid="firmware-upload" disabled=${state.busy || fw.keys.length === 0}>
                    ${t('firmware.upload')}</button>
            </form>
            ${this.renderReleases(fw, canUpdate)}
            ${this.renderBoxes(fw, canUpdate)}
            ${state.results && html`<ul class="small" data-testid="firmware-results">${state.results.map((r) =>
                html`<li>${t('nodes.node')} ${r.node_id}: ${t(`firmware.results.${r.result}`)}</li>`)}</ul>`}
            ${active && html`<p><button type="button" class="link" data-testid="firmware-cancel"
                onClick=${() => this.cancel()}>${t('firmware.cancel')}</button></p>`}
        </section>`;
    }
}
