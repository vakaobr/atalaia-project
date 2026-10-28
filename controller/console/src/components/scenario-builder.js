// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Scenario builder (plan phase 8; ADR-P4-6 as amended, decisions P4-1, P4R8): a YAML editor
// for a scenario manifest. The controller checks it as it is typed (POST /api/v1/scenarios/check:
// the validator's problems, each with its place in the manifest, then the generated field.lua's
// load in the core) and the GM installs it (POST /api/v1/scenarios), which compiles it into a
// scenario package. The editor lists the boxes the scenario names: the GM gives those names to
// boxes in the Join tab. A game of it is the scenario with the objectives package ticked
// (Game tab). The read token checks and lists, and cannot install or read a manifest (it holds
// the codes). Phase 5 plan phase 7 adds a block view of the same manifest (scenario-block-view.js,
// decisions P5F-*): the blocks write the YAML, which stays the builder's text.

import { html, Component, t, api, ApiError, lang, modeText } from '../ui.js';
import { ScenarioBlocks } from './scenario-block-view.js';
import { GlyphWarning } from './box-glyphs.js';
import { manifestToState, NEW_MANIFEST, toYaml } from './scenario-blocks.js';

const CHECK_DELAY_MS = 600;
const DRAFT_KEY = 'atalaia.scenario.draft';
const VIEW_KEY = 'atalaia.scenario.view';

/** A two-objective example: the bridge for any team, then a vault that only red sees. */
export const EXAMPLE = `# A scenario: boxes named by the GM in the Join tab, and objectives.
id: org.club.bridge-and-vault
version: 1
name: Bridge and vault
lang: pt
teams: [red, blue]
i18n: { pt: { name: Ponte e cofre } }
nodes:
  bridge: { role: objective }
  vault: { role: objective }
objectives:
  - id: bridge
    name: Take the bridge
    i18n: { pt: { name: Tomar a ponte } }
    type: capture_and_hold
    target: bridge
    params: { hold_ms: 3000 }
    effect: { points: 50 }
  - id: vault
    name: Open the vault
    i18n: { pt: { name: Abrir o cofre } }
    type: enter_code
    assignee: { team: red }
    target: vault
    params: { code: "4711" }
    visibility: hidden
    depends_on: [bridge]
    effect: { points: 100 }
`;

function loadDraft() {
    try {
        return window.localStorage.getItem(DRAFT_KEY) || '';
    } catch (e) {
        return '';
    }
}

function saveDraft(text) {
    try {
        window.localStorage.setItem(DRAFT_KEY, text);
    } catch (e) {
        /* a private window: the draft is not kept */
    }
}

/** The view the GM used last in this browser: 'yaml' or 'blocks'. */
function savedView() {
    try {
        return window.localStorage.getItem(VIEW_KEY) === 'blocks' ? 'blocks' : 'yaml';
    } catch (e) {
        return 'yaml';
    }
}

function saveView(view) {
    try {
        window.localStorage.setItem(VIEW_KEY, view);
    } catch (e) {
        /* not remembered */
    }
}

/** A text of the scenario or an objective in the console's language (i18n.pt, else English). */
function named(entry) {
    if (!entry) return '';
    const tr = entry.i18n && entry.i18n[lang()];
    return (tr && tr.name) || entry.name || entry.id || '';
}

export class ScenarioBuilder extends Component {
    constructor() {
        super();
        this.state = { text: loadDraft(), result: null, checking: false, list: [], done: null, view: 'yaml',
            blocks: null, blocksKey: 0, blocksError: null, local: [] };
        this.timer = null;
        this.asked = 0;
        this.blockView = null;
    }

    async componentDidMount() {
        this.loadList();
        if (savedView() === 'blocks') await this.showBlocks();
        else if (this.state.text) this.check();
    }

    componentWillUnmount() {
        clearTimeout(this.timer);
    }

    async loadList() {
        const list = await this.props.app.call('GET', '/scenarios');
        if (list) this.setState({ list });
    }

    edit(text) {
        this.setState({ text, done: null });
        saveDraft(text);
        clearTimeout(this.timer);
        this.timer = setTimeout(() => this.check(), CHECK_DELAY_MS);
    }

    /** Checks text (the editor's, by default: setState is applied later, so a caller that
     * just changed it passes the new text). */
    async check(text = this.state.text) {
        clearTimeout(this.timer);
        if (!text.trim()) {
            this.setState({ result: null });
            return;
        }
        this.asked += 1;
        const mine = this.asked;
        this.setState({ checking: true });
        const result = await this.props.app.call('POST', '/scenarios/check', { manifest: text });
        if (mine !== this.asked) return result; // an older answer than the latest text
        this.setState({ checking: false, result: result || this.state.result });
        return result;
    }

    // ---- the block view (plan phase 7) ----

    /** The block view of the editor's text: the controller reads the YAML (check), the blocks are
     * made from what it read; a text the blocks cannot show stays in the YAML view, with why. */
    async showBlocks(text = this.state.text) {
        saveView('blocks');
        if (!text.trim()) {
            this.edit(toYaml(NEW_MANIFEST));
            this.openBlocks(NEW_MANIFEST);
            return;
        }
        const result = await this.check(text);
        if (!result) {
            this.setState({ view: 'yaml', blocksError: t('scenario_blocks.no_controller') });
        } else if (!result.manifest) {
            this.setState({ view: 'yaml', blocksError: t('scenario_blocks.cannot_read') });
        } else {
            this.openBlocks(result.manifest);
        }
    }

    openBlocks(manifest) {
        const { state, lost } = manifestToState(manifest);
        if (lost.length) {
            this.setState({ view: 'yaml', blocksError: t('scenario_blocks.lost', { paths: lost.join(', ') }) });
            return;
        }
        // A new store per manifest: the view that goes away keeps its blocks in its own store.
        this.setState({ view: 'blocks', blocks: { state }, blocksKey: this.state.blocksKey + 1, blocksError: null,
            local: [] });
    }

    showYaml() {
        saveView('yaml');
        this.setState({ view: 'yaml', blocksError: null, local: [] });
    }

    /** A text the GM chose (the example, an installed scenario): in the block view, as blocks. */
    async load(text) {
        this.edit(text);
        if (this.state.view === 'blocks') await this.showBlocks(text);
        else this.check(text);
    }

    blocksChanged(yaml, local) {
        this.setState({ local });
        if (yaml !== this.state.text) this.edit(yaml);
    }

    async install() {
        const app = this.props.app;
        try {
            const done = await api(app.token, 'POST', '/scenarios', { manifest: this.state.text });
            this.setState({ done });
            this.loadList();
            app.loadCatalogue();
        } catch (e) {
            if (e instanceof ApiError && e.body && Array.isArray(e.body.problems)) {
                this.setState({ result: { ...(this.state.result || {}), ok: false, problems: e.body.problems } });
            } else {
                app.showToast(e.message);
            }
        }
    }

    async open(id) {
        const got = await this.props.app.call('GET', `/scenarios/${encodeURIComponent(id)}`);
        if (got && typeof got.manifest_text === 'string') this.load(got.manifest_text);
    }

    renderList() {
        const gm = this.props.app.state.role === 'gm';
        const { list } = this.state;
        return html`<section class="card" aria-labelledby="scn-list-h">
            <h2 id="scn-list-h">${t('scenario.installed')}</h2>
            ${list.length === 0 ? html`<p class="muted" data-testid="scenario-none">${t('scenario.none')}</p>` : html`
            <table class="table" data-testid="scenario-list">
                <thead><tr><th>${t('scenario.name')}</th><th>${t('scenario.version')}</th>
                    <th>${t('scenario.objectives')}</th><th></th></tr></thead>
                <tbody>${list.map((s) => html`<tr data-scenario=${s.id}>
                    <td><strong>${modeText(s, 'name') || s.id}</strong><br /><span class="muted small">${s.id}</span></td>
                    <td>${s.version}</td>
                    <td>${(s.objectives || []).map((o) => named(o)).join(', ')}</td>
                    <td>${gm && s.manifest && html`<button type="button" class="link"
                        onClick=${() => this.open(s.id)}>${t('scenario.open')}</button>`}</td>
                </tr>`)}</tbody>
            </table>`}
            <p class="muted small">${t('scenario.game_hint')}</p>
        </section>`;
    }

    /** A button that shows a problem's block, in the block view. */
    showButton(p) {
        if (this.state.view !== 'blocks') return null;
        return html`${' '}<button type="button" class="link" data-testid="scenario-show"
            onClick=${() => this.blockView && this.blockView.show(p)}>${t('scenario_blocks.show')}</button>`;
    }

    renderLocal() {
        const local = this.state.view === 'blocks' ? this.state.local : [];
        if (local.length === 0) return null;
        return html`<ul class="problems" data-testid="scenario-block-problems" aria-live="polite">
            ${local.map((p) => html`<li class=${`problem problem-${p.level}`} data-code=${p.code}>
                <span class=${p.level === 'error' ? 'error' : 'warn'}>${t(`scenario.levels.${p.level}`)}</span>
                ${' '}${p.path && html`<code>${p.path}</code>${' '}`}${t(`scenario_blocks.problems.${p.code}`)}
                ${this.showButton(p)}</li>`)}
        </ul>`;
    }

    renderProblems(r) {
        if (!r) return null;
        const problems = r.problems || [];
        return html`<div data-testid="scenario-problems" aria-live="polite">
            ${r.ok && problems.length === 0 && html`<p class="ok" role="status" data-testid="scenario-ok">${
                t(r.checked_in_core === false ? 'scenario.ok_no_core' : 'scenario.ok')}</p>`}
            ${r.ok && problems.length > 0 && html`<p class="ok" role="status" data-testid="scenario-ok">${t('scenario.ok_warnings')}</p>`}
            ${!r.ok && html`<p class="error" role="alert">${t('scenario.has_errors', { n: problems.filter((p) => p.level === 'error').length })}</p>`}
            ${problems.length > 0 && html`<ul class="problems">
                ${problems.map((p) => html`<li class=${`problem problem-${p.level}`} data-code=${p.code}>
                    <span class=${p.level === 'error' ? 'error' : 'warn'}>${t(`scenario.levels.${p.level}`)}</span>
                    ${' '}<code>${p.path || t('scenario.whole')}</code>${' '}${p.message}
                    ${' '}<span class="muted small">(${p.code})</span>${this.showButton(p)}</li>`)}
            </ul>`}
        </div>`;
    }

    /** The scenario's and its objectives' names (also the Portuguese ones) a box may show, for the glyph warning. */
    shownNames(r) {
        const out = [];
        const pt = (o) => (o && o.i18n && o.i18n.pt && o.i18n.pt.name) || '';
        const m = r.manifest || {};
        out.push(r.name, pt(m));
        const list = Array.isArray(m.objectives) ? m.objectives : [];
        for (const o of r.objectives || []) out.push(o.name);
        for (const o of list) if (o && typeof o === 'object') out.push(pt(o));
        return out.filter((x) => typeof x === 'string' && x);
    }

    renderNames(r) {
        if (!r || !r.nodes || r.nodes.length === 0) return null;
        const boxes = r.nodes.filter((n) => !n.player);
        const players = r.nodes.filter((n) => n.player);
        return html`<div class="scenario-names" data-testid="scenario-nodes">
            <h3>${t('scenario.nodes_title')}</h3>
            <p class="muted small">${t('scenario.nodes_hint')}</p>
            <ul>${boxes.map((n) => html`<li><code>${n.name}</code> · ${t(`scenario.roles.${n.role}`) || n.role}${
                Number.isInteger(n.level) ? ` · ${t('scenario.node_level', { n: n.level })}` : ''}</li>`)}
                ${players.map((n) => html`<li><code>${n.name}</code> · ${t('scenario.player_node', { role: n.role })}</li>`)}</ul>
            ${r.objectives && r.objectives.length > 0 && html`<h3>${t('scenario.objectives')}</h3>
                <ol>${r.objectives.map((o) => html`<li><code>${o.id}</code> · ${o.name || ''} · ${o.type}</li>`)}</ol>`}
        </div>`;
    }

    renderBlocks(state) {
        return html`<p class="muted small">${t('scenario_blocks.intro')}</p>
            <p id="scn-blocks-help" class="muted small">${t('scenario_blocks.keyboard')}</p>
            <${ScenarioBlocks} key=${`${lang()}-${state.blocksKey}`} store=${state.blocks}
                problems=${(state.result && state.result.problems) || []}
                ref=${(c) => { this.blockView = c; }}
                onChange=${(yaml, local) => this.blocksChanged(yaml, local)}
                onLocal=${(local) => this.setState({ local })}
                onError=${(e) => this.setState({ view: 'yaml', blocksError: t('scenario_blocks.load_failed',
                    { error: e.message }) })} />`;
    }

    render(props, state) {
        const gm = props.app.state.role === 'gm';
        const r = state.result;
        const d = state.done;
        const blocks = state.view === 'blocks' && state.blocks;
        const localErrors = blocks && state.local.some((p) => p.level === 'error');
        return html`<div>
            ${this.renderList()}
            <section class="card" aria-labelledby="scn-edit-h">
                <h2 id="scn-edit-h">${t('scenario.title')}</h2>
                <p class="muted">${t('scenario.intro')}</p>
                <div class="scenario-views" role="group" aria-label=${t('scenario_blocks.view')}>
                    <button type="button" data-testid="scenario-view-yaml" aria-pressed=${blocks ? 'false' : 'true'}
                        onClick=${() => this.showYaml()}>${t('scenario_blocks.view_yaml')}</button>
                    <button type="button" data-testid="scenario-view-blocks" aria-pressed=${blocks ? 'true' : 'false'}
                        onClick=${() => !blocks && this.showBlocks()}>${t('scenario_blocks.view_blocks')}</button>
                </div>
                ${state.blocksError && html`<p class="error" role="alert" data-testid="scenario-blocks-error">${
                    state.blocksError}</p>`}
                ${blocks ? this.renderBlocks(state) : html`<label for="scn-text">${t('scenario.text')}</label>
                <textarea id="scn-text" class="scenario-editor" data-testid="scenario-text" rows="22"
                    spellcheck="false" autocapitalize="off" autocomplete="off" value=${state.text}
                    onInput=${(e) => this.edit(e.target.value)}></textarea>`}
                <div class="actions">
                    <button type="button" data-testid="scenario-example"
                        onClick=${() => this.load(EXAMPLE)}>${t('scenario.example')}</button>
                    <button type="button" data-testid="scenario-check" onClick=${() => this.check()}
                        disabled=${!state.text.trim()}>${t('scenario.check')}</button>
                    ${gm && html`<button type="button" class="primary" data-testid="scenario-install"
                        disabled=${!r || !r.ok || localErrors} onClick=${() => this.install()}>${t('scenario.install')}</button>`}
                    ${state.checking && html`<span class="muted small">${t('scenario.checking')}</span>`}
                </div>
                ${!gm && html`<p class="muted small">${t('scenario.read_only')}</p>`}
                ${d && html`<p class="ok" role="status" data-testid="scenario-installed">${t(d.replaced
                    ? 'scenario.replaced' : 'scenario.installed_done', { name: named(d), version: d.version })}</p>`}
                ${this.renderLocal()}
                ${this.renderProblems(r)}
                ${r && html`<${GlyphWarning} text=${this.shownNames(r)} testid="glyph-scenario" />`}
                ${this.renderNames(r)}
            </section>
        </div>`;
    }
}
