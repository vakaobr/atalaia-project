// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The mode editor's page (phase 5 plan phase A, ADR-P5-1 and P5-2 as amended 2026-10-22): two
// Blockly workspaces, one for the boxes' script (node.lua) and one for the field controller's
// (field.lua), the Mode tab's form for the rest of mode.yaml, and the generated files beside
// them, regenerated on every change, with the problems found. Blocks are saved as one JSON file
// (format "atalaia-mode-editor"); the last state is kept in this browser as a draft. The page
// works offline: Blockly is vendored and nothing is fetched from elsewhere. "Test in the
// simulator" (plan phase 2) sends the generated files to the simulator's POST /api/reload, which
// makes them the game its web view shows (in another tab, "atalaia-sim"); the errors the
// scripts hit there, on loading or while the game runs, come back to the problems list and to
// the blocks they come from.
/* global Blockly, lua */

import { defineBlocks, luaName, toolbox } from './blocks.js';
import { defaultInfo, generateProject, generateWorkspaces, LICENCES, lineBlocks, makeGenerator } from './generator.js';

const LANGS = ['pt', 'en'];
const LANG_KEY = 'atalaia.editor.lang';
const DRAFT_KEY = 'atalaia.editor.draft';
export const FORMAT = 'atalaia-mode-editor';
const FILE_NAMES = { node_lua: 'node.lua', field_lua: 'field.lua', mode_yaml: 'mode.yaml' };
/** How often the editor asks the simulator for script errors while its mode runs there. */
const TEST_POLL_MS = 1000;
/** The id of the warnings the editor puts on blocks for the simulator's errors. */
const SIM_WARNING = 'atalaia-sim';

function storageGet(key) {
    try {
        return window.localStorage.getItem(key);
    } catch (e) {
        return null;
    }
}

function storageSet(key, value) {
    try {
        window.localStorage.setItem(key, value);
    } catch (e) {
        // private mode or storage off: the draft is only a convenience
    }
}

/** ?lang=, then the remembered language, then the browser's (Portuguese or English). */
function pickLanguage() {
    const asked = new URLSearchParams(window.location.search).get('lang');
    if (LANGS.includes(asked)) return asked;
    const kept = storageGet(LANG_KEY);
    if (LANGS.includes(kept)) return kept;
    const browser = (navigator.languages || [navigator.language || 'en']).map((l) => String(l).toLowerCase());
    return browser.find((l) => l.startsWith('pt') || l.startsWith('en'))?.startsWith('pt') ? 'pt' : 'en';
}

function loadScript(src) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = resolve;
        script.onerror = () => reject(new Error(`${src} did not load`));
        document.head.appendChild(script);
    });
}

async function fetchJson(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: ${response.status}`);
    return response.json();
}

function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A dark workspace when the system is dark, like the rest of the page. */
function theme() {
    if (!window.matchMedia || !window.matchMedia('(prefers-color-scheme: dark)').matches) return Blockly.Themes.Classic;
    return Blockly.Theme.defineTheme('atalaia-dark', {
        name: 'atalaia-dark',
        base: Blockly.Themes.Classic,
        componentStyles: {
            workspaceBackgroundColour: '#15181d',
            toolboxBackgroundColour: '#1f232a',
            toolboxForegroundColour: '#e6e8eb',
            flyoutBackgroundColour: '#22262e',
            flyoutForegroundColour: '#e6e8eb',
            flyoutOpacity: 1,
            scrollbarColour: '#555b66',
            insertionMarkerColour: '#ffffff',
            insertionMarkerOpacity: 0.3,
            cursorColour: '#d0d0d0',
        },
    });
}

async function main() {
    const lang = pickLanguage();
    storageSet(LANG_KEY, lang);
    document.documentElement.lang = lang === 'pt' ? 'pt-PT' : 'en';
    if (lang !== 'en') await loadScript(`vendor/blockly/msg/${lang}.js`);
    const en = await fetchJson('i18n/en.json');
    const dict = lang === 'en' ? en : await fetchJson(`i18n/${lang}.json`);
    const t = (key) => dict.blocks[key] ?? en.blocks[key] ?? key;
    const ui = (key) => dict.ui[key] ?? en.ui[key] ?? key;
    // ADR-P5-1, rule 4: no "Describe this function..." placeholder on new functions.
    Blockly.Msg.PROCEDURES_DEFNORETURN_COMMENT = '';
    Blockly.Msg.PROCEDURES_DEFRETURN_COMMENT = '';

    document.title = ui('title');
    for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = ui(el.dataset.i18n);
    const langSelect = document.getElementById('lang');
    langSelect.value = lang;
    langSelect.addEventListener('change', () => {
        storageSet(LANG_KEY, langSelect.value);
        saveDraft();
        const url = new URL(window.location.href);
        url.searchParams.set('lang', langSelect.value);
        window.location.assign(url.toString());
    });

    defineBlocks(Blockly, t);
    const g = makeGenerator(lua);
    const options = (kind) => ({
        toolbox: toolbox(kind, t),
        media: 'vendor/blockly/media/',
        renderer: 'thrasos',
        theme: theme(),
        sounds: false,
        trashcan: true,
        move: { scrollbars: true, drag: true, wheel: false },
        zoom: { controls: true, wheel: true, startScale: 0.85 },
        grid: { spacing: 24, length: 2, colour: '#8888', snap: true },
    });
    const workspaces = { node: Blockly.inject('ws-node', options('node')), field: Blockly.inject('ws-field', options('field')) };

    // ---- the Mode tab ----
    const form = document.getElementById('mode-form');
    const licence = form.elements.license;
    for (const id of LICENCES) licence.add(new Option(id, id));
    let info = defaultInfo();
    const showInfo = () => {
        for (const [key, value] of Object.entries(info)) if (form.elements[key]) form.elements[key].value = value;
    };
    form.addEventListener('input', () => {
        for (const el of form.elements) if (el.name) info[el.name] = el.value;
        changed();
    });
    form.addEventListener('submit', (e) => e.preventDefault());

    // ---- tabs ----
    let activeFile = 'node_lua';
    const selectTab = (tab) => {
        for (const button of document.querySelectorAll('[data-tab]')) button.setAttribute('aria-selected', String(button.dataset.tab === tab));
        document.getElementById('ws-node').classList.toggle('active', tab === 'node');
        document.getElementById('ws-field').classList.toggle('active', tab === 'field');
        form.classList.toggle('active', tab === 'mode');
        if (workspaces[tab]) Blockly.svgResize(workspaces[tab]);
        if (tab === 'node' || tab === 'field') selectFile(tab === 'node' ? 'node_lua' : 'field_lua');
        if (tab === 'mode') selectFile('mode_yaml');
    };
    for (const button of document.querySelectorAll('[data-tab]')) button.addEventListener('click', () => selectTab(button.dataset.tab));
    const selectFile = (file) => {
        activeFile = file;
        for (const button of document.querySelectorAll('[data-file]')) button.setAttribute('aria-selected', String(button.dataset.file === file));
        show();
    };
    for (const button of document.querySelectorAll('[data-file]')) button.addEventListener('click', () => selectFile(button.dataset.file));

    // ---- generating ----
    let files = { node_lua: '', field_lua: '', mode_yaml: '', problems: [] };
    const code = document.getElementById('code');
    const problemList = document.getElementById('problems');
    function show() {
        code.textContent = files[activeFile];
        document.getElementById('no-field').hidden = !(activeFile === 'field_lua' && !files.field_lua);
        document.getElementById('download').disabled = !files[activeFile];
        const problems = [...files.problems, ...simProblems];
        problemList.replaceChildren(...problems.map((p) => {
            const li = document.createElement('li');
            li.textContent = t(p.key).replace('{name}', p.name || '');
            li.dataset.key = p.key;
            if (p.key === 'problem_sim') li.classList.add('sim');
            if (p.block) {
                li.addEventListener('click', () => {
                    const kind = p.script || (workspaces.field.getBlockById(p.block) ? 'field' : 'node');
                    selectTab(kind);
                    const block = workspaces[kind].getBlockById(p.block);
                    if (block) {
                        workspaces[kind].centerOnBlock(block.id);
                        Blockly.common.setSelected(block);
                    }
                });
            }
            return li;
        }));
        document.getElementById('no-problems').hidden = problems.length > 0;
    }
    function regenerate() {
        files = generateWorkspaces(g, info, workspaces.node, workspaces.field);
        // The simulator's errors are about the files it got: once they change, they are gone.
        if (tested && Object.keys(FILE_NAMES).some((f) => files[f] !== tested.files[f])) stopTest();
        show();
    }

    // ---- testing in the simulator ----
    let simProblems = [];
    let tested = null; // { files, maps, reloads, since, timer } of the mode the simulator runs
    const testStatus = document.getElementById('test-status');
    const testBoxes = document.getElementById('test-boxes');
    const setStatus = (key, values = {}, bad = false) => {
        let text = ui(key);
        for (const [k, v] of Object.entries(values)) text = text.replace(`{${k}}`, String(v));
        document.getElementById('test-message').textContent = text;
        document.getElementById('test-open').hidden = bad;
        testStatus.classList.toggle('bad', bad);
        testStatus.hidden = false;
    };
    /** The simulator's errors as problems, on their blocks where the line says which. */
    function showSimErrors(errors) {
        for (const p of simProblems) setWarning(p, null);
        // One problem per message, naming the boxes that hit it (every box runs the same script).
        const byMessage = new Map();
        for (const err of errors) {
            const script = err.script === 'node' || err.script === 'field' ? err.script : null;
            const map = script && tested ? tested.maps[script] : null;
            const block = map && err.line ? map[err.line - 1] || null : null;
            const p = byMessage.get(err.message) || { key: 'problem_sim', block, script, message: err.message, nodes: [] };
            if (err.node && err.node !== 'controller' && !p.nodes.includes(err.node)) p.nodes.push(err.node);
            byMessage.set(err.message, p);
        }
        simProblems = [...byMessage.values()].map((p) => ({ ...p, name: (p.nodes.length ? p.nodes.join(', ') + ': ' : '') + p.message }));
        for (const p of simProblems) setWarning(p, p.message);
        show();
    }
    function setWarning(p, text) {
        const block = p.block && p.script ? workspaces[p.script].getBlockById(p.block) : null;
        if (block) block.setWarningText(text, SIM_WARNING);
    }
    function stopTest() {
        if (tested) clearTimeout(tested.timer);
        tested = null;
        for (const p of simProblems) setWarning(p, null);
        simProblems = [];
        testStatus.hidden = true;
    }
    async function pollTest() {
        const current = tested;
        if (!current) return;
        try {
            const response = await fetch(`/api/state?since=${current.since}`, { cache: 'no-store' });
            const state = await response.json();
            if (tested !== current) return;
            if (state.reloads !== current.reloads) return stopTest(); // another reload replaced it
            current.since = state.events_from + state.events.length;
            const seen = JSON.stringify(state.script_errors);
            if (seen !== current.errors) {
                current.errors = seen;
                showSimErrors(state.script_errors);
                if (state.script_errors.length) setStatus('test_running_errors', { name: state.mode.name });
            }
        } catch (e) {
            // the simulator was stopped: keep what was shown, try again later
        }
        if (tested === current) current.timer = setTimeout(pollTest, TEST_POLL_MS);
    }
    async function test() {
        clearTimeout(timer);
        regenerate();
        stopTest();
        const count = Math.min(16, Math.max(1, Math.round(Number(testBoxes.value)) || 1));
        const role = (luaName(info.role) || 'zone').slice(0, 20);
        const nodes = {};
        for (let i = 1; i <= count; i++) nodes[`${role}${i}`] = role;
        const sent = { ...files };
        const maps = {
            node: sent.node_lua ? lineBlocks(g, workspaces.node, 'node', info, sent.node_lua) : null,
            field: sent.field_lua ? lineBlocks(g, workspaces.field, 'field', info, sent.field_lua) : null,
        };
        setStatus('test_sending');
        let answer;
        try {
            const response = await fetch('/api/reload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode_yaml: sent.mode_yaml, node_lua: sent.node_lua, field_lua: sent.field_lua || null, nodes }),
            });
            answer = await response.json();
            if (!response.ok) throw new Error(answer.error || String(response.status));
        } catch (err) {
            return setStatus('test_offline', { error: err.message }, true);
        }
        // Kept until the files change; followed (polled) only when the simulator took the mode.
        tested = { files: sent, maps, reloads: answer.reloads, since: 0, timer: null, errors: JSON.stringify(answer.errors) };
        showSimErrors(answer.errors);
        if (answer.status !== 'ok') return setStatus('test_failed', {}, true);
        setStatus(answer.errors.length ? 'test_running_errors' : 'test_running', { name: answer.mode.name, boxes: answer.nodes.length });
        tested.timer = setTimeout(pollTest, TEST_POLL_MS);
    }
    document.getElementById('test').addEventListener('click', () => test());
    function project() {
        return {
            format: FORMAT,
            version: 1,
            mode: { ...info },
            node: Blockly.serialization.workspaces.save(workspaces.node),
            field: Blockly.serialization.workspaces.save(workspaces.field),
        };
    }
    function saveDraft() {
        storageSet(DRAFT_KEY, JSON.stringify(project()));
    }
    let timer = null;
    function changed() {
        clearTimeout(timer);
        timer = setTimeout(() => {
            regenerate();
            saveDraft();
        }, 150);
    }
    for (const ws of Object.values(workspaces)) {
        ws.addChangeListener((event) => {
            if (!event.isUiEvent) changed();
        });
    }
    function load(p) {
        if (!p || p.format !== FORMAT || typeof p.version !== 'number') throw new Error(ui('bad_file'));
        info = { ...defaultInfo(), ...(p.mode || {}) };
        showInfo();
        for (const kind of ['node', 'field']) {
            workspaces[kind].clear();
            if (p[kind]) Blockly.serialization.workspaces.load(p[kind], workspaces[kind]);
        }
        regenerate();
        saveDraft();
    }
    const isEmpty = () => workspaces.node.getAllBlocks(false).length + workspaces.field.getAllBlocks(false).length === 0;
    const mayReplace = () => isEmpty() || window.confirm(ui('replace'));

    // ---- toolbar ----
    document.getElementById('new').addEventListener('click', () => {
        if (mayReplace()) load({ format: FORMAT, version: 1, mode: defaultInfo() });
    });
    document.getElementById('save').addEventListener('click', () => {
        download(`${info.id || 'mode'}.blocks.json`, JSON.stringify(project(), null, 2) + '\n', 'application/json');
    });
    document.getElementById('open-file').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        e.target.value = '';
        if (!file || !mayReplace()) return;
        try {
            load(JSON.parse(await file.text()));
        } catch (err) {
            window.alert(ui('bad_file'));
        }
    });
    const example = document.getElementById('example');
    example.addEventListener('change', async () => {
        const name = example.value;
        example.value = '';
        if (name && mayReplace()) load(await fetchJson(`examples/${name}.json`));
    });
    document.getElementById('download').addEventListener('click', () => {
        download(FILE_NAMES[activeFile], files[activeFile], 'text/plain');
    });

    // The draft from the last visit, else an empty mode.
    let draft = null;
    try {
        draft = JSON.parse(storageGet(DRAFT_KEY) || 'null');
    } catch (e) {
        draft = null;
    }
    try {
        load(draft && draft.format === FORMAT ? draft : { format: FORMAT, version: 1, mode: defaultInfo() });
    } catch (e) {
        load({ format: FORMAT, version: 1, mode: defaultInfo() });
    }

    // For the browser tests (simulator/editor_tests/) and for the curious: the same generator
    // on a saved project, without touching the page's workspaces.
    window.atalaiaEditor = {
        generate: (p) => generateProject(Blockly, g, p),
        load,
        project,
        files: () => files,
        selectTab,
        test,
        lineBlocks: (kind) => lineBlocks(g, workspaces[kind], kind, info, files[`${kind}_lua`]),
        blockType: (kind, id) => workspaces[kind].getBlockById(id)?.type ?? null,
    };
    document.body.dataset.ready = 'true';
}

main().catch((err) => {
    document.body.dataset.ready = 'error';
    document.body.prepend(Object.assign(document.createElement('p'), { className: 'intro', textContent: String(err) }));
    throw err;
});
