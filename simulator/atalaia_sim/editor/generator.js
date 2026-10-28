// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Blocks to a mode folder's text files (ADR-P5-1 as amended 2026-10-22): node.lua, field.lua and
// mode.yaml. The Lua comes from a CodeGenerator of Blockly's own Lua generator class, with the
// project's style: 2-space indent, double quotes, the memory (state.node{} / state.field{}) first,
// then the variables as locals, helpers, `local function`s (a function before those that call
// it), then the handlers and timers in the order the blocks sit on the workspace, a blank line
// between each. A handler that only calls a function without arguments names it
// (on("game.start", show)). Problems the Lua would hit at run time, or the manifest at install
// time, are listed with each block's id, so the editor can point at the block. Plan phase 3
// added geo, the mode's GM commands (mode.yaml commands: and their cmd.mode handlers), several
// roles with their own inputs, the kinds modifier and role, and the mode's screens by name.

import { BUILTIN_SCREENS, luaName, POLYGON_MAX } from './blocks.js';

const PROCEDURES = new Set(['procedures_defnoreturn', 'procedures_defreturn']);
const CALLS = new Set(['procedures_callnoreturn', 'procedures_callreturn']);
/** Blocks of Blockly's own the toolbox offers; their Lua is Blockly's. */
const STANDARD = [
    'controls_if', 'logic_compare', 'logic_operation', 'logic_negate', 'logic_boolean', 'logic_null',
    'logic_ternary', 'math_number', 'math_arithmetic', 'math_round', 'math_single', 'text', 'text_join',
    'lists_length', 'lists_create_with', 'lists_getIndex', 'variables_get', 'variables_set', 'procedures_callnoreturn',
    'procedures_callreturn',
];
/** Inputs a script reacts to, and the capability each one needs (mode.yaml roles: requires). */
const INPUT_CAPS = [['team_input.', 'team_input'], ['keypad.', 'keypad'], ['nfc.', 'nfc'], ['hit.', 'hit'], ['gps.', 'gps']];
/** Outputs a script uses, and the capability each one may use (roles: optional). */
const OUTPUT_CAPS = [['atalaia_team_display', 'team_display'], ['atalaia_sound', 'audio'], ['atalaia_screen', 'display']];
/** The inputs a role may require, in the order mode.yaml lists them. */
export const ROLE_INPUTS = INPUT_CAPS.map(([, cap]) => cap);
/** The kinds the editor makes (a scenario is made in the GM console, P5R-2). */
export const KINDS = ['mode', 'modifier', 'role'];

/** The approved licences of community modes (ADR-P5-5). */
export const LICENCES = ['GPL-3.0-or-later', 'LGPL-3.0-or-later', 'MIT', 'Apache-2.0', 'BSD-2-Clause',
    'BSD-3-Clause', 'CC0-1.0'];

/** A Lua string in double quotes. */
function quote(text) {
    return '"' + String(text).replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r') + '"';
}

/** Comment lines for a header, wrapped at about 90 columns. */
function commentLines(text, prefix = '-- ') {
    const out = [];
    let line = '';
    for (const word of String(text).split(/\s+/).filter(Boolean)) {
        if (line && (line + ' ' + word).length > 90) {
            out.push(prefix + line);
            line = word;
        } else {
            line = line ? line + ' ' + word : word;
        }
    }
    if (line) out.push(prefix + line);
    return out;
}

/** Makes the generator: Blockly's Lua generator class with the blocks of blocks.js. */
export function makeGenerator(lua) {
    const { LuaGenerator, Order, luaGenerator } = lua;
    const g = new LuaGenerator('AtalaiaLua');
    for (const type of STANDARD) g.forBlock[type] = luaGenerator.forBlock[type];
    // "a or b or c" without brackets: and/or are associative.
    g.ORDER_OVERRIDES = [[Order.AND, Order.AND], [Order.OR, Order.OR]];
    g.COMMENT_WRAP = 90;
    g.quote_ = quote;
    g.multiline_quote_ = quote;

    const problem = (key, block, args = {}) => g.problems_.push({ key, block: block ? block.id : null, ...args });
    const value = (block, name, order, fallback = 'nil') => g.valueToCode(block, name, order) || fallback;

    /** A data table from a stack of "name = value" blocks: { a = 1, b = e.team } or {}. */
    const table = (block, input) => {
        const parts = [];
        for (let b = block.getInputTargetBlock(input); b; b = b.getNextBlock()) {
            if (b.isEnabled() && b.type === 'atalaia_pair') {
                parts.push(b.getFieldValue('KEY') + ' = ' + value(b, 'VALUE', Order.NONE));
            }
        }
        return parts.length ? '{ ' + parts.join(', ') + ' }' : '{}';
    };

    /**
     * The function a handler or a timer runs: function(e) ... end, or the name of a function
     * when that is all it does. `event`: whether its blocks can read the event (on(), not timers).
     */
    const callback = (block, event) => {
        const body = block.getInputTargetBlock('DO');
        if (body && !body.getNextBlock() && body.type === 'procedures_callnoreturn' && body.isEnabled()
            && body.getVarModels().length === 0 && !body.getCommentText()) {
            return g.getProcedureName(body.getFieldValue('NAME'));
        }
        const frame = { event, used: false };
        g.frames_.push(frame);
        const code = g.statementToCode(block, 'DO');
        g.frames_.pop();
        return 'function(' + (frame.used ? 'e' : '') + ')\n' + code + 'end';
    };

    const eventValue = (block, key) => {
        const frame = [...g.frames_].reverse().find((f) => f.event || f.barrier);
        if (frame && frame.event) frame.used = true;
        else problem('problem_event_outside', block);
        return ['e.' + key, Order.HIGH];
    };

    const memory = () => (g.kind_ === 'field' ? 'fs' : 's');
    const memoryKey = (block) => {
        const key = block.getFieldValue('KEY');
        g.memoryUsed_ = true;
        if (!g.memoryKeys_.has(key)) problem('problem_state_undeclared', block, { name: key });
        return key;
    };

    const on = (block) => 'on(' + quote(block.getFieldValue('EVENT')) + ', ' + callback(block, true) + ')\n';
    const timer = (name, named) => (block) => {
        const call = name + '(' + value(block, 'SECONDS', Order.NONE, '1') + ', ' + callback(block, false) + ')\n';
        return named ? g.getVariableName(block.getFieldValue('TIMER')) + ' = ' + call : call;
    };

    Object.assign(g.forBlock, {
        atalaia_state_node: () => '',
        atalaia_state_field: () => '',
        atalaia_state_item: () => '',
        atalaia_pair: () => '',
        atalaia_param_declare: () => '',
        atalaia_state_get: (block) => [memory() + '.' + memoryKey(block), Order.HIGH],
        atalaia_state_set: (block) => memory() + '.' + memoryKey(block) + ' = ' + value(block, 'VALUE', Order.NONE) + '\n',

        atalaia_on_node: on,
        atalaia_on_field: on,
        atalaia_on_custom: on,
        atalaia_event_value: (block) => eventValue(block, block.getFieldValue('KEY')),
        atalaia_event_value_custom: (block) => eventValue(block, block.getFieldValue('KEY')),
        atalaia_emit: (block) => {
            const data = table(block, 'DATA');
            const prio = block.getFieldValue('PRIO');
            const args = [quote(block.getFieldValue('TYPE'))];
            if (data !== '{}' || prio !== 'default') args.push(data);
            if (prio !== 'default') args.push('{ prio = ' + quote(prio) + ' }');
            return 'emit(' + args.join(', ') + ')\n';
        },

        atalaia_every: timer('every', false),
        atalaia_every_as: timer('every', true),
        atalaia_after: timer('after', false),
        atalaia_after_as: timer('after', true),
        atalaia_cancel: (block) => 'cancel(' + g.getVariableName(block.getFieldValue('TIMER')) + ')\n',

        atalaia_win: (block) => 'game.win(' + value(block, 'TEAM', Order.NONE) + ')\n',
        atalaia_finish: (block) => {
            const reason = block.getFieldValue('REASON');
            return 'game.finish(' + (reason ? quote(reason) : '') + ')\n';
        },
        atalaia_time: () => ['game.time()', Order.HIGH],
        atalaia_teams: () => ['game.teams()', Order.HIGH],
        // "stop here" has no next connection: nothing can follow it, as in Lua.
        atalaia_return: () => 'return\n',

        atalaia_score_add: (block) => {
            const points = block.getInputTargetBlock('POINTS');
            if (points && points.type === 'math_number' && !Number.isInteger(Number(points.getFieldValue('NUM')))) {
                problem('problem_points_integer', block);
            }
            const reason = block.getFieldValue('REASON');
            const args = [value(block, 'TEAM', Order.NONE), value(block, 'POINTS', Order.NONE, '0')];
            if (reason) args.push(quote(reason));
            return 'score.add(' + args.join(', ') + ')\n';
        },
        atalaia_score_get: (block) => ['score.get(' + value(block, 'TEAM', Order.NONE) + ')', Order.HIGH],

        atalaia_screen: (block) => {
            const name = block.getFieldValue('NAME');
            if (!BUILTIN_SCREENS.includes(name) && !g.screens_.includes(name)) problem('problem_screen_unknown', block, { name });
            return 'ui.screen(' + quote(name) + ', ' + table(block, 'DATA') + ')\n';
        },
        atalaia_sound: (block) => 'audio.play(' + quote(block.getFieldValue('CLIP')) + ')\n',
        atalaia_team_display: (block) => 'cap("team_display"):show(' + value(block, 'TEAM', Order.NONE) + ')\n',

        atalaia_param: (block) => {
            const name = block.getFieldValue('NAME');
            g.paramsUsed_.push([name, block]);
            return ['params.' + name, Order.HIGH];
        },

        atalaia_rand: (block) => [
            'rand(' + value(block, 'FROM', Order.NONE, '1') + ', ' + value(block, 'TO', Order.NONE, '1') + ')', Order.HIGH],
        atalaia_log: (block) => 'log(' + value(block, 'TEXT', Order.NONE, '""') + ')\n',
        atalaia_idiv: (block) => [
            value(block, 'A', Order.MULTIPLICATIVE, '0') + ' // ' + value(block, 'B', Order.EXPONENTIATION, '1'),
            Order.MULTIPLICATIVE],

        atalaia_geo_distance: (block) => [
            'geo.distance(' + ['LAT1', 'LON1', 'LAT2', 'LON2'].map((n) => value(block, n, Order.NONE, '0')).join(', ') + ')',
            Order.HIGH],
        atalaia_geo_in_zone: (block) => [
            'geo.in_zone(' + value(block, 'LAT', Order.NONE, '0') + ', ' + value(block, 'LON', Order.NONE, '0') + ', '
                + value(block, 'ZONE', Order.NONE) + ')', Order.HIGH],
        atalaia_geo_circle: (block) => [
            '{ type = "circle", lat = ' + value(block, 'LAT', Order.NONE, '0') + ', lon = ' + value(block, 'LON', Order.NONE, '0')
                + ', radius_m = ' + value(block, 'RADIUS', Order.NONE, '0') + ' }', Order.HIGH],
        atalaia_geo_polygon: (block) => {
            const points = [];
            for (let b = block.getInputTargetBlock('POINTS'); b; b = b.getNextBlock()) {
                if (b.isEnabled() && b.type === 'atalaia_geo_point') {
                    points.push('{ ' + value(b, 'LAT', Order.NONE, '0') + ', ' + value(b, 'LON', Order.NONE, '0') + ' }');
                }
            }
            if (points.length < 3 || points.length > POLYGON_MAX) problem('problem_polygon_points', block, { name: String(POLYGON_MAX) });
            return ['{ type = "polygon", points = { ' + points.join(', ') + ' } }', Order.HIGH];
        },
        atalaia_geo_point: () => '',
        atalaia_event_has_position: (block) => {
            eventValue(block, 'lat');
            return ['type(e.lat) == "number" and type(e.lon) == "number"', Order.AND];
        },

        atalaia_command_declare: () => '',
        // A mode command (the GM's from the console, or field.send(node, "mode", ...)) reaches the
        // box as cmd.mode with its name: one handler per name, which returns at once for another.
        atalaia_on_command: (block) => {
            const frame = { event: true, used: true };
            g.frames_.push(frame);
            const code = g.statementToCode(block, 'DO');
            g.frames_.pop();
            const i = g.INDENT;
            return 'on("cmd.mode", function(e)\n' + i + 'if e.name ~= ' + quote(block.getFieldValue('NAME')) + ' then\n'
                + i + i + 'return\n' + i + 'end\n' + code + 'end)\n';
        },

        atalaia_field_ids: (block) => {
            g.rolesUsed_.push([block.getFieldValue('ROLE'), block]);
            const helper = g.provideFunction_('node_ids', [
                `local function ${g.FUNCTION_NAME_PLACEHOLDER_}(role)`,
                '  local found = {}',
                '  for _, n in ipairs(field.nodes(role)) do',
                '    found[#found + 1] = n.id',
                '  end',
                '  return found',
                'end',
            ]);
            return [helper + '(' + quote(block.getFieldValue('ROLE')) + ')', Order.HIGH];
        },
        atalaia_field_owner: (block) => ['field.owner(' + value(block, 'NODE', Order.NONE, '0') + ')', Order.HIGH],
        atalaia_field_common_owner: (block) => [
            'field.common_owner(' + value(block, 'NODES', Order.NONE, '{}') + ')', Order.HIGH],
        atalaia_field_send: (block) => {
            const data = table(block, 'DATA');
            const args = [value(block, 'NODE', Order.NONE, '0'), quote(block.getFieldValue('CMD'))];
            if (data !== '{}') args.push(data);
            return 'field.send(' + args.join(', ') + ')\n';
        },
        atalaia_field_send_mode: (block) => {
            const data = table(block, 'DATA');
            const name = 'name = ' + quote(block.getFieldValue('NAME'));
            const params = data === '{}' ? '{ ' + name + ' }' : '{ ' + name + ', ' + data.slice(2);
            return 'field.send(' + value(block, 'NODE', Order.NONE, '0') + ', "mode", ' + params + ')\n';
        },
        atalaia_field_score: (block) => ['field.score()[' + value(block, 'TEAM', Order.NONE) + ']', Order.HIGH],

        // A for-each loop as Blockly writes it, without its space after "do".
        controls_forEach: (block, gen) => luaGenerator.forBlock.controls_forEach(block, gen).replace(' do \n', ' do\n'),

        // Functions are local, and placed by generateScript before the code that calls them. (The
        // editor sets Blockly's "Describe this function..." comment to nothing, ADR-P5-1 rule 4.)
        procedures_defnoreturn: (block) => {
            const name = g.getProcedureName(block.getFieldValue('NAME'));
            const args = block.getVarModels().map((v) => g.getVariableName(v.getId()));
            g.frames_.push({ barrier: true });
            let body = block.getInput('STACK') ? g.statementToCode(block, 'STACK') : '';
            const result = block.getInput('RETURN') ? g.valueToCode(block, 'RETURN', Order.NONE) : '';
            g.frames_.pop();
            if (result) body += g.INDENT + 'return ' + result + '\n';
            const head = g.forward_.has(name) ? 'function ' : 'local function ';
            return head + name + '(' + args.join(', ') + ')\n' + body + 'end\n';
        },
    });
    g.forBlock.procedures_defreturn = g.forBlock.procedures_defnoreturn;
    g.order_ = Order;
    return g;
}

/** Function definitions ordered so that a function comes before those that call it. */
function orderProcedures(procs) {
    const byName = new Map(procs.map((b) => [b.getFieldValue('NAME'), b]));
    const done = new Set();
    const visiting = new Set();
    const forward = new Set();
    const out = [];
    const visit = (block) => {
        const name = block.getFieldValue('NAME');
        if (done.has(name)) return;
        if (visiting.has(name)) {
            forward.add(name); // a call back up the chain: declare it first
            return;
        }
        visiting.add(name);
        for (const d of block.getDescendants(true)) {
            if (CALLS.has(d.type) && byName.has(d.getFieldValue('NAME'))) visit(byName.get(d.getFieldValue('NAME')));
        }
        visiting.delete(name);
        done.add(name);
        out.push(block);
    };
    procs.forEach(visit);
    return { ordered: out, forward };
}

/** Whether a block sits in the body of a for-each loop over the variable `id`. */
function insideLoopOf(block, id) {
    for (let b = block.getSurroundParent(); b; b = b.getSurroundParent()) {
        if (b.type === 'controls_forEach' && b.getFieldValue('VAR') === id) return true;
    }
    return false;
}

/** The variables the script keeps at the top level: not function parameters, not only loop variables. */
function topVariables(ws, procs) {
    const params = new Set();
    for (const p of procs) for (const v of p.getVarModels()) params.add(v.getId());
    const used = new Map();
    for (const block of ws.getAllBlocks(false)) {
        if (!block.isEnabled()) continue;
        for (const input of block.inputList) {
            for (const field of input.fieldRow) {
                if (field.referencesVariables && field.referencesVariables()) {
                    const id = field.getValue();
                    // A for-each loop's variable is local to the loop in Lua, and so is reading it inside one.
                    const loopOnly = (block.type === 'controls_forEach' && field.name === 'VAR')
                        || (block.type === 'variables_get' && insideLoopOf(block, id));
                    if (!used.has(id)) used.set(id, true);
                    if (!loopOnly) used.set(id, false);
                }
            }
        }
    }
    return ws.getVariableMap().getAllVariables()
        .filter((v) => used.has(v.getId()) && !used.get(v.getId()) && !params.has(v.getId()))
        .map((v) => v.getId());
}

/**
 * Lua for one workspace: kind 'node' (node.lua) or 'field' (field.lua). `info` is the Mode
 * tab's form (name, description, licence, author, year). Returns { code, problems, used }, code
 * '' when the workspace has no script blocks.
 */
export function generateScript(g, ws, kind, info, screens = []) {
    g.kind_ = kind;
    g.screens_ = screens;
    g.rolesUsed_ = [];
    g.problems_ = [];
    g.frames_ = [];
    g.paramsUsed_ = [];
    g.memoryUsed_ = false;
    g.forward_ = new Set();
    g.init(ws);
    const memoryType = kind === 'field' ? 'atalaia_state_field' : 'atalaia_state_node';
    const top = ws.getTopBlocks(true).filter((b) => b.isEnabled());
    const memoryBlocks = top.filter((b) => b.type === memoryType);
    g.memoryKeys_ = new Set();
    for (const m of memoryBlocks) {
        for (let item = m.getInputTargetBlock('ITEMS'); item; item = item.getNextBlock()) {
            if (item.isEnabled()) g.memoryKeys_.add(item.getFieldValue('KEY'));
        }
    }
    const procs = top.filter((b) => PROCEDURES.has(b.type));
    const { ordered, forward } = orderProcedures(procs);
    g.forward_ = forward;
    const skip = new Set(['atalaia_state_node', 'atalaia_state_field', 'atalaia_state_item', 'atalaia_pair',
        'atalaia_param_declare', 'atalaia_command_declare', 'atalaia_geo_point']);
    const rest = top.filter((b) => !PROCEDURES.has(b.type) && !skip.has(b.type) && !b.outputConnection);

    const procCode = ordered.map((b) => g.blockToCode(b));
    const restCode = rest.map((b) => g.blockToCode(b));

    const items = [];
    for (const m of memoryBlocks) {
        for (let item = m.getInputTargetBlock('ITEMS'); item; item = item.getNextBlock()) {
            if (item.isEnabled()) {
                items.push(item.getFieldValue('KEY') + ' = ' + (g.valueToCode(item, 'VALUE', g.order_.NONE) || 'nil'));
            }
        }
    }
    const chunks = [];
    if (items.length || g.memoryUsed_) {
        const call = kind === 'field' ? 'state.field' : 'state.node';
        chunks.push(`local ${kind === 'field' ? 'fs' : 's'} = ${call} ${items.length ? '{ ' + items.join(', ') + ' }' : '{}'}\n`);
    }
    const locals = [...topVariables(ws, procs).map((id) => g.getVariableName(id)),
        ...ordered.filter((b) => forward.has(b.getFieldValue('NAME'))).map((b) => g.getProcedureName(b.getFieldValue('NAME')))];
    if (locals.length) chunks.push('local ' + locals.join(', ') + '\n');
    chunks.push(...Object.values(g.definitions_).map((d) => d + '\n'));
    chunks.push(...procCode, ...restCode);
    const body = chunks.filter((c) => c && c.trim());
    const used = new Set(g.paramsUsed_.map(([name]) => name));
    const result = { code: '', problems: g.problems_, params: g.paramsUsed_, used, roles: g.rolesUsed_ };
    if (!body.length) return result;
    const where = kind === 'field' ? 'on the field controller' : 'on each box';
    // The generated files' own licence headers (REUSE-IgnoreStart)
    const header = [
        `-- SPDX-FileCopyrightText: ${info.year} ${info.author}`,
        `-- SPDX-License-Identifier: ${info.license}`,
        '--',
        `-- ${info.name}, ${where}.`,
        ...commentLines(info.description || ''),
        '-- Made with the Atalaia mode editor (simulator/atalaia_sim/editor).',
    ].join('\n') + '\n'; // (REUSE-IgnoreEnd)
    result.code = [header, ...body.map((c) => c.replace(/\n+$/, '\n'))].join('\n');
    return result;
}

const MARK = /^\s*--@@'(.*)'$/;

/**
 * Which block each line of a generated script comes from, so an error the simulator reports
 * at "node.lua:12" can point at its block. The script is generated again with Blockly's
 * statement prefix set to a marker line before each statement block; with the markers taken
 * out it must be the script `code` exactly, and then line n comes from the block of the last
 * marker before it. Returns an array (index n - 1 for line n; null before any block), or null
 * when the two do not agree.
 */
export function lineBlocks(g, ws, kind, info, code, screens = []) {
    g.STATEMENT_PREFIX = '--@@%1\n';
    let marked;
    try {
        marked = generateScript(g, ws, kind, info, screens).code;
    } finally {
        g.STATEMENT_PREFIX = null;
    }
    const plain = [];
    const blocks = [];
    let current = null;
    for (const line of marked.split('\n')) {
        const mark = MARK.exec(line);
        if (mark) {
            current = mark[1];
        } else {
            plain.push(line);
            blocks.push(current);
        }
    }
    return plain.join('\n') === code ? blocks : null;
}

/** The parameter declarations of a workspace: [name, spec, block] for mode.yaml. */
function declarations(ws) {
    return ws.getTopBlocks(true).filter((b) => b.isEnabled() && b.type === 'atalaia_param_declare');
}

/** A setting's schema from its block, or null when its default does not fit. */
function paramSpec(block) {
    const type = block.getFieldValue('TYPE');
    const text = (name) => String(block.getFieldValue(name) || '').trim();
    const spec = { type };
    const int = (s) => (/^-?\d+$/.test(s) ? Number(s) : null);
    if (type === 'int') {
        const [def, min, max] = [int(text('DEFAULT')), int(text('MIN')), int(text('MAX'))];
        if (text('MIN') && min === null) return null;
        if (text('MAX') && max === null) return null;
        if (min !== null) spec.min = min;
        if (max !== null) spec.max = max;
        if (text('DEFAULT')) {
            if (def === null || (min !== null && def < min) || (max !== null && def > max)) return null;
            spec.default = def;
        }
    } else if (type === 'bool') {
        const def = text('DEFAULT').toLowerCase();
        if (def && !['true', 'false'].includes(def)) return null;
        if (def) spec.default = def === 'true';
    } else if (type === 'string') {
        const max = int(text('MAX'));
        if (max !== null) spec.max = max;
        spec.default = String(block.getFieldValue('DEFAULT') || '');
    } else if (text('DEFAULT')) {
        spec.default = text('DEFAULT');
    }
    spec.label = String(block.getFieldValue('LABEL') || '');
    return spec;
}

/** YAML for a scalar: numbers and booleans as they are, text in double quotes (JSON's are YAML's). */
function yamlValue(v) {
    return typeof v === 'string' ? JSON.stringify(v) : String(v);
}

/**
 * The mode's roles from the Mode tab: [{ name, inputs, needed }], `inputs` null for "the inputs the
 * box script reacts to" or a list of ROLE_INPUTS. A project saved before plan phase 3 has one
 * `role` (a name) instead.
 */
export function modeRoles(info) {
    const roles = Array.isArray(info.roles) ? info.roles : [{ name: info.role || 'zone' }];
    return roles.map((r) => ({
        name: String((r && r.name) || '').trim(),
        inputs: r && Array.isArray(r.inputs) ? ROLE_INPUTS.filter((cap) => r.inputs.includes(cap)) : null,
        needed: !(r && r.needed === false),
    }));
}

/** The kind the Mode tab says (mode, modifier, role), mode when it says nothing else. */
export function modeKind(info) {
    return KINDS.includes(info.kind) ? info.kind : 'mode';
}

/** The command declarations of a workspace. */
function commandBlocks(ws) {
    return ws.getTopBlocks(true).filter((b) => b.isEnabled() && b.type === 'atalaia_command_declare');
}

/**
 * mode.yaml from the Mode tab's form and both workspaces: the settings and GM commands from their
 * declaration blocks; each role's capabilities from the blocks the box script uses (inputs it
 * reacts to are required, unless the role lists its own; outputs it uses are optional). Returns
 * { code, problems }.
 */
/**
 * The mode's translations the Mode tab and the declaration blocks carry (mode.yaml `i18n`): the
 * language code and the suffix of its fields (`name_pt`, `LABEL_PT`; `name_zh_tw`, `LABEL_ZH_TW`
 * for `zh-tw`). A project saved before German and Chinese has no such fields: they read as empty.
 */
export const TRANSLATIONS = [['pt', 'pt'], ['de', 'de'], ['zh-tw', 'zh_tw']];

function translatedLabels(block) {
    const out = {};
    for (const [lang, suffix] of TRANSLATIONS) {
        const field = `LABEL_${suffix.toUpperCase()}`;
        out[lang] = block.getField(field) ? String(block.getFieldValue(field) || '').trim() : '';
    }
    return out;
}

export function generateManifest(info, nodeWs, fieldWs, scripts) {
    const problems = [];
    if (!/^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$/.test(info.id || '')) problems.push({ key: 'problem_bad_id', block: null });
    if (!String(info.name || '').trim()) problems.push({ key: 'problem_no_name', block: null });
    const params = [];
    const seen = new Set();
    for (const ws of [nodeWs, fieldWs]) {
        for (const block of declarations(ws)) {
            const name = block.getFieldValue('NAME');
            if (seen.has(name)) {
                problems.push({ key: 'problem_param_twice', block: block.id, name });
                continue;
            }
            seen.add(name);
            const spec = paramSpec(block);
            if (!spec) problems.push({ key: 'problem_param_default', block: block.id, name });
            else params.push([name, spec, translatedLabels(block)]);
        }
    }
    for (const script of scripts) {
        for (const [name, block] of script.params) {
            if (!seen.has(name)) problems.push({ key: 'problem_param_undeclared', block: block.id, name });
        }
    }
    const blocks = nodeWs.getAllBlocks(false).filter((b) => b.isEnabled());
    const events = blocks.filter((b) => b.type === 'atalaia_on_node' || b.type === 'atalaia_on_custom')
        .map((b) => b.getFieldValue('EVENT'));
    const handled = INPUT_CAPS.filter(([prefix]) => events.some((e) => e.startsWith(prefix))).map(([, cap]) => cap);
    const optional = OUTPUT_CAPS.filter(([type]) => blocks.some((b) => b.type === type)).map(([, cap]) => cap);

    // ---- roles ----
    const roles = modeRoles(info);
    const roleNames = new Set();
    const roleLines = [];
    if (!roles.length) problems.push({ key: 'problem_no_role', block: null });
    for (const role of roles) {
        if (!luaName(role.name)) {
            problems.push({ key: 'problem_bad_role', block: null, name: role.name });
            continue;
        }
        if (roleNames.has(role.name)) {
            problems.push({ key: 'problem_role_twice', block: null, name: role.name });
            continue;
        }
        roleNames.add(role.name);
        const requires = role.inputs || handled;
        if (role.inputs && role.inputs.some((cap) => !handled.includes(cap))) {
            problems.push({ key: 'problem_role_input_unhandled', block: null, name: role.name });
        }
        if (role.inputs && !role.inputs.length && handled.length) {
            problems.push({ key: 'problem_role_no_input', block: null, name: role.name });
        }
        const caps = [];
        if (requires.length) caps.push(`requires: [${requires.join(', ')}]`);
        if (optional.length) caps.push(`optional: [${optional.join(', ')}]`);
        if (!role.needed) caps.push('needed: false');
        roleLines.push(`  ${role.name}: { ${caps.join(', ')} }`.replace('{  }', '{}'));
    }
    for (const script of scripts) {
        for (const [name, block] of script.roles || []) {
            if (!roleNames.has(name)) problems.push({ key: 'problem_role_unknown', block: block.id, name });
        }
    }

    // ---- GM commands ----
    const commands = [];
    const commandNames = new Set();
    const handlers = new Set(blocks.filter((b) => b.type === 'atalaia_on_command').map((b) => b.getFieldValue('NAME')));
    for (const block of commandBlocks(nodeWs)) {
        const name = block.getFieldValue('NAME');
        if (commandNames.has(name)) {
            problems.push({ key: 'problem_command_twice', block: block.id, name });
            continue;
        }
        commandNames.add(name);
        const forRoles = String(block.getFieldValue('ROLES')).split(',').map((r) => r.trim()).filter(Boolean);
        for (const role of forRoles.filter((r) => !roleNames.has(r))) {
            problems.push({ key: 'problem_role_unknown', block: block.id, name: role });
        }
        if (!handlers.has(name)) problems.push({ key: 'problem_command_unhandled', block: block.id, name });
        commands.push([name, forRoles, String(block.getFieldValue('LABEL') || '').trim() || name,
            translatedLabels(block)]);
    }

    // (REUSE-IgnoreStart)
    const lines = [
        `# SPDX-FileCopyrightText: ${info.year} ${info.author}`,
        `# SPDX-License-Identifier: ${info.license}`, // (REUSE-IgnoreEnd)
        `id: ${info.id}`,
        `version: ${info.version}`,
        `license: ${info.license}`,
        `min_tier: ${info.min_tier}`,
        `kind: ${modeKind(info)}`,
        `name: ${yamlValue(info.name)}`,
        `description: ${yamlValue(info.description)}`,
        'roles:',
        ...roleLines,
    ];
    if (params.length) {
        lines.push('params:');
        for (const [name, spec] of params) {
            const fields = Object.entries(spec).map(([k, v]) => `${k}: ${k === 'type' ? v : yamlValue(v)}`);
            lines.push(`  ${name}: { ${fields.join(', ')} }`);
        }
    }
    if (commands.length) {
        lines.push('commands:');
        for (const [name, forRoles, label] of commands) {
            lines.push(`  ${name}: { roles: [${forRoles.join(', ')}], label: ${yamlValue(label)} }`);
        }
    }
    // How a box scores while it holds, so a controller can project the points between two STATEs
    // (modes/README.md, "Projected score"). No block sets it: the project carries it as it came.
    const hold = info.scoring && info.scoring.hold;
    if (hold && hold.every && hold.points) {
        lines.push('scoring:', `  hold: { every: ${yamlValue(hold.every)}, points: ${yamlValue(hold.points)} }`);
    }
    for (const [lang, suffix] of TRANSLATIONS) {
        const labels = params.filter(([, , tr]) => tr[lang]);
        const commandLabels = commands.filter(([, , , tr]) => tr[lang]);
        const name = info[`name_${suffix}`];
        const description = info[`description_${suffix}`];
        if (!(name || description || labels.length || commandLabels.length)) continue;
        if (!lines.includes('i18n:')) lines.push('i18n:');
        lines.push(`  ${lang}:`);
        if (name) lines.push(`    name: ${yamlValue(name)}`);
        if (description) lines.push(`    description: ${yamlValue(description)}`);
        if (labels.length) {
            lines.push('    params:');
            for (const [pname, , tr] of labels) lines.push(`      ${pname}: ${yamlValue(tr[lang])}`);
        }
        if (commandLabels.length) {
            lines.push('    commands:');
            for (const [cname, , , tr] of commandLabels) lines.push(`      ${cname}: ${yamlValue(tr[lang])}`);
        }
    }
    return { code: lines.join('\n') + '\n', problems };
}

/** The Mode tab's defaults: a new mode. */
export function defaultInfo() {
    return {
        id: 'org.club.my-mode', version: '0.1.0', name: 'My mode', description: '', name_pt: '',
        description_pt: '', name_de: '', description_de: '', name_zh_tw: '',
        description_zh_tw: '', kind: 'mode', roles: [{ name: 'zone', inputs: null, needed: true }],
        license: 'GPL-3.0-or-later', min_tier: 'reduced', author: 'The Atalaia contributors',
        year: String(new Date().getFullYear()),
    };
}

/**
 * The boxes the editor's Test starts the simulator with: `count` boxes, one for each role but
 * the last and the rest for the last (Master and Satellites: master1, satellite1, satellite2),
 * at least one per role. Names are the role and a number, at most 24 characters.
 */
export function testNodes(info, count) {
    const names = [...new Set(modeRoles(info).map((r) => r.name).filter((n) => luaName(n)))];
    if (!names.length) names.push('zone');
    const total = Math.min(16, Math.max(names.length, count));
    const nodes = {};
    names.forEach((role, i) => {
        const n = i < names.length - 1 ? 1 : total - (names.length - 1);
        for (let k = 1; k <= n; k++) nodes[`${role.slice(0, 20)}${k}`] = role;
    });
    return nodes;
}

/**
 * Every file of a project, from its saved form ({ format, mode, node, field }) in headless
 * workspaces: { node_lua, field_lua, mode_yaml, problems }. The editor and the tests share it.
 */
export function generateProject(Blockly, g, project) {
    const info = { ...defaultInfo(), ...(project.mode || {}) };
    if (project.mode && !Array.isArray(project.mode.roles)) info.roles = modeRoles(project.mode);
    const screens = Object.keys(project.screens || {});
    const load = (state) => {
        const ws = new Blockly.Workspace();
        if (state) Blockly.serialization.workspaces.load(state, ws);
        return ws;
    };
    const nodeWs = load(project.node);
    const fieldWs = load(project.field);
    try {
        return generateWorkspaces(g, info, nodeWs, fieldWs, screens);
    } finally {
        nodeWs.dispose();
        fieldWs.dispose();
    }
}

/** Every file from the two live (or headless) workspaces; `screens`: the names of the mode's own. */
export function generateWorkspaces(g, info, nodeWs, fieldWs, screens = []) {
    const node = generateScript(g, nodeWs, 'node', info, screens);
    const field = generateScript(g, fieldWs, 'field', info, screens);
    const manifest = generateManifest(info, nodeWs, fieldWs, [node, field]);
    return {
        node_lua: node.code,
        field_lua: field.code,
        mode_yaml: manifest.code,
        problems: [...manifest.problems, ...node.problems.map((p) => ({ ...p, script: 'node' })),
            ...field.problems.map((p) => ({ ...p, script: 'field' }))],
    };
}
