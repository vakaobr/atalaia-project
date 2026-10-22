// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Signed mode packages (protocol/mode-packages.md, phase 5 plan phase 6), for
// the GM, under the Presets tab: upload a signed package (the archive and its
// .release.json from tools/mode_package.py) or install one from the field's
// registry index ([modes] index). The controller installs a package only if one
// of its own mode keys ([modes] keys) signed it and that key is not revoked.
// Each installed package shows who signed it and whether the project reviewed
// it: an upload, or an index entry not marked verified, is "not reviewed by
// the project".

import { html, Component, t } from '../ui.js';

const STATE_CLASS = { available: '', installed: 'ok', no_key: 'warn', revoked: 'warn', builtin: 'muted' };

export class ModePackages extends Component {
    constructor() {
        super();
        this.state = { status: null, busy: false };
        this.archive = null;
        this.release = null;
    }

    componentDidMount() {
        if (this.props.app.state.role === 'gm') this.load(false); // the GM's only
    }

    async load(refresh) {
        const status = await this.props.app.call('GET', `/mode-packages${refresh ? '?refresh=1' : ''}`);
        if (status) this.setState({ status });
    }

    async upload(e) {
        e.preventDefault();
        const app = this.props.app;
        const archive = this.archive && this.archive.files[0];
        const releaseFile = this.release && this.release.files[0];
        if (!archive || !releaseFile) {
            app.showToast(t('packages.choose_both'));
            return;
        }
        let rel;
        try {
            rel = JSON.parse(await releaseFile.text());
        } catch (err) {
            app.showToast(t('packages.bad_release_file'));
            return;
        }
        const fields = ['id', 'version', 'kind', 'min_tier', 'signature', 'key_id'];
        const query = new URLSearchParams(Object.fromEntries(fields.map((k) => [k, String(rel[k] || '')])));
        this.setState({ busy: true });
        const out = await app.call('POST', `/mode-packages?${query}`, undefined,
                                   { type: 'application/octet-stream', data: archive });
        this.setState({ busy: false });
        if (out) {
            this.archive.value = '';
            this.release.value = '';
            app.showToast(t('packages.installed_toast', { id: out.id, version: out.version }));
            this.load(false);
        }
    }

    async install(entry) {
        this.setState({ busy: true });
        const out = await this.props.app.call('POST', '/mode-packages/install', { id: entry.id, version: entry.version });
        this.setState({ busy: false });
        if (out) this.props.app.showToast(t('packages.installed_toast', { id: out.id, version: out.version }));
        this.load(false);
    }

    renderSigned(m) {
        if (!m.signed) return html`<span class="muted">${t('packages.unsigned')}</span>`;
        const s = m.signed;
        return html`<span>${t('packages.signed_by')} <code>${s.key_id}</code></span>
            ${s.verified ? html` <span class="ok">${t('packages.verified')}</span>`
                : html` <strong class="warn">${t('packages.not_reviewed')}</strong>`}
            ${s.trust !== 'trusted' && html` <strong class="warn">${t(`packages.trust.${s.trust}`)}</strong>`}`;
    }

    renderInstalled(modes) {
        const uploaded = modes.filter((m) => !m.builtin);
        if (uploaded.length === 0) return html`<p class="muted">${t('packages.none_installed')}</p>`;
        return html`<div class="table-wrap"><table class="table" data-testid="packages-installed">
            <thead><tr><th>${t('packages.mode')}</th><th>${t('packages.version')}</th>
                <th>${t('packages.signature')}</th></tr></thead>
            <tbody>${uploaded.map((m) => html`<tr data-mode=${m.id}>
                <td><strong>${m.name}</strong> <span class="muted small">${m.id}</span></td>
                <td>${m.version}</td>
                <td data-testid=${`packages-signed-${m.id}`}>${this.renderSigned(m)}</td>
            </tr>`)}</tbody>
        </table></div>`;
    }

    renderIndex(index, busy) {
        if (!index.source) return html`<p class="muted small">${t('packages.no_index')}</p>`;
        return html`<div data-testid="packages-index">
            <p class="small"><span class="muted">${t('packages.index')}:</span> <code>${index.source}</code>
                <button type="button" class="small link" data-testid="packages-refresh"
                    onClick=${() => this.load(true)}>${t('packages.refresh')}</button></p>
            ${index.error && html`<p class="warning" data-testid="packages-index-error">
                ${t('packages.index_error', { error: index.error })}</p>`}
            ${!index.error && index.entries.length === 0 && html`<p class="muted">${t('packages.index_empty')}</p>`}
            ${index.entries.length > 0 && html`<div class="table-wrap"><table class="table">
                <thead><tr><th>${t('packages.mode')}</th><th>${t('packages.version')}</th>
                    <th>${t('packages.licence')}</th><th>${t('packages.signature')}</th>
                    <th><span class="sr-only">${t('packages.actions')}</span></th></tr></thead>
                <tbody>${index.entries.map((e) => html`<tr data-entry=${`${e.id}@${e.version}`}>
                    <td><strong>${e.name}</strong> <span class="muted small">${e.id}</span>
                        ${e.author && html`<br /><span class="muted small">${e.author}</span>`}</td>
                    <td>${e.version} <span class="muted small">${t(`packages.kinds.${e.kind}`)}</span></td>
                    <td>${e.license}</td>
                    <td><code>${e.key_id}</code> ${e.verified ? html`<span class="ok">${t('packages.verified')}</span>`
                        : html`<strong class="warn">${t('packages.not_reviewed')}</strong>`}</td>
                    <td data-testid=${`packages-entry-${e.id}`}>
                        ${e.state === 'available' ? html`<button type="button" class="small" disabled=${busy}
                            data-testid=${`packages-install-${e.id}`} onClick=${() => this.install(e)}>
                            ${e.installed_version ? t('packages.update_to', { version: e.version }) : t('packages.install')}
                        </button>` : html`<span class=${STATE_CLASS[e.state] || ''}>${t(`packages.states.${e.state}`)}</span>`}
                    </td>
                </tr>`)}</tbody>
            </table></div>`}
        </div>`;
    }

    render(props, state) {
        const app = props.app;
        if (app.state.role !== 'gm') return null;
        const status = state.status;
        if (!status) return null;
        const noKeys = status.keys.length === 0;
        return html`<section class="card" aria-labelledby="packages-h" data-testid="mode-packages">
            <h2 id="packages-h">${t('packages.title')}</h2>
            <p class="muted small">${t('packages.hint')}</p>
            ${noKeys ? html`<p class="warning" data-testid="packages-no-keys">${t('packages.no_keys')}</p>`
                : html`<p class="small muted" data-testid="packages-keys">${t('packages.keys')}
                    ${status.keys.map((k) => html` <code>${k}</code>`)}</p>`}
            <form class="actions" onSubmit=${(e) => this.upload(e)}>
                <label>${t('packages.archive')}
                    <input type="file" accept=".tar,application/x-tar" data-testid="packages-archive"
                        ref=${(el) => { this.archive = el; }} /></label>
                <label>${t('packages.release_file')}
                    <input type="file" accept=".json,application/json" data-testid="packages-release"
                        ref=${(el) => { this.release = el; }} /></label>
                <button type="submit" data-testid="packages-upload" disabled=${state.busy || noKeys}>
                    ${t('packages.upload')}</button>
            </form>
            <h3>${t('packages.installed')}</h3>
            ${this.renderInstalled(app.state.modes || [])}
            <h3>${t('packages.from_index')}</h3>
            ${this.renderIndex(status.index, state.busy || noKeys)}
        </section>`;
    }
}
