// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Field check-in (ADR-P3-13, protocol/checkin.md): the GM opens or closes
// check-in for the live game, sets the field's rules, prints the check-in
// poster, follows the check-ins as they arrive (names are shown here, to
// staff, and nowhere else), confirms them, ticks "card seen" for a
// federation number, gives teams, squads and roles, checks in a player
// without the app, keeps the list of marshals (the only way to be one: the
// controller gives each an id, the app shows it, decisions MR-1 to MR-14),
// and works through the "replicas to chrono" list that
// the marshals' signed readings fill in. With a site server (plan phase 16):
// a game made from the schedule, its registered players as "expected"
// until they arrive, a printed ticket scanned or pasted, and the counts of
// registered players and walk-ins.

import { html, Component, t, posterProblem, inWebView } from '../ui.js';

const STATUSES = ['expected', 'pending', 'checked_in', 'left', 'removed'];
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
        this.state = { list: null, chrono: null, poster: null, classes: [], manual: null, busy: false, schedule: null, ticket: '' };
    }

    componentDidMount() {
        this.load();
        // A marshal's app registers its key without telling the stream: the list asks now and then.
        // Not while the GM edits a row of the list: drawing it again from the controller's answer would put
        // back the old name under the cursor, and the edit would be lost (found by the browser test, 2026-10-26).
        this.marshalTimer = setInterval(() => {
            const editing = document.activeElement && document.activeElement.closest('[data-testid="marshals-table"]');
            if (this.props.app.state.role === 'gm' && this.state.marshals && !editing) this.loadMarshals();
        }, 5000);
    }

    componentDidUpdate() {
        // A reload when the live game changes (the stream's first game after the tab was opened, a new game,
        // the game's end). Compared with the game the last load was for: the previous props cannot tell, as
        // their "app" is the App itself and already holds the new game (decision FL-1).
        const g = this.game();
        if ((g ? g.id : null) !== this.loadedFor) this.load();
    }

    game() {
        const g = this.props.app.state.game;
        return g && g.live && g.state !== 'ended' ? g : null;
    }

    async load() {
        const app = this.props.app;
        const g = this.game();
        const id = g ? g.id : null;
        if (id !== this.loadedFor && this.state.list) this.setState({ list: null, chrono: null }); // not the last game's
        this.loadedFor = id;
        if (app.state.role !== 'gm') return;
        // Only the latest load is shown: an earlier one (for no game, or the game before) can answer last.
        const seq = (this.loadSeq = (this.loadSeq || 0) + 1);
        const [poster, info, schedule, marshals] = await Promise.all([app.call('GET', '/checkin/poster'), app.call('GET', '/checkin'),
            app.serves('schedule') ? app.call('GET', '/schedule') : null, app.call('GET', '/marshals')]);
        if (seq !== this.loadSeq) return;
        this.setState({ poster, classes: info ? info.limits.classes : [], schedule, marshals: marshals || [] });
        if (!g) {
            this.setState({ list: null, chrono: null });
            return;
        }
        const [list, chrono] = await Promise.all([app.call('GET', `/games/${g.id}/checkins`),
            app.call('GET', `/games/${g.id}/chrono-list`)]);
        if (seq !== this.loadSeq) return;
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
        } else if (msg.type === 'roster') {
            this.load();
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
        clearInterval(this.marshalTimer);
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

    /** The marshal list (MR-1): the GM's, and the only way to be a marshal. */
    async loadMarshals() {
        const marshals = await this.props.app.call('GET', '/marshals');
        // Only when something changed: a re-render would put back a name the GM is typing.
        if (marshals && JSON.stringify(marshals) !== JSON.stringify(this.state.marshals)) this.setState({ marshals });
    }

    async addMarshal(e) {
        e.preventDefault();
        const a = this.state.addMarshal || { player: '', name: '', id: '' };
        const body = {};
        if (a.player) body.player_id = a.player;
        if (a.name.trim()) body.name = a.name.trim();
        if (a.id.trim()) body.marshal_id = a.id.trim();
        const m = await this.props.app.call('POST', '/marshals', body);
        if (m) {
            this.setState({ addMarshal: { player: '', name: '', id: '' } });
            this.props.app.showToast(t('checkin.marshals.added', { id: m.marshal_id }));
            await this.loadMarshals();
        }
    }

    async patchMarshal(id, body) {
        const m = await this.props.app.call('PATCH', `/marshals/${encodeURIComponent(id)}`, body);
        if (m) await this.loadMarshals();
    }

    // The name typed in a row, when the field is left: saved if it changed, then the controller's again.
    async saveMarshalName(m, typed) {
        const name = typed.trim();
        if (name && name !== m.name) await this.patchMarshal(m.marshal_id, { name });
        const { [m.marshal_id]: _, ...rest } = this.state.nameEdits || {};
        this.setState({ nameEdits: rest });
    }

    async removeMarshal(m) {
        if (!window.confirm(t('checkin.marshals.remove_confirm', { id: m.marshal_id, name: m.name }))) return;
        const r = await this.props.app.call('DELETE', `/marshals/${encodeURIComponent(m.marshal_id)}`);
        if (r) {
            this.props.app.showToast(t('checkin.marshals.removed', { id: m.marshal_id }));
            await this.loadMarshals();
        }
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

    async ticketCheckin(e) {
        e.preventDefault();
        const g = this.game();
        const row = await this.props.app.call('POST', `/games/${g.id}/checkins/ticket`, { ticket: this.state.ticket.trim() });
        if (row) {
            this.setState({ ticket: '' });
            this.onStream({ type: 'checkin', game: g.id, checkin: row });
            this.props.app.showToast(t('checkin.ticket_done', { name: row.display_name || row.player_id }));
        }
    }

    async fromSchedule(id) {
        const game = await this.props.app.call('POST', `/schedule/${id}/game`, {});
        if (game) {
            this.props.app.setGame(game);
            this.load();
        }
    }

    renderSchedule() {
        const sc = this.state.schedule;
        if (!sc || !sc.enabled) return null;
        const live = this.game();
        return html`<section class="card" aria-labelledby="csch-h" data-testid="schedule">
            <h2 id="csch-h">${t('checkin.schedule_title')}</h2>
            <p class="muted">${t('checkin.schedule_intro')}</p>
            ${sc.games.length === 0 && html`<p class="muted" data-testid="schedule-empty">${t('checkin.schedule_none')}</p>`}
            <ul class="chrono-list">${sc.games.map((sg) => html`<li data-testid=${`schedule-${sg.scheduled_game_id}`}>
                <strong>${sg.title}</strong> · ${new Date(sg.starts_at * 1000).toLocaleString()}
                · ${t('checkin.schedule_registered', { n: sg.registered })}
                ${sg.games.length > 0 && html` <span class="small muted">${t('checkin.schedule_made', { ids: sg.games.join(', ') })}</span>`}
                ${' '}<button type="button" data-testid="schedule-create" disabled=${!!live}
                    onClick=${() => this.fromSchedule(sg.scheduled_game_id)}>${t('checkin.schedule_create')}</button>
            </li>`)}</ul>
        </section>`;
    }

    renderTicket(g) {
        return html`<form class="form inline" data-testid="ticket-form" onSubmit=${(e) => this.ticketCheckin(e)}>
            <h3>${t('checkin.ticket_title')}</h3>
            <p class="muted small">${t('checkin.ticket_hint')}</p>
            <div class="field"><label for="ct-ticket">${t('checkin.ticket_label')}</label>
                <input id="ct-ticket" data-testid="ticket-input" required maxlength="256" value=${this.state.ticket}
                    onInput=${(e) => this.setState({ ticket: e.target.value })} /></div>
            <button type="submit" class="primary" data-testid="ticket-submit">${t('checkin.ticket_submit')}</button>
        </form>`;
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
            ${inWebView() && html`<p class="muted small" data-testid="checkin-webview">${t('checkin.webview_notice')}</p>`}
            <p class="small" data-testid="checkin-counts">${STATUSES.map((s) => `${t(`checkin.statuses.${s}`)}: ${c[s] || 0}`).join(' · ')}</p>
            ${registeredCounts(list.checkins) && html`<p class="small" data-testid="checkin-registered">${
                t('checkin.registered_counts', registeredCounts(list.checkins))}</p>`}
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
            ${this.renderTicket(g)}
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
                ${r.registered && html` <span class="badge" data-testid="checkin-registered-badge">${t('checkin.registered_badge')}</span>`}
                <div class="small muted">${r.player_id}${r.team_preference ? ` · ${t('checkin.prefers', { team: r.team_preference })}` : ''}</div></td>
            <td><span class=${`badge status-${r.status}`}>${t(`checkin.statuses.${r.status}`)}</span>
                ${r.status === 'pending' && html` <button type="button" class="primary" data-testid="checkin-confirm"
                    onClick=${() => this.patch(r.player_id, { status: 'checked_in' })}>${t('checkin.confirm')}</button>`}
                ${r.status === 'expected' && html` <button type="button" class="primary" data-testid="checkin-arrived"
                    onClick=${() => this.patch(r.player_id, { status: 'checked_in' })}>${t('checkin.arrived')}</button>`}</td>
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

    /** Who may act as a marshal: ids the controller gives, a player each, and whether their app has registered its key. */
    renderMarshals(g, list) {
        const marshals = this.state.marshals;
        if (!marshals) return null;
        const here = list ? list.checkins.filter((r) => r.status === 'pending' || r.status === 'checked_in') : [];
        const nameOf = (pid) => {
            const row = list && list.checkins.find((r) => r.player_id === pid);
            return row && row.display_name ? row.display_name : pid;
        };
        const taken = new Set(marshals.map((m) => m.player_id).filter(Boolean));
        // A name being typed stays the GM's until it is saved: every new drawing of the panel (the stream, the
        // list's refresh) would otherwise put the controller's name back under the cursor.
        const edits = this.state.nameEdits || {};
        const add = this.state.addMarshal || { player: '', name: '', id: '' };
        const setAdd = (k, v) => this.setState({ addMarshal: { ...add, [k]: v } });
        return html`<section class="card" aria-labelledby="cm-h" data-testid="marshals">
            <h2 id="cm-h">${t('checkin.marshals.title')}</h2>
            <p class="muted">${t('checkin.marshals.intro')}</p>
            ${marshals.length === 0 && html`<p class="muted" data-testid="marshals-empty">${t('checkin.marshals.empty')}</p>`}
            ${marshals.length > 0 && html`<div class="table-wrap"><table class="table" data-testid="marshals-table">
                <thead><tr><th>${t('checkin.marshals.id')}</th><th>${t('checkin.marshals.name')}</th>
                    <th>${t('checkin.marshals.player')}</th><th>${t('checkin.marshals.key')}</th><th></th></tr></thead>
                <tbody>${marshals.map((m) => html`<tr data-testid=${`marshal-row-${m.marshal_id}`}>
                    <td><strong data-testid="marshal-id">${m.marshal_id}</strong></td>
                    <td><input aria-label=${t('checkin.marshals.name')} data-testid="marshal-name" maxlength="64"
                        value=${edits[m.marshal_id] !== undefined ? edits[m.marshal_id] : m.name}
                        onInput=${(e) => this.setState({ nameEdits: { ...edits, [m.marshal_id]: e.target.value } })}
                        onChange=${(e) => this.saveMarshalName(m, e.target.value)} /></td>
                    <td><select aria-label=${t('checkin.marshals.player')} data-testid="marshal-player" value=${m.player_id || ''}
                        onChange=${(e) => this.patchMarshal(m.marshal_id, { player_id: e.target.value || null })}>
                        <option value="">${t('checkin.marshals.no_player')}</option>
                        ${m.player_id && !here.some((r) => r.player_id === m.player_id)
                            && html`<option value=${m.player_id}>${nameOf(m.player_id)}</option>`}
                        ${here.filter((r) => !taken.has(r.player_id) || r.player_id === m.player_id).map((r) => html`<option
                            value=${r.player_id}>${r.display_name || r.player_id}</option>`)}</select></td>
                    <td><span class=${`badge ${m.key_registered ? 'status-checked_in' : 'status-pending'}`} data-testid="marshal-key">${
                        t(m.key_registered ? 'checkin.marshals.key_ok' : 'checkin.marshals.key_waiting')}</span></td>
                    <td><button type="button" class="link danger" data-testid="marshal-remove"
                        onClick=${() => this.removeMarshal(m)}>${t('checkin.marshals.remove')}</button></td>
                </tr>`)}</tbody>
            </table></div>`}
            <form class="form inline" data-testid="marshal-add-form" onSubmit=${(e) => this.addMarshal(e)}>
                <h3>${t('checkin.marshals.add')}</h3>
                <div class="field"><label for="cm-player">${t('checkin.marshals.add_player')}</label>
                    <select id="cm-player" data-testid="marshal-add-player" value=${add.player}
                        onChange=${(e) => setAdd('player', e.target.value)}>
                        <option value="">–</option>
                        ${here.filter((r) => !taken.has(r.player_id)).map((r) => html`<option
                            value=${r.player_id}>${r.display_name || r.player_id}</option>`)}</select></div>
                <div class="field"><label for="cm-mname">${t('checkin.marshals.add_name')}</label>
                    <input id="cm-mname" data-testid="marshal-add-name" maxlength="64" value=${add.name}
                        onInput=${(e) => setAdd('name', e.target.value)} /></div>
                <div class="field"><label for="cm-mid">${t('checkin.marshals.add_id')}</label>
                    <input id="cm-mid" data-testid="marshal-add-id" maxlength="64" pattern="[A-Za-z0-9._:\\-]+" value=${add.id}
                        onInput=${(e) => setAdd('id', e.target.value)} /></div>
                <button type="submit" class="primary" data-testid="marshal-add" disabled=${!add.player && !add.name.trim()}>${
                    t('checkin.marshals.add')}</button>
            </form>
        </section>`;
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
            ${p.problem && html`<p class="warning" data-testid="poster-problem">${posterProblem(p)}</p>`}
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
            ${this.renderSchedule()}
            ${g && list && this.renderHead(g, list)}
            ${g && list && this.renderList(g, list)}
            ${this.renderMarshals(g, list)}
            ${g && this.renderChrono()}
            ${g && this.renderSettings()}
            ${this.renderPoster()}
        </div>`;
    }
}

/** Registered players expected and arrived, and walk-ins; null when nobody here registered online. */
function registeredCounts(rows) {
    if (!rows.some((r) => r.registered)) return null;
    const here = rows.filter((r) => r.status === 'pending' || r.status === 'checked_in');
    return { expected: rows.filter((r) => r.status === 'expected').length,
        arrived: here.filter((r) => r.registered).length, walkins: here.filter((r) => !r.registered).length };
}

function counts(rows) {
    const out = {};
    for (const s of STATUSES) out[s] = 0;
    for (const r of rows) out[r.status] = (out[r.status] || 0) + 1;
    return out;
}
