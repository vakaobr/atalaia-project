// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Scenario blocks (phase 5 plan phase 7; ADR-P5-1 and P5-2 as amended, decisions P5R-2, P5F-*):
// the blocks of the scenario builder's block view, and the two conversions that make it a view
// of the same YAML manifest the controller checks and compiles (ADR-P4-6 as amended, M7-1):
//
//   manifestToState(manifest)  a manifest (as the controller read it) -> Blockly's JSON state,
//                              and the paths of anything blocks cannot hold (then the view
//                              refuses, and the GM fixes it in the YAML first)
//   workspaceToManifest(ws)    the blocks -> the manifest, where each value came from (a path
//                              -> block id map, for the controller's problems) and the problems
//                              only the blocks have (a rule given twice, a block in the wrong place)
//   toYaml(manifest)           the manifest as YAML text, in the style of the hand-written examples
//
// No rule of the validator is repeated here (decision M8-7): the controller checks the YAML.
// Blockly 13.3.0 is vendored in lib/blockly/ and loaded only when the block view opens.
/* global Blockly */

const BLOCKLY_DIR = new URL('../lib/blockly/', import.meta.url);
// Relative to the console's page. Blockly writes it into its stylesheet, whose SHA-256 the
// controller's Content-Security-Policy allows (decision P5F-2): keep it as it is.
export const MEDIA = 'lib/blockly/media/';
export const THEME = 'atalaia-scenario';
export const RENDERER = 'thrasos';

// ---- loading Blockly --------------------------------------------------------------------

let core = null;
let messages = null;

function loadScript(src) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = () => resolve(script);
        script.onerror = () => reject(new Error(`${src} did not load`));
        document.head.appendChild(script);
    });
}

/** Blockly with its own texts (its menus) in Portuguese, else English (the console vendors only
 * those two): the core once, the texts when lang changes. */
export async function loadBlockly(lang) {
    if (!core) {
        core = loadScript(new URL('blockly_compressed.js', BLOCKLY_DIR).href).catch((e) => {
            core = null;
            throw e;
        });
    }
    await core;
    if (!messages || messages.lang !== lang) {
        const script = await loadScript(new URL(`msg/${lang === 'pt' ? 'pt' : 'en'}.js`, BLOCKLY_DIR).href);
        script.remove(); // it has set Blockly.Msg; the next language's file sets them again
        messages = { lang };
    }
    return window.Blockly;
}

// ---- the blocks ---------------------------------------------------------------------------

export const TYPES = ['capture_and_hold', 'enter_code', 'scan_tags', 'escort', 'destroy', 'defend', 'survive'];
const VISIBILITY = ['public', 'team', 'squad', 'hidden'];
const LEVELS = 10; // a box's level on a multi-story field, 0-9 (decision ML-8)
const NO_LEVEL = 'none';

const COLOURS = {
    scenario: '#2f6b47', text: '#6b6b6b', team: '#a33b3b', param: '#7a5c99', node: '#2e6f8f',
    objective: '#b5651d', who: '#3d7d7d', how: '#5b6fb3', effect: '#8a7a14',
};

// What each statement input of a block takes (the generator checks it; Blockly's connection
// checks only look at neighbours).
const PLACES = {
    'scn_scenario.INFO': ['scn_description', 'scn_author', 'scn_name_pt', 'scn_description_pt'],
    'scn_scenario.TEAMS': ['scn_team'],
    'scn_scenario.PARAMS': ['scn_param'],
    'scn_scenario.NODES': ['scn_box', 'scn_player'],
    'scn_scenario.OBJECTIVES': ['scn_objective'],
    'scn_objective.RULES': ['scn_description', 'scn_name_pt', 'scn_description_pt', 'scn_assignee', 'scn_visibility',
        'scn_after', 'scn_opens_at', 'scn_closes_at', 'scn_hold', 'scn_duration', 'scn_code', 'scn_tags',
        'scn_defuse', 'scn_fuse', 'scn_circle', 'scn_area', 'scn_max_acc', 'scn_lives', 'scn_points',
        'scn_points_param', 'scn_win', 'scn_reveal'],
    'scn_area.CORNERS': ['scn_corner'],
};

const text = (name, value = '') => ({ type: 'field_input', name, text: value, spellcheck: false });
// precision null: any number (a latitude); 1: whole numbers; 0.001: seconds to the millisecond.
const num = (name, value = 0, precision = 1) => (precision === null ? { type: 'field_number', name, value }
    : { type: 'field_number', name, value, precision });
const check = (name) => ({ type: 'field_checkbox', name, checked: false });
const statement = (name) => ({ type: 'input_statement', name });

/** One block's JSON: messages[i] is the text of row i, with %1, %2... for that row's args. */
function def(type, colour, rows, extra = {}) {
    const out = { type, colour, ...extra };
    rows.forEach(([message, args], i) => {
        out[`message${i}`] = message;
        if (args && args.length) out[`args${i}`] = args;
    });
    return out;
}

/** The block definitions, with their texts from tr(key) (the console's scenario_blocks.blocks). */
export function blockDefinitions(tr) {
    const item = { previousStatement: null, nextStatement: null };
    const types = TYPES.map((v) => [tr(`type_${v}`), v]);
    const levels = [[tr('level_none'), NO_LEVEL], ...Array.from({ length: LEVELS }, (_, i) => [String(i), String(i)])];
    const C = COLOURS;
    return [
        def('scn_scenario', C.scenario, [
            [tr('scenario'), [text('NAME')]],
            [tr('scenario_id'), [text('ID', 'org.club.'), text('VERSION', '1')]],
            [tr('scenario_lang'), [{ type: 'field_dropdown', name: 'LANG', options: [[tr('lang_pt'), 'pt'], [tr('lang_en'), 'en']] },
                num('SQUADS', 0)]],
            [tr('scenario_texts'), [statement('INFO')]],
            [tr('scenario_teams'), [statement('TEAMS')]],
            [tr('scenario_params'), [statement('PARAMS')]],
            [tr('scenario_nodes'), [statement('NODES')]],
            [tr('scenario_objectives'), [statement('OBJECTIVES')]],
        ], { tooltip: tr('scenario_tip') }),
        def('scn_description', C.text, [[tr('description'), [text('TEXT')]]], item),
        def('scn_author', C.text, [[tr('author'), [text('TEXT')]]], item),
        def('scn_name_pt', C.text, [[tr('name_pt'), [text('TEXT')]]], item),
        def('scn_description_pt', C.text, [[tr('description_pt'), [text('TEXT')]]], item),
        def('scn_team', C.team, [[tr('team'), [text('TEAM', 'red')]]], item),
        def('scn_param', C.param, [
            [tr('param'), [text('NAME', 'points'), text('MIN'), text('MAX'), num('DEFAULT', 0)]],
            [tr('param_label'), [text('LABEL'), text('LABEL_PT')]],
            [tr('param_gm_only'), [check('GM_ONLY')]],
        ], { ...item, tooltip: tr('param_tip') }),
        def('scn_box', C.node, [[tr('box'), [text('NAME', 'alpha'),
            { type: 'field_dropdown', name: 'ROLE', options: [[tr('role_objective'), 'objective'], [tr('role_bomb_site'), 'bomb_site']] },
            { type: 'field_dropdown', name: 'LEVEL', options: levels }]]], { ...item, tooltip: tr('box_tip') }),
        def('scn_player', C.node, [[tr('player'), [text('NAME', 'vip'), text('ROLE', 'vip')]]],
            { ...item, tooltip: tr('player_tip') }),
        def('scn_objective', C.objective, [
            [tr('objective'), [text('ID', 'objective'), text('NAME')]],
            [tr('objective_type'), [{ type: 'field_dropdown', name: 'TYPE', options: types }, text('TARGET')]],
            [tr('objective_rules'), [statement('RULES')]],
        ], { ...item, tooltip: tr('objective_tip') }),
        def('scn_assignee', C.who, [[tr('assignee'), [text('TEAM', 'red'), text('SQUAD')]]], item),
        def('scn_visibility', C.who, [[tr('visibility'), [{ type: 'field_dropdown', name: 'VISIBILITY',
            options: VISIBILITY.map((v) => [tr(`visibility_${v}`), v]) }]]], item),
        def('scn_after', C.who, [[tr('after'), [text('OBJECTIVE')]]], item),
        def('scn_opens_at', C.who, [[tr('opens_at'), [num('MINUTE', 0)]]], item),
        def('scn_closes_at', C.who, [[tr('closes_at'), [num('MINUTE', 60)]]], item),
        def('scn_hold', C.how, [[tr('hold'), [num('SECONDS', 3, 0.001)]]], item),
        def('scn_duration', C.how, [[tr('duration'), [num('SECONDS', 60)]]], item),
        def('scn_code', C.how, [[tr('code'), [text('CODE', '1234')]]], item),
        def('scn_tags', C.how, [[tr('tags'), [num('COUNT', 1), check('ANY')]]], item),
        def('scn_defuse', C.how, [[tr('defuse'), [num('SECONDS', 5, 0.001)]]], item),
        def('scn_fuse', C.how, [[tr('fuse'), [num('SECONDS', 60)]]], item),
        def('scn_circle', C.how, [[tr('circle'), [num('LAT', 0, null), num('LON', 0, null), num('RADIUS', 15, null)]]], item),
        def('scn_area', C.how, [[tr('area'), [statement('CORNERS')]]], item),
        def('scn_corner', C.how, [[tr('corner'), [num('LAT', 0, null), num('LON', 0, null)]]], item),
        def('scn_max_acc', C.how, [[tr('max_acc'), [num('METRES', 25)]]], item),
        def('scn_lives', C.how, [[tr('lives'), [num('LIVES', 1)]]], item),
        def('scn_points', C.effect, [[tr('points'), [num('POINTS', 10)]]], item),
        def('scn_points_param', C.effect, [[tr('points_param'), [text('PARAM', 'points')]]], item),
        def('scn_win', C.effect, [[tr('win'), []]], item),
        def('scn_reveal', C.effect, [[tr('reveal'), [text('OBJECTIVE')]]], item),
    ];
}

/** Registers the blocks with Blockly (again after a language change: same types, new texts). */
export function defineBlocks(B, tr) {
    for (const json of blockDefinitions(tr)) {
        B.Blocks[json.type] = { init() { this.jsonInit(json); } };
    }
}

/** The toolbox: categories of the blocks to add (the scenario block itself is always there). */
export function toolbox(tr) {
    const cat = (name, colour, types) => ({ kind: 'category', name: tr(name), colour,
        contents: types.map((type) => ({ kind: 'block', type })) });
    const C = COLOURS;
    return {
        kind: 'categoryToolbox',
        contents: [
            cat('cat_objectives', C.objective, ['scn_objective']),
            cat('cat_nodes', C.node, ['scn_box', 'scn_player']),
            cat('cat_who', C.who, ['scn_assignee', 'scn_visibility', 'scn_after', 'scn_opens_at', 'scn_closes_at']),
            cat('cat_how', C.how, ['scn_hold', 'scn_duration', 'scn_code', 'scn_tags', 'scn_defuse', 'scn_fuse',
                'scn_circle', 'scn_area', 'scn_corner', 'scn_max_acc', 'scn_lives']),
            cat('cat_effects', C.effect, ['scn_points', 'scn_points_param', 'scn_win', 'scn_reveal']),
            cat('cat_texts', C.text, ['scn_description', 'scn_name_pt', 'scn_description_pt', 'scn_author']),
            cat('cat_teams', C.team, ['scn_team']),
            cat('cat_params', C.param, ['scn_param']),
        ],
    };
}

// ---- manifest -> blocks ---------------------------------------------------------------------

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isInt = (v) => Number.isInteger(v);
const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);
const isText = (v) => typeof v === 'string';

/** Blockly's JSON state of a statement input holding blocks one after the other. */
function chain(blocks) {
    if (!blocks.length) return undefined;
    for (let i = blocks.length - 2; i >= 0; i--) blocks[i].next = { block: blocks[i + 1] };
    return { block: blocks[0] };
}

function block(type, fields = {}, inputs = {}) {
    const out = { type };
    if (Object.keys(fields).length) out.fields = fields;
    const used = Object.fromEntries(Object.entries(inputs).filter(([, v]) => v));
    if (Object.keys(used).length) out.inputs = used;
    return out;
}

/** A scenario to start from: the defaults a new manifest would get. The id, the name and the
 * objectives are the GM's to give, and the controller's checks say so until they are given. */
export const NEW_MANIFEST = { id: 'org.club.', version: '1', lang: 'pt', teams: ['red', 'blue'], objectives: [] };

/**
 * The blocks of a manifest (a map as the controller read the YAML): { state, lost }. lost lists
 * the paths of what the blocks cannot hold as it is (an unknown key, a value of the wrong kind,
 * an empty value); the view refuses such a manifest rather than change it silently.
 */
export function manifestToState(m) {
    const lost = [];
    const at = (path, key) => (path ? `${path}.${key}` : key);
    const only = (obj, keys, path) => {
        for (const k of Object.keys(obj)) if (!keys.includes(k)) lost.push(at(path, k));
    };
    const textOf = (obj, key, path) => {
        if (!(key in obj)) return undefined;
        if (isText(obj[key])) return obj[key];
        lost.push(at(path, key));
        return undefined;
    };
    const intOf = (obj, key, path) => {
        if (!(key in obj)) return undefined;
        if (isInt(obj[key])) return obj[key];
        lost.push(at(path, key));
        return undefined;
    };
    if (!isObject(m)) return { state: null, lost: [''] };
    only(m, ['id', 'version', 'name', 'description', 'author', 'lang', 'teams', 'squads', 'params', 'i18n', 'nodes',
        'objectives'], '');

    const root = { ID: '', VERSION: '', NAME: '', LANG: 'pt', SQUADS: 0 };
    if ('id' in m) root.ID = textOf(m, 'id', '') ?? '';
    if ('version' in m) {
        if (isText(m.version) || isNumber(m.version)) root.VERSION = String(m.version);
        else lost.push('version');
    }
    root.NAME = textOf(m, 'name', '') ?? '';
    for (const key of ['id', 'version', 'name']) if (m[key] === '') lost.push(key); // the blocks would leave it out
    if ('lang' in m) {
        if (m.lang === 'pt' || m.lang === 'en') root.LANG = m.lang;
        else lost.push('lang');
    }
    if ('squads' in m) root.SQUADS = intOf(m, 'squads', '') ?? 0;

    const info = [];
    const description = textOf(m, 'description', '');
    if (description !== undefined) info.push(block('scn_description', { TEXT: description }));
    const author = textOf(m, 'author', '');
    if (author !== undefined) info.push(block('scn_author', { TEXT: author }));
    let labelsPt = {};
    if ('i18n' in m) {
        if (!isObject(m.i18n)) lost.push('i18n');
        else {
            only(m.i18n, ['pt'], 'i18n');
            const pt = m.i18n.pt;
            if (pt !== undefined && !isObject(pt)) lost.push('i18n.pt');
            else if (pt) {
                only(pt, ['name', 'description', 'params'], 'i18n.pt');
                const name = textOf(pt, 'name', 'i18n.pt');
                if (name !== undefined) info.push(block('scn_name_pt', { TEXT: name }));
                const desc = textOf(pt, 'description', 'i18n.pt');
                if (desc !== undefined) info.push(block('scn_description_pt', { TEXT: desc }));
                if ('params' in pt) {
                    if (isObject(pt.params)) labelsPt = { ...pt.params };
                    else lost.push('i18n.pt.params');
                }
            }
        }
    }

    const teams = [];
    if (!('teams' in m)) teams.push(...['red', 'blue'].map((t) => block('scn_team', { TEAM: t })));
    else if (!Array.isArray(m.teams)) lost.push('teams');
    else {
        m.teams.forEach((t, i) => {
            if (isText(t)) teams.push(block('scn_team', { TEAM: t }));
            else lost.push(`teams[${i}]`);
        });
    }

    const params = [];
    if ('params' in m) {
        if (!isObject(m.params)) lost.push('params');
        else {
            for (const [name, spec] of Object.entries(m.params)) {
                const path = `params.${name}`;
                if (!isObject(spec)) {
                    lost.push(path);
                    continue;
                }
                only(spec, ['type', 'min', 'max', 'default', 'label', 'gm_only'], path);
                if (spec.type !== 'int') lost.push(`${path}.type`);
                const fields = { NAME: name, MIN: '', MAX: '', DEFAULT: 0, LABEL: '', LABEL_PT: '', GM_ONLY: 'FALSE' };
                for (const [key, field] of [['min', 'MIN'], ['max', 'MAX']]) {
                    const v = intOf(spec, key, path);
                    if (v !== undefined) fields[field] = String(v);
                }
                if (!('default' in spec) || !isInt(spec.default)) lost.push(`${path}.default`);
                else fields.DEFAULT = spec.default;
                fields.LABEL = textOf(spec, 'label', path) ?? '';
                if (spec.label === '') lost.push(`${path}.label`);
                if ('gm_only' in spec) {
                    if (spec.gm_only === true) fields.GM_ONLY = 'TRUE';
                    else lost.push(`${path}.gm_only`); // false is the default: the blocks write nothing
                }
                if (name in labelsPt) {
                    if (isText(labelsPt[name]) && labelsPt[name] !== '') fields.LABEL_PT = labelsPt[name];
                    else lost.push(`i18n.pt.params.${name}`);
                    delete labelsPt[name];
                }
                params.push(block('scn_param', fields));
            }
        }
    }
    for (const name of Object.keys(labelsPt)) lost.push(`i18n.pt.params.${name}`); // a label of no parameter

    const nodes = [];
    if ('nodes' in m) {
        if (!isObject(m.nodes)) lost.push('nodes');
        else {
            for (const [name, spec] of Object.entries(m.nodes)) {
                const path = `nodes.${name}`;
                if (!isObject(spec)) {
                    lost.push(path);
                    continue;
                }
                if (spec.player === true) {
                    only(spec, ['player', 'role'], path);
                    const role = textOf(spec, 'role', path);
                    if (role === '') lost.push(`${path}.role`);
                    nodes.push(block('scn_player', { NAME: name, ROLE: role ?? '' }));
                } else {
                    only(spec, ['role', 'level'], path);
                    if (spec.role !== 'objective' && spec.role !== 'bomb_site') lost.push(`${path}.role`);
                    let level = NO_LEVEL;
                    if ('level' in spec) {
                        if (isInt(spec.level) && spec.level >= 0 && spec.level < LEVELS) level = String(spec.level);
                        else lost.push(`${path}.level`);
                    }
                    nodes.push(block('scn_box', { NAME: name, ROLE: spec.role === 'bomb_site' ? 'bomb_site' : 'objective',
                        LEVEL: level }));
                }
            }
        }
    }

    const objectives = [];
    if (!('objectives' in m)) lost.push('objectives');
    else if (!Array.isArray(m.objectives)) lost.push('objectives');
    else m.objectives.forEach((o, i) => objectives.push(objectiveBlock(o, `objectives[${i}]`, lost, { only, textOf, intOf })));

    const scenario = block('scn_scenario', root, {
        INFO: chain(info), TEAMS: chain(teams), PARAMS: chain(params), NODES: chain(nodes),
        OBJECTIVES: chain(objectives.filter(Boolean)),
    });
    scenario.x = 16;
    scenario.y = 16;
    scenario.deletable = false;
    return { state: { blocks: { languageVersion: 0, blocks: [scenario] } }, lost };
}

const MS = 1000;

function objectiveBlock(o, path, lost, { only, textOf, intOf }) {
    if (!isObject(o)) {
        lost.push(path);
        return null;
    }
    only(o, ['id', 'type', 'name', 'description', 'i18n', 'target', 'assignee', 'params', 'visibility',
        'depends_on', 'time_window', 'effect'], path);
    const fields = { ID: textOf(o, 'id', path) ?? '', NAME: textOf(o, 'name', path) ?? '', TYPE: 'capture_and_hold',
        TARGET: textOf(o, 'target', path) ?? '' };
    if (TYPES.includes(o.type)) fields.TYPE = o.type;
    else lost.push(`${path}.type`);
    if (o.target === '') lost.push(`${path}.target`);
    const rules = [];
    const description = textOf(o, 'description', path);
    if (description !== undefined) rules.push(block('scn_description', { TEXT: description }));
    if ('i18n' in o) {
        const pt = isObject(o.i18n) ? o.i18n.pt : undefined;
        if (!isObject(o.i18n) || !isObject(pt)) lost.push(`${path}.i18n`);
        else {
            only(o.i18n, ['pt'], `${path}.i18n`);
            only(pt, ['name', 'description'], `${path}.i18n.pt`);
            const name = textOf(pt, 'name', `${path}.i18n.pt`);
            if (name !== undefined) rules.push(block('scn_name_pt', { TEXT: name }));
            const desc = textOf(pt, 'description', `${path}.i18n.pt`);
            if (desc !== undefined) rules.push(block('scn_description_pt', { TEXT: desc }));
        }
    }
    if ('assignee' in o) {
        const a = o.assignee;
        if (!isObject(a)) lost.push(`${path}.assignee`);
        else {
            only(a, ['team', 'squad'], `${path}.assignee`);
            const team = textOf(a, 'team', `${path}.assignee`);
            const squad = intOf(a, 'squad', `${path}.assignee`);
            if (team === '' || (team === undefined && squad === undefined)) lost.push(`${path}.assignee`);
            rules.push(block('scn_assignee', { TEAM: team ?? '', SQUAD: squad === undefined ? '' : String(squad) }));
        }
    }
    if ('visibility' in o) {
        if (VISIBILITY.includes(o.visibility)) rules.push(block('scn_visibility', { VISIBILITY: o.visibility }));
        else lost.push(`${path}.visibility`);
    }
    if ('depends_on' in o) {
        if (!Array.isArray(o.depends_on) || o.depends_on.length === 0) lost.push(`${path}.depends_on`);
        else o.depends_on.forEach((ref, j) => {
            if (isText(ref)) rules.push(block('scn_after', { OBJECTIVE: ref }));
            else lost.push(`${path}.depends_on[${j}]`);
        });
    }
    if ('time_window' in o) {
        const w = o.time_window;
        if (!isObject(w) || Object.keys(w).length === 0) lost.push(`${path}.time_window`);
        else {
            only(w, ['start_min', 'end_min'], `${path}.time_window`);
            const start = intOf(w, 'start_min', `${path}.time_window`);
            if (start !== undefined) rules.push(block('scn_opens_at', { MINUTE: start }));
            const end = intOf(w, 'end_min', `${path}.time_window`);
            if (end !== undefined) rules.push(block('scn_closes_at', { MINUTE: end }));
        }
    }
    if ('params' in o) {
        const p = o.params;
        const where = `${path}.params`;
        if (!isObject(p)) lost.push(where);
        else {
            only(p, ['hold_ms', 'duration_s', 'code', 'tag_count', 'any', 'defuse_ms', 'fuse_s', 'destination',
                'max_acc_m', 'minimum_lives'], where);
            const ms = (key, type) => {
                const v = intOf(p, key, where);
                if (v !== undefined) rules.push(block(type, { SECONDS: v / MS }));
            };
            const int = (key, type, field) => {
                const v = intOf(p, key, where);
                if (v !== undefined) rules.push(block(type, { [field]: v }));
            };
            ms('hold_ms', 'scn_hold');
            int('duration_s', 'scn_duration', 'SECONDS');
            const code = textOf(p, 'code', where);
            if (code !== undefined) rules.push(block('scn_code', { CODE: code }));
            if ('tag_count' in p || 'any' in p) {
                const count = intOf(p, 'tag_count', where);
                if (count === undefined) lost.push(`${where}.tag_count`);
                if ('any' in p && p.any !== true) lost.push(`${where}.any`); // false is the default
                rules.push(block('scn_tags', { COUNT: count ?? 1, ANY: p.any === true ? 'TRUE' : 'FALSE' }));
            }
            ms('defuse_ms', 'scn_defuse');
            int('fuse_s', 'scn_fuse', 'SECONDS');
            if ('destination' in p) {
                const d = p.destination;
                const dw = `${where}.destination`;
                if (isObject(d) && 'points' in d) {
                    only(d, ['points'], dw);
                    const corners = [];
                    if (!Array.isArray(d.points)) lost.push(`${dw}.points`);
                    else d.points.forEach((pt, j) => {
                        if (Array.isArray(pt) && pt.length === 2 && isNumber(pt[0]) && isNumber(pt[1])) {
                            corners.push(block('scn_corner', { LAT: pt[0], LON: pt[1] }));
                        } else lost.push(`${dw}.points[${j}]`);
                    });
                    rules.push(block('scn_area', {}, { CORNERS: chain(corners) }));
                } else if (isObject(d)) {
                    only(d, ['lat', 'lon', 'radius_m'], dw);
                    for (const k of ['lat', 'lon', 'radius_m']) if (!isNumber(d[k])) lost.push(`${dw}.${k}`);
                    rules.push(block('scn_circle', { LAT: isNumber(d.lat) ? d.lat : 0, LON: isNumber(d.lon) ? d.lon : 0,
                        RADIUS: isNumber(d.radius_m) ? d.radius_m : 0 }));
                } else lost.push(dw);
            }
            int('max_acc_m', 'scn_max_acc', 'METRES');
            int('minimum_lives', 'scn_lives', 'LIVES');
        }
    }
    if ('effect' in o) {
        const e = o.effect;
        const where = `${path}.effect`;
        if (!isObject(e)) lost.push(where);
        else {
            only(e, ['points', 'win', 'reveal'], where);
            if ('points' in e) {
                if (isInt(e.points)) rules.push(block('scn_points', { POINTS: e.points }));
                else if (isObject(e.points) && isText(e.points.param) && Object.keys(e.points).length === 1) {
                    rules.push(block('scn_points_param', { PARAM: e.points.param }));
                } else lost.push(`${where}.points`);
            }
            if ('win' in e) {
                if (e.win === true) rules.push(block('scn_win'));
                else lost.push(`${where}.win`); // false is the default: the blocks write nothing
            }
            if ('reveal' in e) {
                if (!Array.isArray(e.reveal) || e.reveal.length === 0) lost.push(`${where}.reveal`);
                else e.reveal.forEach((ref, j) => {
                    if (isText(ref)) rules.push(block('scn_reveal', { OBJECTIVE: ref }));
                    else lost.push(`${where}.reveal[${j}]`);
                });
            }
        }
    }
    // An empty id or name would not be written back by the blocks.
    for (const key of ['id', 'name']) if (o[key] === '') lost.push(`${path}.${key}`);
    return block('scn_objective', fields, { RULES: chain(rules) });
}

// ---- blocks -> manifest ---------------------------------------------------------------------

/** The blocks one after the other in a statement input (disabled ones left out). */
function inside(b, input) {
    const out = [];
    for (let c = b.getInputTargetBlock(input); c; c = c.getNextBlock()) if (c.isEnabled()) out.push(c);
    return out;
}

/** An optional whole number typed as text: '' is none, digits a number, anything else as typed
 * (so that the controller says what is wrong with it). */
function optionalInt(value) {
    const v = String(value ?? '').trim();
    if (v === '') return undefined;
    return /^-?\d+$/.test(v) ? Number(v) : v;
}

/**
 * The manifest the blocks say: { manifest, where, problems }. where maps each path the
 * manifest has (objectives[1].depends_on[0]) to the block it came from; problems are what only
 * the blocks can get wrong ({ blockId, path, code, level }): a block in a place that does not
 * take it, a rule given twice in one objective, blocks left outside the scenario.
 */
export function workspaceToManifest(ws) {
    const where = {};
    const problems = [];
    const roots = ws.getTopBlocks(true).filter((b) => b.type === 'scn_scenario');
    for (const b of ws.getTopBlocks(true)) {
        if (b.type !== 'scn_scenario') problems.push({ blockId: b.id, path: '', code: 'loose', level: 'warning' });
        else if (b !== roots[0]) problems.push({ blockId: b.id, path: '', code: 'twice', level: 'error' });
    }
    const root = roots[0];
    if (!root) return { manifest: null, where, problems };
    const placed = (b, input) => inside(b, input).filter((c) => {
        if (PLACES[`${b.type}.${input}`].includes(c.type)) return true;
        problems.push({ blockId: c.id, path: '', code: 'misplaced', level: 'error' });
        return false;
    });
    const m = {};
    const put = (path, value, b) => {
        where[path] = b.id;
        return value;
    };
    const field = (b, name) => b.getFieldValue(name);
    where[''] = root.id;
    for (const [key, name] of [['id', 'ID'], ['version', 'VERSION'], ['name', 'NAME']]) {
        if (field(root, name) !== '') m[key] = put(key, field(root, name), root);
    }
    const i18n = {};
    for (const b of placed(root, 'INFO')) {
        const value = field(b, 'TEXT');
        const [obj, key, path] = {
            scn_description: [m, 'description', 'description'],
            scn_author: [m, 'author', 'author'],
            scn_name_pt: [i18n, 'name', 'i18n.pt.name'],
            scn_description_pt: [i18n, 'description', 'i18n.pt.description'],
        }[b.type];
        if (key in obj) problems.push({ blockId: b.id, path, code: 'twice', level: 'error' });
        else obj[key] = put(path, value, b);
    }
    m.lang = put('lang', field(root, 'LANG'), root);
    m.teams = put('teams', placed(root, 'TEAMS').map((b) => field(b, 'TEAM')), root);
    const squads = Number(field(root, 'SQUADS'));
    if (squads !== 0) m.squads = put('squads', squads, root);
    const params = {};
    const labelsPt = {};
    for (const b of placed(root, 'PARAMS')) {
        const name = field(b, 'NAME');
        const path = `params.${name}`;
        if (name in params) {
            problems.push({ blockId: b.id, path, code: 'twice', level: 'error' });
            continue;
        }
        const spec = { type: 'int' };
        const lo = optionalInt(field(b, 'MIN'));
        const hi = optionalInt(field(b, 'MAX'));
        if (lo !== undefined) spec.min = lo;
        if (hi !== undefined) spec.max = hi;
        spec.default = Number(field(b, 'DEFAULT'));
        if (field(b, 'LABEL') !== '') spec.label = field(b, 'LABEL');
        if (field(b, 'GM_ONLY') === 'TRUE') spec.gm_only = true;
        params[name] = put(path, spec, b);
        if (field(b, 'LABEL_PT') !== '') labelsPt[name] = put(`i18n.pt.params.${name}`, field(b, 'LABEL_PT'), b);
    }
    if (Object.keys(params).length) m.params = params;
    if (Object.keys(labelsPt).length) i18n.params = labelsPt;
    if (Object.keys(i18n).length) {
        m.i18n = { pt: i18n };
        where['i18n'] = where['i18n'] || root.id;
    }
    const nodes = {};
    for (const b of placed(root, 'NODES')) {
        const name = field(b, 'NAME');
        const path = `nodes.${name}`;
        if (name in nodes) {
            problems.push({ blockId: b.id, path, code: 'twice', level: 'error' });
            continue;
        }
        if (b.type === 'scn_player') {
            nodes[name] = { player: true };
            if (field(b, 'ROLE') !== '') nodes[name].role = field(b, 'ROLE');
        } else {
            nodes[name] = { role: field(b, 'ROLE') };
            if (field(b, 'LEVEL') !== NO_LEVEL) nodes[name].level = Number(field(b, 'LEVEL'));
        }
        put(path, nodes[name], b);
    }
    if (Object.keys(nodes).length) m.nodes = nodes;
    m.objectives = placed(root, 'OBJECTIVES').map((b, i) => objectiveOf(b, `objectives[${i}]`, placed, put, problems));
    where.objectives = root.id;
    return { manifest: m, where, problems };
}

function objectiveOf(b, path, placed, put, problems) {
    const field = (blk, name) => blk.getFieldValue(name);
    const o = {};
    put(path, o, b);
    if (field(b, 'ID') !== '') o.id = put(`${path}.id`, field(b, 'ID'), b);
    if (field(b, 'NAME') !== '') o.name = put(`${path}.name`, field(b, 'NAME'), b);
    const pt = {};
    const assignee = {};
    const params = {};
    const window = {};
    const effect = {};
    const after = [];
    const reveal = [];
    let visibility;
    let description;
    const once = (blk, key, rulePath, set) => {
        if (key in once.seen) {
            problems.push({ blockId: blk.id, path: rulePath, code: 'twice', level: 'error' });
            return;
        }
        once.seen[key] = true;
        put(rulePath, null, blk);
        set();
    };
    once.seen = {};
    for (const r of placed(b, 'RULES')) {
        const p = `${path}.params`;
        switch (r.type) {
        case 'scn_description':
            once(r, 'description', `${path}.description`, () => { description = field(r, 'TEXT'); });
            break;
        case 'scn_name_pt':
            once(r, 'name_pt', `${path}.i18n.pt.name`, () => { pt.name = field(r, 'TEXT'); });
            break;
        case 'scn_description_pt':
            once(r, 'description_pt', `${path}.i18n.pt.description`, () => { pt.description = field(r, 'TEXT'); });
            break;
        case 'scn_assignee':
            once(r, 'assignee', `${path}.assignee`, () => {
                if (field(r, 'TEAM') !== '') assignee.team = field(r, 'TEAM');
                const squad = optionalInt(field(r, 'SQUAD'));
                if (squad !== undefined) assignee.squad = squad;
            });
            break;
        case 'scn_visibility':
            once(r, 'visibility', `${path}.visibility`, () => { visibility = field(r, 'VISIBILITY'); });
            break;
        case 'scn_after':
            after.push(field(r, 'OBJECTIVE'));
            put(`${path}.depends_on[${after.length - 1}]`, null, r);
            break;
        case 'scn_opens_at':
            once(r, 'start_min', `${path}.time_window.start_min`, () => { window.start_min = Number(field(r, 'MINUTE')); });
            break;
        case 'scn_closes_at':
            once(r, 'end_min', `${path}.time_window.end_min`, () => { window.end_min = Number(field(r, 'MINUTE')); });
            break;
        case 'scn_hold':
            once(r, 'hold_ms', `${p}.hold_ms`, () => { params.hold_ms = Math.round(Number(field(r, 'SECONDS')) * MS); });
            break;
        case 'scn_duration':
            once(r, 'duration_s', `${p}.duration_s`, () => { params.duration_s = Number(field(r, 'SECONDS')); });
            break;
        case 'scn_code':
            once(r, 'code', `${p}.code`, () => { params.code = field(r, 'CODE'); });
            break;
        case 'scn_tags':
            once(r, 'tag_count', `${p}.tag_count`, () => {
                params.tag_count = Number(field(r, 'COUNT'));
                if (field(r, 'ANY') === 'TRUE') params.any = put(`${p}.any`, true, r);
            });
            break;
        case 'scn_defuse':
            once(r, 'defuse_ms', `${p}.defuse_ms`, () => { params.defuse_ms = Math.round(Number(field(r, 'SECONDS')) * MS); });
            break;
        case 'scn_fuse':
            once(r, 'fuse_s', `${p}.fuse_s`, () => { params.fuse_s = Number(field(r, 'SECONDS')); });
            break;
        case 'scn_circle':
            once(r, 'destination', `${p}.destination`, () => {
                params.destination = { lat: Number(field(r, 'LAT')), lon: Number(field(r, 'LON')),
                    radius_m: Number(field(r, 'RADIUS')) };
            });
            break;
        case 'scn_area':
            once(r, 'destination', `${p}.destination`, () => {
                const corners = placed(r, 'CORNERS');
                corners.forEach((c, j) => put(`${p}.destination.points[${j}]`, null, c));
                params.destination = { points: corners.map((c) => [Number(field(c, 'LAT')), Number(field(c, 'LON'))]) };
            });
            break;
        case 'scn_max_acc':
            once(r, 'max_acc_m', `${p}.max_acc_m`, () => { params.max_acc_m = Number(field(r, 'METRES')); });
            break;
        case 'scn_lives':
            once(r, 'minimum_lives', `${p}.minimum_lives`, () => { params.minimum_lives = Number(field(r, 'LIVES')); });
            break;
        case 'scn_points':
            once(r, 'points', `${path}.effect.points`, () => { effect.points = Number(field(r, 'POINTS')); });
            break;
        case 'scn_points_param':
            once(r, 'points', `${path}.effect.points`, () => { effect.points = { param: field(r, 'PARAM') }; });
            break;
        case 'scn_win':
            once(r, 'win', `${path}.effect.win`, () => { effect.win = true; });
            break;
        case 'scn_reveal':
            reveal.push(field(r, 'OBJECTIVE'));
            put(`${path}.effect.reveal[${reveal.length - 1}]`, null, r);
            break;
        default:
            break;
        }
    }
    if (description !== undefined) o.description = description;
    if (Object.keys(pt).length) o.i18n = { pt };
    o.type = put(`${path}.type`, field(b, 'TYPE'), b);
    if (field(b, 'TARGET') !== '') o.target = put(`${path}.target`, field(b, 'TARGET'), b);
    if (Object.keys(assignee).length) o.assignee = assignee;
    if (Object.keys(params).length) o.params = params;
    if (visibility !== undefined) o.visibility = visibility;
    if (after.length) o.depends_on = after;
    if (Object.keys(window).length) {
        o.time_window = {};
        if ('start_min' in window) o.time_window.start_min = window.start_min;
        if ('end_min' in window) o.time_window.end_min = window.end_min;
    }
    if (reveal.length) effect.reveal = reveal;
    if (Object.keys(effect).length) {
        o.effect = {};
        for (const k of ['points', 'win', 'reveal']) if (k in effect) o.effect[k] = effect[k];
    }
    return o;
}

/** The block a problem's path (objectives[1].depends_on[0]) points at: the one that wrote the
 * longest part of that path, else the scenario block. */
export function blockForPath(where, path) {
    let best = '';
    for (const key of Object.keys(where)) {
        if (key.length > best.length && (path === key || path.startsWith(`${key}.`) || path.startsWith(`${key}[`))) {
            best = key;
        }
    }
    return where[best] || where[''] || null;
}

// ---- YAML --------------------------------------------------------------------------------

// A text written without quotes only when YAML (PyYAML's YAML 1.1) reads it back as the same
// text: letters first, then letters, digits, _, ., - and inner spaces; never a word YAML 1.1
// reads as a boolean or null.
const PLAIN = /^[\p{L}_][\p{L}\p{N}_.\- ]*$/u;
const RESERVED = /^(yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF|null|Null|NULL)$/;
const ESCAPES = { '"': '\\"', '\\': '\\\\', '\n': '\\n', '\r': '\\r', '\t': '\\t' };

function quote(s) {
    let out = '"';
    for (const ch of s) {
        const c = ch.codePointAt(0);
        if (ESCAPES[ch]) out += ESCAPES[ch];
        // Controls, YAML 1.1's other line breaks (NEL, LS, PS), the BOM and lone surrogates.
        else if (c < 0x20 || (c >= 0x7f && c <= 0x9f) || c === 0x2028 || c === 0x2029 || c === 0xfeff
                 || (c >= 0xd800 && c <= 0xdfff)) out += `\\u${c.toString(16).padStart(4, '0')}`;
        else out += ch;
    }
    return `${out}"`;
}

function scalar(v) {
    if (v === null || v === undefined) return 'null';
    if (typeof v === 'boolean') return v ? 'true' : 'false';
    if (typeof v === 'number') {
        if (!Number.isFinite(v)) return 'null';
        let s = String(v);
        // PyYAML reads an exponent only with a dot before it (1.0e-7, not 1e-7).
        if (/e/.test(s) && !s.includes('.')) s = s.replace('e', '.0e');
        return s;
    }
    const s = String(v);
    return PLAIN.test(s) && !s.endsWith(' ') && !RESERVED.test(s) ? s : quote(s);
}

function flow(v) {
    if (Array.isArray(v)) return `[${v.map(flow).join(', ')}]`;
    if (isObject(v)) {
        const entries = Object.entries(v);
        return entries.length ? `{ ${entries.map(([k, x]) => `${scalar(k)}: ${flow(x)}`).join(', ')} }` : '{}';
    }
    return scalar(v);
}

const WIDTH = 100;

function emitMap(obj, indent, lines, first = null) {
    const pad = ' '.repeat(indent);
    Object.entries(obj).forEach(([k, v], i) => {
        const lead = i === 0 && first !== null ? first : pad;
        const key = `${lead}${scalar(k)}:`;
        if (!Array.isArray(v) && !isObject(v)) lines.push(`${key} ${scalar(v)}`);
        else if (`${key} ${flow(v)}`.length <= WIDTH) lines.push(`${key} ${flow(v)}`);
        else if (Array.isArray(v)) {
            lines.push(key);
            for (const item of v) {
                if (isObject(item) && Object.keys(item).length) emitMap(item, indent + 4, lines, `${pad}  - `);
                else lines.push(`${pad}  - ${flow(item)}`);
            }
        } else {
            lines.push(key);
            emitMap(v, indent + 2, lines);
        }
    });
}

const TOP = ['id', 'version', 'name', 'author', 'description', 'lang', 'teams', 'squads', 'params', 'i18n', 'nodes',
    'objectives'];
const OBJECTIVE = ['id', 'name', 'description', 'i18n', 'type', 'target', 'assignee', 'params', 'visibility',
    'depends_on', 'time_window', 'effect'];

function ordered(obj, keys) {
    const out = {};
    for (const k of keys) if (k in obj) out[k] = obj[k];
    for (const k of Object.keys(obj)) if (!(k in out)) out[k] = obj[k];
    return out;
}

/** The manifest as YAML, laid out as the hand-written examples: small maps on one line, a blank
 * line before the nodes, the objectives and each objective. */
export function toYaml(manifest) {
    const lines = [];
    const top = ordered(manifest, TOP);
    const head = Object.fromEntries(Object.entries(top).filter(([k]) => k !== 'nodes' && k !== 'objectives'));
    emitMap(head, 0, lines);
    if ('nodes' in top) {
        lines.push('');
        emitMap({ nodes: top.nodes }, 0, lines);
    }
    if ('objectives' in top) {
        lines.push('');
        const list = top.objectives;
        if (!Array.isArray(list) || list.length === 0) lines.push(`objectives: ${flow(list)}`);
        else {
            lines.push('objectives:');
            list.forEach((o, i) => {
                if (i > 0) lines.push('');
                if (isObject(o) && Object.keys(o).length) emitMap(ordered(o, OBJECTIVE), 4, lines, '  - ');
                else lines.push(`  - ${flow(o)}`);
            });
        }
    }
    return `${lines.join('\n')}\n`;
}
