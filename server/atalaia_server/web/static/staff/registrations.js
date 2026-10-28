// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Who registered for one scheduled game (GET /api/v1/fields/{field}/scheduled-games/{id}/registrations, for
// the field's admin and gm), and what the API lets staff do: until the game starts, change a registration's
// display name, team preference, federation number and replicas (PATCH), move it to another published game
// that has not started (POST .../move), withdraw it (DELETE) or bring a withdrawn one back (POST .../restore);
// at any time note that it is paid (PUT .../payment); after the game, mark a player who did not come (PUT
// .../no-show). The registration list's import and its CSV export are here too. Check-in is not: the
// controller decides on the day, and the arrivals come from its sync. The rules are the API's.

import { $, boot, clear, el, enable, errorText, api, fieldApi, fieldPage, fillRows, page, status, t, when } from './staff.js';
import { apdChoices, asksMembership, changeable, loadBoth, membershipText, over, replicaCell, summarise, ticketText }
    from './registrants.js';

const base = () => `/scheduled-games/${encodeURIComponent(page.game)}/registrations`;
const regPath = (reg, rest = '') => fieldApi(`${base()}/${encodeURIComponent(reg.id)}${rest}`);
const MOVED = { team_preference: 'reg_moved_team', federation_number: 'reg_moved_fed', apd_id: 'reg_moved_fed', membership_expires: 'reg_moved_fed', replicas: 'reg_moved_replicas' };
let ctx = null;
let game = null;
let regList = { apd: {}, apds: [] };
let rules = { classes: [], replica_types: [], max_replicas: 0 };
let editing = null;
let rows = [];
let moving = null;
let titles = {};

function close() {
    editing = null;
    moving = null;
    $('reg-edit').hidden = true;
    $('reg-move').hidden = true;
}

// ---- the replicas in the edit form -------------------------------------------------------------

const limit = () => Math.min(rules.max_replicas, 20);

function option(value) {
    return el('option', { value, text: value });
}

function select(label, values, current, onchange) {
    const node = el('select', { 'aria-label': label }, values.map(option));
    node.value = current;
    node.addEventListener('change', () => onchange(node.value));
    return node;
}

function drawReplicas() {
    const list = clear($('r-replicas'));
    rows.forEach((entry, i) => {
        const item = el('li', { class: 'replica-row' });
        if (entry.replica_id) {
            const make = entry.make_model ? `, ${entry.make_model}` : '';
            item.append(el('span', { text: `${entry.type}, ${entry.class}${make} (${t('rep_registry')})` }));
        } else {
            const make = el('input', { type: 'text', maxlength: 64, 'aria-label': t('rep_make'), value: entry.make_model || '' });
            make.addEventListener('input', () => { entry.make_model = make.value; });
            item.append(
                select(t('rep_type'), rules.replica_types, entry.type, (v) => { entry.type = v; }),
                select(t('rep_class'), rules.classes, entry.class, (v) => { entry.class = v; }), make);
        }
        item.append(el('button', { type: 'button', class: 'danger', text: t('rep_remove'),
            'aria-label': `${t('rep_remove')}: ${entry.type}, ${entry.class}`,
            onclick: () => { rows.splice(i, 1); drawReplicas(); } }));
        list.append(item);
    });
    $('r-rep-none').hidden = rows.length > 0;
    $('r-rep-add').disabled = rows.length >= limit();
}

/** The replicas as the API takes them: a registry replica by its id, a new one by type, class and make. */
function replicaBody() {
    return rows.map((e) => (e.replica_id ? { replica_id: e.replica_id }
        : { type: e.type, class: e.class, make_model: (e.make_model || '').trim() || null }));
}

const replicaKey = (items) => JSON.stringify(items);

function edit(reg) {
    close();
    editing = reg;
    $('reg-edit-title').textContent = t('reg_edit_title', { name: reg.display_name || '' });
    $('r-name').value = reg.display_name || '';
    const teams = clear($('r-team'));
    teams.append(el('option', { value: '', text: t('reg_team_none') }));
    for (const team of game.teams || []) teams.append(el('option', { value: team, text: team }));
    teams.value = reg.team_preference || '';
    const asks = asksMembership(game, regList);
    $('r-fed-row').hidden = !asks;
    $('r-fed').value = reg.federation_number || '';
    const apds = clear($('r-apd'));
    apds.append(el('option', { value: '', text: t('apd_unknown') }));
    const known = apdChoices(regList);
    for (const e of known) apds.append(el('option', { value: e.id, text: e.short_name }));
    if (reg.apd_id && !known.some((e) => e.id === reg.apd_id)) apds.append(el('option', { value: reg.apd_id, text: reg.apd_id }));
    apds.value = reg.apd_id || '';
    $('r-expires').value = reg.membership_expires || '';
    const asked = game.predeclare_replicas && rules.classes.length > 0 && rules.replica_types.length > 0;
    $('r-replicas-row').hidden = !asked;
    $('r-rep-not-asked').hidden = game.predeclare_replicas;
    rows = (reg.replicas || []).map((r) => ({ replica_id: r.replica_id, type: r.type, class: r.class, make_model: r.make_model || '' }));
    $('r-rep-limit').textContent = t('rep_limit', { n: limit() });
    editing.original = replicaKey(replicaBody());
    drawReplicas();
    $('reg-edit').hidden = false;
    $('reg-edit-title').scrollIntoView({ block: 'start' });
    $('r-name').focus();
}

async function submit(event) {
    event.preventDefault();
    if (!editing) return;
    const reg = editing;
    const body = {};
    const name = $('r-name').value.trim();
    if (name !== (reg.display_name || '')) body.display_name = name;
    const team = $('r-team').value;
    if (team !== (reg.team_preference || '')) body.team_preference = team === '' ? null : team;
    const fed = $('r-fed').value.trim();
    if (asksMembership(game, regList)) {
        if (fed !== (reg.federation_number || '')) body.federation_number = fed === '' ? null : fed;
        const apd = $('r-apd').value;
        if (apd !== (reg.apd_id || '')) body.apd_id = apd === '' ? null : apd;
        const expires = $('r-expires').value;
        if (expires !== (reg.membership_expires || '')) body.membership_expires = expires === '' ? null : expires;
    }
    if (!$('r-replicas-row').hidden && replicaKey(replicaBody()) !== reg.original) body.replicas = replicaBody();
    if (Object.keys(body).length) {
        try {
            await api('PATCH', regPath(reg), body);
        } catch (err) {
            status(errorText(err), 'error');
            return;
        }
    }
    close();
    status(t('saved'), 'ok');
    await load();
}

// ---- moving, withdrawing, bringing back ---------------------------------------------------------

async function openMove(reg) {
    close();
    let games;
    try {
        games = await api('GET', fieldApi(`/scheduled-games?from=${encodeURIComponent(new Date().toISOString())}`));
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    const now = new Date();
    const targets = (games || []).filter((g) => g.id !== page.game && g.status === 'published' && new Date(g.starts_at) > now);
    moving = reg;
    $('reg-move-title').textContent = t('reg_move_title', { name: reg.display_name || '' });
    const chooser = clear($('m-game'));
    titles = {};
    for (const g of targets) {
        titles[g.id] = g.title;
        const places = g.max_players === null ? t('sched_places_nolimit', { n: g.registered })
            : t('sched_places', { n: g.registered, max: g.max_players });
        chooser.append(el('option', { value: g.id, disabled: g.places_left === 0,
            text: `${g.title} · ${when(g.starts_at, ctx.zone)} · ${places}` }));
    }
    $('m-none').hidden = targets.length > 0;
    $('m-go').disabled = targets.length === 0;
    $('reg-move').hidden = false;
    $('reg-move-title').scrollIntoView({ block: 'start' });
    chooser.focus();
}

async function submitMove(event) {
    event.preventDefault();
    if (!moving || !$('m-game').value) return;
    const reg = moving;
    const target = $('m-game').value;
    let moved;
    try {
        moved = await api('POST', regPath(reg, '/move'), { scheduled_game_id: target });
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    close();
    const notes = (moved.changed || []).filter((c) => c in MOVED).map((c) => t(MOVED[c]));
    status([t('reg_moved', { title: titles[target] || '' }), ...notes].join(' '), 'ok');
    await load();
}

/** One call on a registration, then a fresh list and a line in the status. */
async function act(call, message) {
    try {
        const answer = await call();
        status(message(answer), 'ok');
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    await load();
}

async function withdraw(reg) {
    if (!window.confirm(t('reg_withdraw_confirm', { name: reg.display_name || '' }))) return;
    if (editing && editing.id === reg.id) close();
    await act(() => api('DELETE', regPath(reg)), () => t('reg_withdrawn'));
}

const restore = (reg) => act(() => api('POST', regPath(reg, '/restore')), () => t('reg_restored'));
const setPaid = (reg, paid) => act(() => api('PUT', regPath(reg, '/payment'), { paid }),
    () => t(paid ? 'reg_marked_paid' : 'reg_marked_unpaid'));

async function setNoShow(reg, noShow) {
    if (noShow && !window.confirm(t('reg_no_show_confirm', { name: reg.display_name || '' }))) return;
    await act(() => api('PUT', regPath(reg, '/no-show'), { no_show: noShow }),
        () => t(noShow ? 'reg_no_show_done' : 'reg_no_show_undone'));
}

// ---- the list --------------------------------------------------------------------------------------

function button(text, who, onclick, danger = false) {
    return el('button', { type: 'button', class: danger ? 'danger' : null, text, 'aria-label': `${text}: ${who}`, onclick });
}

function actions(reg) {
    const who = reg.display_name || '';
    const live = changeable(game);
    const out = [];
    if (reg.status === 'registered' && live) {
        out.push(button(t('edit'), who, () => edit(reg)), button(t('reg_move'), who, () => openMove(reg)),
            button(t('reg_withdraw'), who, () => withdraw(reg), true));
    }
    if (reg.status === 'cancelled' && live && reg.display_name) out.push(button(t('reg_restore'), who, () => restore(reg)));
    if (reg.status === 'registered' && over(game)) out.push(button(t('reg_no_show'), who, () => setNoShow(reg, true)));
    if (reg.status === 'no_show' && reg.no_show_by_staff) out.push(button(t('reg_no_show_undo'), who, () => setNoShow(reg, false)));
    if (reg.paid) out.push(button(t('reg_mark_unpaid'), who, () => setPaid(reg, false)));
    else if (reg.status !== 'cancelled' && game.status !== 'cancelled') out.push(button(t('reg_mark_paid'), who, () => setPaid(reg, true)));
    return out.length ? el('span', { class: 'actions' }, out) : '';
}

function paidText(reg) {
    if (!reg.paid) return reg.status === 'cancelled' ? t('none') : t('reg_paid_no');
    const at = when(reg.paid_at, ctx.zone);
    return reg.paid_by ? t('reg_paid_yes', { at, by: reg.paid_by }) : t('reg_paid_yes_nobody', { at });
}

async function load() {
    let loaded;
    try {
        loaded = await loadBoth();
    } catch (err) {
        status(errorText(err), 'error');
        return false;
    }
    game = loaded.game;
    const { list } = loaded;
    regList = list;
    $('regs-heading').textContent = t('regs_heading', { title: game.title });
    summarise($('summary'), game, ctx.zone);
    const counts = list.counts || {};
    const text = t('regs_counts', {
        registered: counts.registered || 0, checked_in: counts.checked_in || 0, no_show: counts.no_show || 0,
        cancelled: counts.cancelled || 0,
    });
    $('counts').textContent = list.walkins === null || list.walkins === undefined ? text
        : `${text} ${t('regs_walkins', { n: list.walkins })}`;
    $('locked').hidden = changeable(game);
    const roster = $('roster-link');
    roster.hidden = game.status === 'draft';
    roster.firstChild.setAttribute('href', fieldPage(`/schedule/${encodeURIComponent(page.game)}/roster`));
    const asks = asksMembership(game, list);
    $('th-fed').hidden = !asks;
    const regs = list.registrations || [];
    fillRows($('regs'), regs.map((r) => [
        r.display_name || t('none'), r.team_preference || t('none'), ...(asks ? [membershipText(r, list)] : []),
        replicaCell(r.replicas, true), ticketText(r), t(`reg_status_${r.status}`), paidText(r),
        r.source === 'site' ? t('source_site') : r.source, actions(r)]));
    $('regs').hidden = regs.length === 0;
    $('regs-none').hidden = regs.length > 0;
    $('io-locked').hidden = changeable(game);
    $('io-check').disabled = !changeable(game);
    syncImport();
    return true;
}

// ---- the export and the import -----------------------------------------------------------------

async function exportCsv() {
    let file;
    try {
        file = await api('GET', fieldApi(`${base()}.csv`), undefined, { blob: true });
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    const url = URL.createObjectURL(file);
    const link = el('a', { href: null, download: `registrations-${page.game}.csv` });
    link.setAttribute('href', url);  // a blob: address, made here, never one from the server
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    status(t('io_exported'), 'ok');
}

function syncImport() {
    $('io-run').disabled = !(changeable(game) && $('io-basis').checked);
}

async function runImport(dryRun) {
    const file = $('io-file').files[0];
    if (!file) {
        status(t('io_no_file'), 'error');
        return;
    }
    const source = $('io-source').value.trim();
    const json = file.name.toLowerCase().endsWith('.json') || file.type === 'application/json';
    const query = `source=${encodeURIComponent(source)}&dry_run=${dryRun}&basis_confirmed=${!dryRun}`;
    let answer;
    try {
        answer = await api('POST', fieldApi(`${base()}/import?${query}`), await file.arrayBuffer(),
            { type: json ? 'application/json' : 'text/csv; charset=utf-8' });
    } catch (err) {
        status(errorText(err), 'error');
        return;
    }
    showImport(answer);
    status(t(dryRun ? 'io_dry' : 'io_done'), 'ok');
    if (!dryRun) {
        $('io-file').value = '';
        await load();
    }
}

const CAP = 200;

function reason(row) {
    const parts = [];
    if (row.code) parts.push(t(`e_${row.code}`));
    for (const w of row.warnings || []) parts.push(t(`io_warn_${w}`));
    return parts.join('; ');
}

function showImport(answer) {
    const c = answer.counts || {};
    const lines = [t('io_counts', { rows: answer.rows, created: c.created || 0, updated: c.updated || 0,
        unchanged: c.unchanged || 0, skipped: c.skipped || 0, refused: c.refused || 0 })];
    if (answer.missing && answer.missing.count) lines.push(t('io_missing', { n: answer.missing.count }));
    const ignored = answer.not_imported_columns || [];
    if (ignored.length) lines.push(t('io_ignored', { names: ignored.join(', ') }));
    $('io-summary').textContent = lines.join(' ');
    const attention = (answer.results || []).filter((r) => r.result === 'refused' || r.result === 'skipped'
        || (r.warnings && r.warnings.length));
    $('io-issues').hidden = attention.length === 0;
    fillRows($('io-rows'), attention.slice(0, CAP).map((r) => [
        [String(r.row), { class: 'num' }], r.display_name || t('none'), t(`io_res_${r.result}`), reason(r)]));
    $('io-more').hidden = attention.length <= CAP;
    $('io-more').textContent = t('io_more', { n: attention.length - CAP });
    $('io-result').hidden = false;
}

// ---- the page -------------------------------------------------------------------------------------------

async function main() {
    ctx = await boot();
    if (!ctx) return;
    if (ctx.field && ctx.field.slug) {
        try {
            rules = await api('GET', `/api/v1/fields-by-slug/${encodeURIComponent(ctx.field.slug)}`).then((a) => a.field);
        } catch (err) {
            status(errorText(err), 'error');
        }
    }
    if (!(await load())) return;
    $('back').setAttribute('href', fieldPage('/schedule'));
    enable($('reg-form'));
    enable($('move-form'));
    enable($('io-form'));
    $('reg-form').addEventListener('submit', submit);
    $('r-cancel').addEventListener('click', close);
    $('r-rep-add').addEventListener('click', () => {
        rows.push({ replica_id: null, type: rules.replica_types[0], class: rules.classes[0], make_model: '' });
        drawReplicas();
    });
    $('move-form').addEventListener('submit', submitMove);
    $('m-cancel').addEventListener('click', close);
    $('io-export').addEventListener('click', exportCsv);
    $('io-export').disabled = false;  // disabled in the page until its listener is there
    $('io-basis').addEventListener('change', syncImport);
    $('io-check').addEventListener('click', () => runImport(true));
    $('io-form').addEventListener('submit', (event) => {
        event.preventDefault();
        if (!$('io-run').disabled) runImport(false);
    });
}

main();
