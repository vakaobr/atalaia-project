// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Indoor BLE beacons (ADR-P3-6, decisions BLE-1 to BLE-9): the registry of the iBeacon hardware the
// GM has put up in a building. Each beacon is its UUID, major and minor, the room it is in (and an
// optional zone) and the level of the plan it is on, and may be placed on that plan. A player's phone
// reports the strongest registered beacon it hears and the controller turns it into the room, which
// is what the GM, the ATAK feed and the player see: room-level, never metre-level (no triangulation).
// The controller keeps the registry (GET|POST /api/v1/beacons, PUT|DELETE .../{major:minor}); only
// the GM token reads the rooms (a player's phone is given each beacon's id and UUID, nothing else).
//
// On the plan: a pin (a button, focusable, with its room) at each placed beacon of the shown level,
// under the boxes. The editor under the plan places a beacon by a click on the plan, or by typing a
// place across and down it, as the map features' editor does.
//
// The Field Boxes are beacons too (decisions BBC-1 to BBC-12): the controller lists the boxes of the live
// game that the GM has placed, each as a beacon of kind "box" with its room (the box's name, or the one the
// GM gives) and its level and place from the field view. They are not edited as tags (no UUID, major or
// minor to type, no pin: the box's own marker is its place); the GM can disable one, give it a room, or turn
// the field's boxes off (PUT /api/v1/box-beacons, .../{node}).

import { html, Component, t, ConfirmButton } from '../ui.js';
import { levelName, levelsInUse } from './field-levels.js';

const UUID_RE = /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
// The pin's icon: a beacon sending out waves, drawn in white on its colour (24 x 24).
const ICON = 'M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM7.2 7.2l1.4 1.4a5 5 0 0 0 0 6.8l-1.4 1.4a7 7 0 0 1 0-9.6zm9.6 0a7 7 0 0 1 0 9.6l-1.4-1.4a5 5 0 0 0 0-6.8l1.4-1.4z';
export const BEACON_COLOUR = '#0ea5e9';

/** A beacon's name as shown: its room, and the zone when it has one. */
export function beaconName(b) {
    return b.zone ? `${b.room} (${b.zone})` : b.room;
}

/** A pin per placed beacon of the shown level (the GM edits it from the list below the plan). */
export function beaconPins(beacons, level, onSelect) {
    return beacons.filter((b) => b.kind !== 'box' && b.level === level && typeof b.x === 'number').map((b) => {
        const label = t('beacons.pin', { id: b.id, name: beaconName(b) });
        return html`<button type="button" class=${`bc-pin${b.draft ? ' draft' : ''}`}
            data-testid=${`bc-pin-${b.id}`} aria-label=${label} title=${label} onClick=${() => onSelect && onSelect(b)}
            ref=${(el) => {
                if (!el) return;
                el.style.left = `${(b.x * 100).toFixed(2)}%`;
                el.style.top = `${(b.y * 100).toFixed(2)}%`;
                el.style.background = BEACON_COLOUR;
            }}><svg class="mf-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d=${ICON} /></svg></button>`;
    });
}

/** A new beacon's form values: the UUID of the last one (a building usually has one), on the shown level. */
export function newBeaconDraft(level, beacons) {
    const tags = beacons.filter((b) => b.kind !== 'box');
    const last = tags.length ? tags[tags.length - 1].uuid : '';
    return { id: 'new', draft: true, uuid: last, major: '', minor: '', room: '', zone: '', level, x: null, y: null,
             placing: false };
}

/** The editor under the plan: the registry, and the GM's form. */
export class BeaconPanel extends Component {
    constructor() {
        super();
        this.state = { error: '', across: '', down: '', boxRoom: null };
    }

    set(change) {
        this.setState({ error: '' });
        this.props.onDraft({ ...this.props.draft, ...change });
    }

    edit(b) {
        this.setState({ error: '', across: '', down: '' });
        this.props.onDraft({ ...b, draft: true, placing: false, x: b.x ?? null, y: b.y ?? null });
    }

    /** A place typed with the keyboard: across and down the plan, in %. */
    typedPlace() {
        const across = Number(this.state.across);
        const down = Number(this.state.down);
        if (this.state.across === '' || this.state.down === '' || !(across >= 0 && across <= 100)
            || !(down >= 0 && down <= 100)) {
            this.setState({ error: t('features.bad_place') });
            return;
        }
        this.props.onPlace({ x: across / 100, y: down / 100 });
        this.setState({ across: '', down: '' });
    }

    /** The form's values as the API takes them, or an error text. */
    body() {
        const d = this.props.draft;
        const number = (v) => (v === '' || v === null ? NaN : Number(v));
        const major = number(d.major);
        const minor = number(d.minor);
        if (!UUID_RE.test(d.uuid.trim())) return { error: t('beacons.bad_uuid') };
        for (const v of [major, minor]) {
            if (!Number.isInteger(v) || v < 0 || v > 65535) return { error: t('beacons.bad_id') };
        }
        if (!d.room.trim()) return { error: t('beacons.need_room') };
        return { body: { uuid: d.uuid.trim(), major, minor, room: d.room, zone: d.zone, level: d.level, x: d.x, y: d.y } };
    }

    async save(e) {
        e.preventDefault();
        const d = this.props.draft;
        const { body, error } = this.body();
        if (error) {
            this.setState({ error });
            return;
        }
        const out = d.id === 'new' ? await this.props.app.call('POST', '/beacons', body)
            : await this.props.app.call('PUT', `/beacons/${d.id}`, body);
        if (out) {
            this.props.onDraft(null);
            this.props.app.loadBeacons();
        }
    }

    async remove(b) {
        const out = await this.props.app.call('DELETE', `/beacons/${b.id}`);
        if (out) this.props.app.loadBeacons();
    }

    /** The GM's choice for the field's boxes, or for one of them. */
    async boxCall(path, body) {
        const out = await this.props.app.call('PUT', path, body);
        if (out) this.props.app.loadBeacons();
        return out;
    }

    async saveBoxRoom(b) {
        const text = this.state.boxRoom.text.trim();
        const out = await this.boxCall(`/box-beacons/${b.node_id}`, { room: text === '' ? null : text });
        if (out) this.setState({ boxRoom: null });
    }

    renderBoxes() {
        const { beacons, levels, canEdit, boxStatus } = this.props;
        const boxes = beacons.filter((b) => b.kind === 'box');
        const multi = levelsInUse(levels) > 1;
        const editing = this.state.boxRoom;
        return html`<div class="bc-boxes" data-testid="bc-boxes">
            <h3 id="bc-boxes-h">${t('beacons.boxes_title')}</h3>
            <p class="muted small">${t('beacons.boxes_intro')}</p>
            ${canEdit && boxStatus && html`<div class="field"><label><input type="checkbox" data-testid="bc-box-switch"
                checked=${boxStatus.enabled} onChange=${(e) => this.boxCall('/box-beacons', { enabled: e.target.checked })} />
                ${' '}${t('beacons.boxes_switch')}</label></div>`}
            ${boxes.length === 0 && html`<p class="muted small" data-testid="bc-box-none">${t('beacons.boxes_none')}</p>`}
            ${boxes.length > 0 && html`<ul class="mf-list" data-testid="bc-box-list" aria-labelledby="bc-boxes-h">${boxes.map((b) => html`<li data-testid=${`bc-box-${b.node_id}`}>
                <span class="mf-what"><strong>${b.room}</strong>
                    <span class="muted small">${t('beacons.box_label')} · ${b.id}${multi ? ` · ${levelName(levels, b.level)}` : ''}${
                        b.enabled ? '' : ` · ${t('beacons.box_disabled')}`}</span></span>
                ${canEdit && html`<span class="mf-actions">
                    <button type="button" data-testid=${`bc-box-toggle-${b.node_id}`}
                        aria-label=${t(b.enabled ? 'beacons.box_disable_of' : 'beacons.box_enable_of', { name: b.room })}
                        onClick=${() => this.boxCall(`/box-beacons/${b.node_id}`, { enabled: !b.enabled })}>${
                        t(b.enabled ? 'beacons.box_disable' : 'beacons.box_enable')}</button>
                    <button type="button" data-testid=${`bc-box-room-${b.node_id}`}
                        onClick=${() => this.setState({ boxRoom: { node: b.node_id, text: b.room_given ? b.room : '' } })}>${
                        t('beacons.box_room_edit')}</button>
                </span>`}
                ${canEdit && editing && editing.node === b.node_id && html`<form class="bc-box-room"
                    onSubmit=${(e) => { e.preventDefault(); this.saveBoxRoom(b); }}>
                    <label for=${`bc-box-room-input-${b.node_id}`}>${t('beacons.box_room_label', { name: b.name })}</label>
                    <input id=${`bc-box-room-input-${b.node_id}`} data-testid="bc-box-room-input" maxlength="48" autocomplete="off"
                        value=${editing.text} onInput=${(e) => this.setState({ boxRoom: { ...editing, text: e.target.value } })} />
                    <button type="submit" class="primary" data-testid="bc-box-room-save">${t('beacons.box_room_save')}</button>
                    <button type="button" data-testid="bc-box-room-cancel" onClick=${() => this.setState({ boxRoom: null })}>${
                        t('common.cancel')}</button>
                </form>`}
            </li>`)}</ul>`}
        </div>`;
    }

    renderList() {
        const { levels, canEdit } = this.props;
        const beacons = this.props.beacons.filter((b) => b.kind !== 'box');
        if (!beacons.length) return html`<p class="muted small" data-testid="bc-none">${t('beacons.none')}</p>`;
        const multi = levelsInUse(levels) > 1;
        return html`<ul class="mf-list" data-testid="bc-list">${beacons.map((b) => html`<li data-testid=${`bc-item-${b.id}`}>
            <span class="mf-swatch" ref=${(el) => { if (el) el.style.background = BEACON_COLOUR; }}>
                <svg class="mf-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d=${ICON} /></svg></span>
            <span class="mf-what"><strong>${beaconName(b)}</strong>
                <span class="muted small">${b.id}${multi ? ` · ${levelName(levels, b.level)}` : ''} · ${
                    typeof b.x === 'number' ? t('beacons.placed') : t('beacons.not_placed')}</span></span>
            ${canEdit && html`<span class="mf-actions">
                <button type="button" data-testid=${`bc-edit-${b.id}`} onClick=${() => this.edit(b)}>${t('features.edit')}</button>
                <${ConfirmButton} label=${t('features.delete')} testid=${`bc-delete-${b.id}`}
                    question=${t('beacons.confirm_delete', { name: beaconName(b) })} onConfirm=${() => this.remove(b)} />
            </span>`}
        </li>`)}</ul>`;
    }

    renderPlacing() {
        const d = this.props.draft;
        return html`<div class="mf-placing" data-testid="bc-placing">
            <p class="small" role="status" data-testid="bc-hint">${t('beacons.placing')}</p>
            <fieldset class="mf-keys">
                <legend>${t('features.keyboard')}</legend>
                <div class="field"><label for="bc-across">${t('features.across')}</label>
                    <input id="bc-across" data-testid="bc-across" type="number" min="0" max="100" step="0.1"
                        inputmode="decimal" value=${this.state.across}
                        onInput=${(e) => this.setState({ across: e.target.value })} /></div>
                <div class="field"><label for="bc-down">${t('features.down')}</label>
                    <input id="bc-down" data-testid="bc-down" type="number" min="0" max="100" step="0.1"
                        inputmode="decimal" value=${this.state.down}
                        onInput=${(e) => this.setState({ down: e.target.value })} /></div>
                <button type="button" data-testid="bc-put" onClick=${() => this.typedPlace()}>${t('features.set_point')}</button>
            </fieldset>
            ${d.x !== null && html`<div class="actions"><button type="button" data-testid="bc-unplace"
                onClick=${() => this.set({ x: null, y: null })}>${t('beacons.unplace')}</button></div>`}
        </div>`;
    }

    renderForm() {
        const { draft: d, levels } = this.props;
        const count = levelsInUse(levels);
        const adding = d.id === 'new';
        return html`<form class="form mf-form" data-testid="bc-form" novalidate onSubmit=${(e) => this.save(e)}
            aria-labelledby="bc-form-h">
            <h3 id="bc-form-h">${adding ? t('beacons.add') : t('beacons.editing', { name: beaconName(d) })}</h3>
            <div class="params">
                <div class="field"><label for="bc-uuid">${t('beacons.uuid')}</label>
                    <input id="bc-uuid" data-testid="bc-uuid" autocomplete="off" spellcheck="false" value=${d.uuid}
                        onInput=${(e) => this.set({ uuid: e.target.value })} /></div>
                <div class="field"><label for="bc-major">${t('beacons.major')}</label>
                    <input id="bc-major" data-testid="bc-major" type="number" min="0" max="65535" step="1" inputmode="numeric"
                        disabled=${!adding} value=${d.major} onInput=${(e) => this.set({ major: e.target.value })} /></div>
                <div class="field"><label for="bc-minor">${t('beacons.minor')}</label>
                    <input id="bc-minor" data-testid="bc-minor" type="number" min="0" max="65535" step="1" inputmode="numeric"
                        disabled=${!adding} value=${d.minor} onInput=${(e) => this.set({ minor: e.target.value })} /></div>
                <div class="field"><label for="bc-room">${t('beacons.room')}</label>
                    <input id="bc-room" data-testid="bc-room" maxlength="48" autocomplete="off" value=${d.room}
                        onInput=${(e) => this.set({ room: e.target.value })} /></div>
                <div class="field"><label for="bc-zone">${t('beacons.zone')}</label>
                    <input id="bc-zone" data-testid="bc-zone" maxlength="48" autocomplete="off" value=${d.zone}
                        onInput=${(e) => this.set({ zone: e.target.value })} /></div>
                ${count > 1 && html`<div class="field"><label for="bc-level">${t('beacons.level')}</label>
                    <select id="bc-level" data-testid="bc-level" value=${d.level}
                        onChange=${(e) => this.set({ level: Number(e.target.value), x: null, y: null })}>
                        ${Array.from({ length: count }, (_, lv) => html`<option value=${lv} selected=${lv === d.level}>${
                            levelName(levels, lv)}</option>`)}
                    </select></div>`}
            </div>
            <p class="small" data-testid="bc-place-state">${typeof d.x === 'number' ? t('beacons.placed') : t('beacons.not_placed')}</p>
            <div class="actions">
                <button type="button" data-testid="bc-place" aria-pressed=${d.placing ? 'true' : 'false'}
                    onClick=${() => this.set({ placing: !d.placing })}>${t('features.place')}</button>
            </div>
            ${d.placing && this.renderPlacing()}
            ${this.state.error && html`<p class="error" role="alert" data-testid="bc-error">${this.state.error}</p>`}
            <div class="actions">
                <button type="submit" class="primary" data-testid="bc-save">${t('common.save')}</button>
                <button type="button" data-testid="bc-cancel" onClick=${() => this.props.onDraft(null)}>${t('common.cancel')}</button>
            </div>
        </form>`;
    }

    render(props) {
        const { canEdit, draft, beacons, level } = props;
        return html`<section class="card mf" aria-labelledby="bc-h" data-testid="beacons">
            <h2 id="bc-h">${t('beacons.title')}</h2>
            <p class="muted small">${t('beacons.intro')}</p>
            ${this.renderList()}
            ${canEdit && !draft && html`<div class="actions">
                <button type="button" class="primary" data-testid="bc-add"
                    onClick=${() => { this.setState({ error: '', across: '', down: '' }); props.onDraft(newBeaconDraft(level, beacons)); }}>${
                    t('beacons.add')}</button>
            </div>`}
            ${canEdit && draft && this.renderForm()}
            ${canEdit && this.props.boxStatus && this.renderBoxes()}
        </section>`;
    }
}
