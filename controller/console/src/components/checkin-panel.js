// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Field check-in (ADR-P3-13, protocol/checkin.md): the GM opens or closes
// check-in for the live game, sets the field's rules, prints the check-in
// poster, follows the check-ins as they arrive (names are shown here, to
// staff, and nowhere else), confirms them, ticks "card seen" for a
// federation number, gives teams, squads and roles, checks in a player
// without the app, and works through the "replicas to chrono" list that
// the marshals' signed readings fill in.

import { html, Component, t } from '../ui.js';

const STATUSES = ['pending', 'checked_in', 'left', 'removed'];
const ROLES = ['player', 'squad_leader', 'vip', 'marshal', 'gm', 'spectator'];

/** A game's squads are sub-groups inside each team, and only some games have them (decision PE25). */
function squadsOf(g) {
    return (g && g.squads) || 0;
}

/** "red › squad 2", or the team alone. */
function where(team, squad) {
    if (!team) return '–';
    return squad ? `${team} › ${t('checkin.squad_n', { n: squad })}` : team;
}
const TYPES = ['aeg', 'gbb', 'hpa', 'bolt_action', 'dmr', 'sniper', 'pistol', 'shotgun'];

function uuid4() {
    const b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function StateBadge({ state, refusedToday }) {
    return html`<span class=${`badge chrono-${state}`} data-testid="chrono-state">${t(`checkin.states.${state}`)}${
        refusedToday ? ` · ${t('checkin.refused_today')}` : ''}</span>`;
}

export class CheckinPanel extends Component {
    constructor() {
        super();
        this.state = { list: null, chrono: null, poster: null, classes: [], manual: null, busy: false };
    }

    componentDidMount() {
        this.load();
    }

    componentDidUpdate(prev) {
        const g = this.props.app.state.game;
        const before = prev.app.state.game;
        if ((g && g.id) !== (before && before.id)) this.load();
    }

    game() {
        const g = this.props.app.state.game;
        return g && g.live && g.state !== 'ended' ? g : null;
    }

    async load() {
        const app = this.props.app;
        if (app.state.role !== 'gm') return;
        const g = this.game();
        const [poster, info] = await Promise.all([app.call('GET', '/checkin/poster'), app.call('GET', '/checkin')]);
        this.setState({ poster, classes: info ? info.limits.classes : [] });
        if (!g) {
            this.setState({ list: null, chrono: null });
            return;
        }
        const [list, chrono] = await Promise.all([app.call('GET', `/games/${g.id}/checkins`),
            app.call('GET', `/games/${g.id}/chrono-list`)]);
        this.setState({ list, chrono });
        if (chrono) app.setState({ chronoCounts: chrono.counts });
    }

    /** A stream message: checkin, chrono_list, checkin_open or checkin_settings (app.js forwards them). */
    onStream(msg) {
        const g = this.game();
        if (!g || (msg.game !== undefined && msg.game !== g.id)) return;
        if (msg.type === 'checkin' && this.state.list) {
            if (msg.erased) {
                this.load();
                return;
            }
            const rows = this.state.list.checkins.filter((r) => r.player_id !== msg.checkin.player_id);
            rows.push(msg.checkin);
            rows.sort((a, b) => a.seq - b.seq);
            this.setState({ list: { ...this.state.list, checkins: rows, counts: counts(rows) } });
        } else if (msg.type === 'chrono_list') {
            this.reloadChrono();
        } else if (msg.type === 'checkin_open' && this.state.list) {
            this.setState({ list: { ...this.state.list, open: msg.open } });
        } else if (msg.type === 'checkin_settings' && this.state.list) {
            this.setState({ list: { ...this.state.list, settings: msg.settings } });
        }
    }

    async reloadChrono() {
        const g = this.game();
        if (!g) return;
        clearTimeout(this.chronoTimer);
        this.chronoTimer = setTimeout(async () => {
            const chrono = await this.props.app.call('GET', `/games/${g.id}/chrono-list`);
            if (chrono) {
                this.setState({ chrono });
                this.props.app.setState({ chronoCounts: chrono.counts });
            }
        }, 150);
    }

    componentWillUnmount() {
        clearTimeout(this.chronoTimer);
    }

    async setOpen(open) {
        const g = this.game();
        const r = await this.props.app.call('POST', `/games/${g.id}/checkin/${open ? 'open' : 'close'}`);
        if (r) this.setState({ list: { ...this.state.list, open: r.open } });
    }

    async patch(pid, body) {
        const g = this.game();
        const row = await this.props.app.call('PATCH', `/games/${g.id}/checkins/${pid}`, body);
        if (row) this.onStream({ type: 'checkin', game: g.id, checkin: row });
    }

    async remove(pid) {
        const g = this.game();
        await this.props.app.call('DELETE', `/games/${g.id}/checkins/${pid}`);
        this.load();
    }

    async saveSettings(e) {
        e.preventDefault();
        const f = e.target.elements;
        const body = {
            confirm: f.confirm.value, federation: f.federation.value, federation_label: f.federation_label.value.trim(),
            max_replicas: parseInt(f.max_replicas.value, 10), max_players: parseInt(f.max_players.value, 10),
            chrono_valid_for: f.chrono_valid_for.value,
        };
        const s = await this.props.app.call('PUT', '/checkin/settings', body);
        if (s && this.state.list) {
            this.setState({ list: { ...this.state.list, settings: s } });
            this.props.app.showToast(t('checkin.saved'));
        }
    }

    async savePoster(e) {
        e.preventDefault();
        const f = e.target.elements;
        const urls = f.urls.value.split(/\s+/).map((u) => u.trim()).filter(Boolean);
        const body = { wifi_ssid: f.wifi_ssid.value.trim(), urls,
            game_id: f.pinned.checked && this.game() ? this.game().id : null };
        const poster = await this.props.app.call('PUT', '/checkin/poster', body);
        if (poster) {
            this.setState({ poster });
            this.props.app.showToast(t('checkin.saved'));
        }
    }

    async exportCsv() {
        const g = this.game();
        const blob = await this.props.app.call('GET', `/games/${g.id}/checkins.csv`);
        if (!blob) return;
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `checkins-${g.id}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }

    async manualCheckin(e) {
        e.preventDefault();
        const g = this.game();
        const m = this.state.manual;
        const body = { display_name: m.name.trim(), replicas: m.replicas.map((r) => ({
            declaration_id: r.id, type: r.type, class: r.cls, ...(r.mm.trim() ? { make_model: r.mm.trim() } : {}),
        })) };
        if (m.fed.trim()) body.federation_number = m.fed.trim();
        if (m.team) body.team_preference = m.team;
        const row = await this.props.app.call('POST', `/games/${g.id}/checkins`, body);
        if (row) {
            this.setState({ manual: null });
            this.onStream({ type: 'checkin', game: g.id, checkin: row });
            this.props.app.showToast(t('checkin.manual_done', { id: row.player_id }));
        }
    }

    renderHead(g, list) {
        const c = list.counts;
        return html`<section class="card" aria-labelledby="ci-h">
            <h2 id="ci-h">${t('checkin.title')}</h2>
            <p class="muted">${t('checkin.intro')}</p>
            <p data-testid="checkin-open">${list.open ? t('checkin.open', { game: g.name }) : t('checkin.closed', { game: g.name })}</p>
            <div class="actions">
                ${list.open
        ? html`<button type="button" data-testid="checkin-close" onClick=${() => this.setOpen(false)}>${t('checkin.close')}</button>`
        : html`<button type="button" class="primary" data-testid="checkin-reopen" onClick=${() => this.setOpen(true)}>${t('checkin.reopen')}</button>`}
                <a class="button" href="poster.html" target="_blank" rel="noopener" data-testid="checkin-poster-link">${t('checkin.print_poster')}</a>
                <button type="button" data-testid="checkin-csv" onClick=${() => this.exportCsv()}>${t('checkin.csv')}</button>
            </div>
            <p class="small" data-testid="checkin-counts">${STATUSES.map((s) => `${t(`checkin.statuses.${s}`)}: ${c[s] || 0}`).join(' · ')}</p>
        </section>`;
    }

    renderList(g, list) {
        const s = list.settings;
        const rows = list.checkins;
        return html`<section class="card" aria-labelledby="cil-h">
            <h2 id="cil-h">${t('checkin.list')}</h2>
            ${rows.length === 0 && html`<p class="muted" data-testid="checkin-empty">${t('checkin.empty')}</p>`}
            ${rows.length > 0 && html`<div class="table-wrap"><table class="table" data-testid="checkin-table">
                <thead><tr><th>${t('checkin.name')}</th><th>${t('checkin.status')}</th>
                    <th>${squadsOf(g) ? t('checkin.team_squad') : t('checkin.team')}</th><th>${t('checkin.role')}</th>
                    ${s.federation !== 'off' && html`<th>${s.federation_label}</th>`}
                    <th>${t('checkin.replicas')}</th><th></th></tr></thead>
                <tbody>${rows.map((r) => this.renderRow(g, s, r))}</tbody>
            </table></div>`}
            ${this.renderManual(g, s)}
        </section>`;
    }

    renderRow(g, s, r) {
        const active = r.status === 'pending' || r.status === 'checked_in';
        const decls = (r.declarations || []).filter((d) => d.state !== 'withdrawn');
        const counts = {};
        for (const d of decls) counts[d.state] = (counts[d.state] || 0) + 1;
        return html`<tr data-testid=${`checkin-row-${r.player_id}`} class=${active ? '' : 'muted'}>
            <td><strong data-testid="checkin-name">${r.display_name || t('checkin.erased')}</strong>
                ${r.manual && html` <span class="badge">${t('checkin.by_hand')}</span>`}
                <div class="small muted">${r.player_id}${r.team_preference ? ` · ${t('checkin.prefers', { team: r.team_preference })}` : ''}</div></td>
            <td><span class=${`badge status-${r.status}`}>${t(`checkin.statuses.${r.status}`)}</span>
                ${r.status === 'pending' && html` <button type="button" class="primary" data-testid="checkin-confirm"
                    onClick=${() => this.patch(r.player_id, { status: 'checked_in' })}>${t('checkin.confirm')}</button>`}</td>
            <td>${active ? html`<select aria-label=${t('checkin.team')} data-testid="checkin-team" value=${r.team || ''}
                    onChange=${(e) => this.patch(r.player_id, { team: e.target.value || null, squad: 0 })}>
                    <option value="">–</option>${g.teams.map((tm) => html`<option value=${tm}>${tm}</option>`)}</select>${
                    squadsOf(g) && r.team ? html` › <select aria-label=${t('checkin.squad')} data-testid="checkin-squad"
                        value=${String(r.squad)} onChange=${(e) => this.patch(r.player_id, { squad: parseInt(e.target.value, 10) })}>
                        <option value="0">${t('checkin.no_squad')}</option>
                        ${Array.from({ length: squadsOf(g) }, (_, i) => html`<option value=${String(i + 1)}>${
                            t('checkin.squad_n', { n: i + 1 })}</option>`)}</select>` : ''}` : where(r.team, r.squad)}</td>
            <td>${active ? html`<select aria-label=${t('checkin.role')} data-testid="checkin-role" value=${r.role}
                    onChange=${(e) => this.patch(r.player_id, { role: e.target.value })}>
                    ${ROLES.filter((ro) => ro !== 'squad_leader' || squadsOf(g) || r.role === ro)
        .map((ro) => html`<option value=${ro}>${t(`checkin.roles.${ro}`)}</option>`)}</select>` : t(`checkin.roles.${r.role}`)}</td>
            ${s.federation !== 'off' && html`<td>${r.federation_number || '–'}
                ${r.federation_number && html`<label class="check small"><input type="checkbox" data-testid="checkin-card-seen"
                    checked=${r.federation_seen} disabled=${!active}
                    onChange=${(e) => this.patch(r.player_id, { federation_seen: e.target.checked })} /> ${
                    r.federation_seen ? t('checkin.card_seen') : t('checkin.not_checked')}</label>`}</td>`}
            <td data-testid="checkin-replicas">${decls.length}${decls.length ? ` (${Object.entries(counts)
                .map(([k, v]) => `${t(`checkin.states.${k}`)} ${v}`).join(', ')})` : ''}</td>
            <td>${active && html`<button type="button" class="link danger" data-testid="checkin-remove"
                onClick=${() => this.remove(r.player_id)}>${t('checkin.remove')}</button>`}</td>
        </tr>`;
    }

    renderManual(g, s) {
        const m = this.state.manual;
        if (!m) {
            return html`<div class="actions"><button type="button" data-testid="checkin-manual"
                onClick=${() => this.setState({ manual: { name: '', fed: '', team: '', replicas: [] } })}>${t('checkin.manual')}</button></div>`;
        }
        const set = (k, v) => this.setState({ manual: { ...m, [k]: v } });
        const setR = (i, k, v) => set('replicas', m.replicas.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
        const classes = this.state.classes;
        return html`<form class="form" data-testid="checkin-manual-form" onSubmit=${(e) => this.manualCheckin(e)}>
            <h3>${t('checkin.manual')}</h3>
            <p class="muted small">${t('checkin.manual_hint')}</p>
            <div class="field"><label for="cm-name">${t('checkin.name')}</label>
                <input id="cm-name" data-testid="checkin-manual-name" required maxlength="32" value=${m.name}
                    onInput=${(e) => set('name', e.target.value)} /></div>
            ${s.federation !== 'off' && html`<div class="field"><label for="cm-fed">${s.federation_label}</label>
                <input id="cm-fed" maxlength="32" required=${s.federation === 'required'} value=${m.fed}
                    onInput=${(e) => set('fed', e.target.value)} /></div>`}
            <div class="field"><label for="cm-team">${t('checkin.team_preference')}</label>
                <select id="cm-team" value=${m.team} onChange=${(e) => set('team', e.target.value)}>
                    <option value="">–</option>${g.teams.map((tm) => html`<option value=${tm}>${tm}</option>`)}</select></div>
            ${m.replicas.map((r, i) => html`<div class="form inline" data-testid="checkin-manual-replica">
                <div class="field"><label for=${`cm-t${i}`}>${t('checkin.type')}</label>
                    <select id=${`cm-t${i}`} value=${r.type} onChange=${(e) => setR(i, 'type', e.target.value)}>
                        ${TYPES.map((ty) => html`<option value=${ty}>${t(`checkin.types.${ty}`)}</option>`)}</select></div>
                <div class="field"><label for=${`cm-c${i}`}>${t('checkin.class')}</label>
                    <select id=${`cm-c${i}`} value=${r.cls} onChange=${(e) => setR(i, 'cls', e.target.value)}>
                        ${classes.map((c) => html`<option value=${c}>${c}</option>`)}</select></div>
                <div class="field"><label for=${`cm-m${i}`}>${t('checkin.make_model')}</label>
                    <input id=${`cm-m${i}`} maxlength="64" value=${r.mm} onInput=${(e) => setR(i, 'mm', e.target.value)} /></div>
                <button type="button" class="link" onClick=${() => set('replicas', m.replicas.filter((_, j) => j !== i))}>×</button>
            </div>`)}
            <div class="actions">
                <button type="button" data-testid="checkin-manual-add" disabled=${m.replicas.length >= s.max_replicas}
                    onClick=${() => set('replicas', [...m.replicas, { id: uuid4(), type: 'aeg', cls: classes[0] || 'rifle', mm: '' }])}>${t('checkin.add_replica')}</button>
                <button type="submit" class="primary" data-testid="checkin-manual-save">${t('checkin.manual_save')}</button>
                <button type="button" class="link" onClick=${() => this.setState({ manual: null })}>${t('common.cancel')}</button>
            </div>
        </form>`;
    }

    renderChrono() {
        const c = this.state.chrono;
        if (!c) return null;
        return html`<section class="card" aria-labelledby="cc-h">
            <h2 id="cc-h">${t('checkin.chrono_title')}</h2>
            <p class="muted">${t(c.chrono_valid_for === 'day' ? 'checkin.valid_day' : 'checkin.valid_game')}</p>
            <p data-testid="chrono-counts">${['pending', 'passed', 'refused'].map((s) => `${t(`checkin.states.${s}`)}: ${c.counts[s]}`).join(' · ')}</p>
            ${c.players.length === 0 && html`<p class="muted">${t('checkin.chrono_empty')}</p>`}
            <ul class="chrono-list" data-testid="chrono-list">${c.players.map((p) => html`<li data-testid=${`chrono-player-${p.player_id}`}>
                <strong>${p.display_name || p.player_id}</strong>${p.team ? ` · ${where(p.team, p.squad)}` : ''}
                ${p.status === 'pending' && html` <span class="badge status-pending">${t('checkin.statuses.pending')}</span>`}
                <ul>${p.declarations.map((d) => html`<li>
                    ${t(`checkin.types.${d.type}`)} · ${d.class}${d.make_model ? ` · ${d.make_model}` : ''}
                    ${!d.replica_id && html` <span class="small muted">${t('checkin.unregistered')}</span>`}
                    ${' '}<${StateBadge} state=${d.state} refusedToday=${d.refused_today} />
                </li>`)}</ul>
            </li>`)}</ul>
        </section>`;
    }

    renderSettings() {
        const list = this.state.list;
        if (!list) return null;
        const s = list.settings;
        return html`<section class="card" aria-labelledby="cs-h">
            <h2 id="cs-h">${t('checkin.settings')}</h2>
            <form class="form" data-testid="checkin-settings" onSubmit=${(e) => this.saveSettings(e)}>
                <div class="field"><label for="cs-confirm">${t('checkin.confirm_mode')}</label>
                    <select id="cs-confirm" name="confirm" value=${s.confirm}>
                        <option value="auto">${t('checkin.confirm_auto')}</option>
                        <option value="staff">${t('checkin.confirm_staff')}</option></select></div>
                <div class="field"><label for="cs-fed">${t('checkin.federation')}</label>
                    <select id="cs-fed" name="federation" data-testid="checkin-federation" value=${s.federation}>
                        ${['off', 'optional', 'required'].map((v) => html`<option value=${v}>${t(`checkin.federation_${v}`)}</option>`)}</select></div>
                <div class="field"><label for="cs-label">${t('checkin.federation_label')}</label>
                    <input id="cs-label" name="federation_label" maxlength="16" value=${s.federation_label} /></div>
                <div class="field"><label for="cs-max">${t('checkin.max_replicas')}</label>
                    <input id="cs-max" name="max_replicas" type="number" min="1" max="20" value=${s.max_replicas} /></div>
                <div class="field"><label for="cs-players">${t('checkin.max_players')}</label>
                    <input id="cs-players" name="max_players" type="number" min="1" max="5000" value=${s.max_players} /></div>
                <div class="field"><label for="cs-valid">${t('checkin.valid_for')}</label>
                    <select id="cs-valid" name="chrono_valid_for" value=${s.chrono_valid_for}>
                        <option value="day">${t('checkin.valid_for_day')}</option>
                        <option value="game">${t('checkin.valid_for_game')}</option></select></div>
                <p class="muted small">${t('checkin.federation_note')}</p>
                <button type="submit" data-testid="checkin-settings-save">${t('common.save')}</button>
            </form>
        </section>`;
    }

    renderPoster() {
        const p = this.state.poster;
        if (!p) return null;
        return html`<section class="card" aria-labelledby="cp-h">
            <h2 id="cp-h">${t('checkin.poster')}</h2>
            <p class="muted">${t('checkin.poster_intro')}</p>
            ${p.problem && html`<p class="warning" data-testid="poster-problem">${p.problem}</p>`}
            ${p.ca_short && html`<p>${t('checkin.ca')}: <code data-testid="poster-ca">${p.ca_short}</code></p>`}
            <form class="form" data-testid="poster-form" onSubmit=${(e) => this.savePoster(e)}>
                <div class="field"><label for="cp-urls">${t('checkin.poster_urls')}</label>
                    <textarea id="cp-urls" name="urls" rows="3" data-testid="poster-urls"
                        value=${(p.urls || []).join('\n')}></textarea></div>
                <div class="field"><label for="cp-ssid">${t('checkin.poster_ssid')}</label>
                    <input id="cp-ssid" name="wifi_ssid" maxlength="32" value=${p.wifi_ssid || ''} /></div>
                <label class="check"><input type="checkbox" name="pinned" checked=${!!p.game_id} disabled=${!this.game()} />
                    ${t('checkin.poster_pinned')}</label>
                <button type="submit" data-testid="poster-save">${t('common.save')}</button>
            </form>
        </section>`;
    }

    render(props) {
        const { role } = props.app.state;
        if (role !== 'gm') return html`<section class="card"><p class="muted">${t('checkin.gm_only')}</p></section>`;
        const g = this.game();
        const list = this.state.list;
        return html`<div>
            ${!g && html`<section class="card"><p class="muted" data-testid="checkin-no-game">${t('checkin.no_game')}</p></section>`}
            ${g && list && this.renderHead(g, list)}
            ${g && list && this.renderList(g, list)}
            ${g && this.renderChrono()}
            ${g && this.renderSettings()}
            ${this.renderPoster()}
        </div>`;
    }
}

function counts(rows) {
    const out = {};
    for (const s of STATUSES) out[s] = 0;
    for (const r of rows) out[r.status] = (out[r.status] || 0) + 1;
    return out;
}
