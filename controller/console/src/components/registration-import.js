// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Importing a registration list into the check-in list (PKE-1; decision F23): for a field with no site server,
// the GM picks a CSV (or JSON) file from the other platform, checks it (a dry run: nothing is changed, every
// row is listed as new, changed, unchanged, skipped or refused with the reason), then imports it. The file's
// format is the site server's (controller/atalaia_controller/import_format.py): only display_name,
// external_ref, team_preference, federation_number and replicas are read; any other column (an email, a phone
// number) is only named. Imported players are "expected" until a marshal ticks them by name; rows with the
// same source and reference update each other, so the same export can be imported again.

import { html, Component, t, api, ApiError } from '../ui.js';

const MAX_BYTES = 1024 * 1024;

/** The text of a code the controller answers with (a file or a row refused, a skipped row, a warning). */
export function importCodeText(code, line) {
    const key = `checkin_import.codes.${code}`;
    const text = t(key);
    const base = text === key ? code : text;
    return line ? `${base} (${t('checkin_import.line', { n: line })})` : base;
}

export class RegistrationImport extends Component {
    constructor() {
        super();
        this.state = { file: null, text: null, source: 'csv', basis: false, result: null, error: '', busy: false };
    }

    async pick(e) {
        const file = e.target.files && e.target.files[0];
        this.setState({ file: file ? file.name : null, text: null, result: null, error: '' });
        if (!file) return;
        if (file.size > MAX_BYTES) {
            this.setState({ error: importCodeText('too_large') });
            return;
        }
        try {
            // Strictly UTF-8, as the controller reads it: a file in another encoding is refused, not mangled.
            const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: false }).decode(await file.arrayBuffer());
            this.setState({ text, format: /\.json$/i.test(file.name) ? 'json' : 'csv' });
        } catch (err) {
            this.setState({ error: importCodeText('encoding_invalid') });
        }
    }

    async run(dryRun) {
        const app = this.props.app;
        const s = this.state;
        this.setState({ busy: true, error: '' });
        try {
            const result = await api(app.token, 'POST', `/games/${this.props.game.id}/checkins/import`, {
                format: s.format, data: s.text, source: s.source.trim(), dry_run: dryRun, basis_confirmed: s.basis });
            this.setState({ result, busy: false });
            if (!dryRun) {
                const c = result.counts;
                app.showToast(t('checkin_import.done', { created: c.created, updated: c.updated }));
                if (this.props.onDone) this.props.onDone();
            }
        } catch (err) {
            if (err instanceof ApiError && err.status === 401) {
                app.logout(t('login.expired'));
                return;
            }
            const line = err instanceof ApiError && err.body ? err.body.line : null;
            this.setState({ busy: false, result: null, error: err instanceof ApiError ? importCodeText(err.message, line) : err.message });
        }
    }

    renderResult(r) {
        const c = r.counts;
        const shown = r.results.filter((x) => x.result !== 'unchanged').slice(0, 200);
        return html`<div data-testid="import-result" role="status">
            <p><strong>${r.dry_run ? t('checkin_import.checked') : t('checkin_import.imported')}</strong>
                ${' '}${t('checkin_import.counts', { rows: r.rows, created: c.created, updated: c.updated,
        unchanged: c.unchanged, skipped: c.skipped, refused: c.refused })}</p>
            ${r.not_imported_columns.length > 0 && html`<p class="small muted" data-testid="import-ignored">${
                t('checkin_import.ignored', { names: r.not_imported_columns.join(', ') })}${
                r.not_imported_more ? ` ${t('checkin_import.more', { n: r.not_imported_more })}` : ''}</p>`}
            ${r.missing.count > 0 && html`<p class="small muted" data-testid="import-missing">${
                t('checkin_import.missing', { n: r.missing.count })}</p>`}
            ${shown.length > 0 && html`<div class="table-wrap"><table class="table" data-testid="import-rows">
                <thead><tr><th>${t('checkin_import.row')}</th><th>${t('checkin.name')}</th><th>${t('checkin_import.result')}</th></tr></thead>
                <tbody>${shown.map((x) => html`<tr data-testid=${`import-row-${x.row}`}>
                    <td>${x.row}</td><td>${x.display_name || '–'}</td>
                    <td><span class=${`badge ${x.result === 'refused' ? 'danger' : ''}`}>${t(`checkin_import.results.${x.result}`)}</span>
                        ${x.code ? ` ${importCodeText(x.code)}` : ''}${x.changed ? ` ${x.changed.join(', ')}` : ''}${
                (x.warnings || []).map((w) => html` <span class="small muted">${importCodeText(w)}</span>`)}</td></tr>`)}</tbody>
            </table></div>`}
        </div>`;
    }

    render(props, state) {
        const ready = state.text !== null && state.text !== undefined;
        return html`<details class="card-section" data-testid="import-section">
            <summary data-testid="import-open">${t('checkin_import.title')}</summary>
            <form class="form inline" data-testid="import-form" onSubmit=${(e) => { e.preventDefault(); this.run(true); }}>
                <p class="muted small">${t('checkin_import.intro')}</p>
                <div class="field"><label for="ci-file">${t('checkin_import.file')}</label>
                    <input id="ci-file" type="file" accept=".csv,.json,text/csv,application/json" data-testid="import-file"
                        onChange=${(e) => this.pick(e)} /></div>
                <div class="field"><label for="ci-source">${t('checkin_import.source')}</label>
                    <input id="ci-source" data-testid="import-source" required maxlength="32" pattern="[a-z0-9][a-z0-9._\\-]{0,31}"
                        value=${state.source} onInput=${(e) => this.setState({ source: e.target.value, result: null })} />
                    <span class="small muted">${t('checkin_import.source_hint')}</span></div>
                <label class="check"><input type="checkbox" data-testid="import-basis" checked=${state.basis}
                    onChange=${(e) => this.setState({ basis: e.target.checked })} /> ${t('checkin_import.basis')}</label>
                <div class="actions">
                    <button type="submit" data-testid="import-check" disabled=${!ready || state.busy}>${t('checkin_import.check')}</button>
                    <button type="button" class="primary" data-testid="import-run"
                        disabled=${!ready || state.busy || !state.basis || !state.result || !state.result.dry_run}
                        onClick=${() => this.run(false)}>${t('checkin_import.run')}</button>
                </div>
                <p class="small muted">${t('checkin_import.order')}</p>
                ${state.error && html`<p class="error" role="alert" data-testid="import-error">${state.error}</p>`}
                ${state.result && this.renderResult(state.result)}
            </form>
        </details>`;
    }
}
