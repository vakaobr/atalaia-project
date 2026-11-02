// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The controller's wall clock (controller/atalaia_controller/wallclock.py, decisions CLK-*). A Raspberry Pi 4
// has no real-time clock, so after a power cycle in a field with no internet its clock is wrong; the controller
// says so (status.clock.ok false) and this banner offers, to the game master only, to set it from this device,
// whose clock is right. The controller moves forward only, never below what it has seen and never absurdly
// far, and says why when it refuses. Only the Pi controller has it (a phone's clock is the network's).

import { html, Component, t } from '../ui.js';

function stamp(seconds) {
    return new Date(seconds * 1000).toLocaleString();
}

export async function setFromDevice(app) {
    const out = await app.call('PUT', '/clock', { epoch: Date.now() / 1000 });
    if (out) {
        await app.refreshStatus();
        app.showToast(t('clock.set_done', { time: stamp(out.now) }));
    }
    return out;
}

/** Under the header, while the controller's clock is wrong. */
export function ClockBanner({ app }) {
    const clock = app.state.status && app.state.status.clock;
    if (!clock || clock.ok) return null;
    const gm = app.state.role === 'gm';
    return html`<div class="banner clock-banner" role="alert" data-testid="clock-wrong">
        <strong>${t('clock.wrong')}</strong>
        ${' '}${t(`clock.reason_${clock.reason}`, { now: stamp(clock.now), floor: stamp(clock.floor) })}
        ${' '}${gm ? t('clock.hint_gm') : t('clock.hint_read')}
        ${gm && html`${' '}<button type="button" data-testid="clock-set" onClick=${() => setFromDevice(app)}>${t('clock.set')}</button>`}
    </div>`;
}

/** Settings: the controller's time and this device's, and the same button. */
export class ClockSettings extends Component {
    componentDidMount() {
        this.timer = setInterval(() => this.forceUpdate(), 1000);
    }

    componentWillUnmount() {
        clearInterval(this.timer);
    }

    render(props) {
        const app = props.app;
        const clock = app.state.status && app.state.status.clock;
        if (!clock) return null;
        const gm = app.state.role === 'gm';
        if (this.last !== clock) {  // a new status: the controller's time as of now, ticking from here
            this.last = clock;
            this.at = Date.now();
        }
        const live = clock.now + (Date.now() - this.at) / 1000;
        return html`<section class="card" aria-labelledby="clock-h" data-testid="clock-settings">
            <h2 id="clock-h">${t('clock.title')}</h2>
            <p class="muted small">${t('clock.intro')}</p>
            <p>${t('clock.controller_time')}: <strong data-testid="clock-controller">${stamp(live)}</strong>${clock.ok ? '' : html` <span class="warn">${t('clock.wrong_short')}</span>`}</p>
            <p>${t('clock.device_time')}: <strong data-testid="clock-device">${stamp(Date.now() / 1000)}</strong></p>
            ${clock.last_jump && html`<p class="muted small" data-testid="clock-jump">${t('clock.jump', { seconds: Math.round(clock.last_jump.seconds), time: stamp(clock.last_jump.at) })}</p>`}
            ${gm ? html`<button type="button" data-testid="clock-set-settings" onClick=${() => setFromDevice(app)}>${t('clock.set')}</button>
                <p class="muted small">${t('clock.forward_only')}</p>`
                : html`<p class="muted">${t('clock.read_only')}</p>`}
        </section>`;
    }
}
