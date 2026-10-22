// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The editor's blocks (ADR-P5-1 as amended 2026-10-22, decision P5R-3): one block per call of
// the script API in core/src/script_api.c, for node scripts (node.lua, on every box) and field
// scripts (field.lua, on the field controller), plus a few of Blockly's own (logic, numbers,
// text, lists, variables, functions). generator.js turns them into Lua; toolbox() lists them
// for a script kind ('node' or 'field'). Plan phase 3 added geo (distances, zones, positions),
// the mode's GM commands and the mode commands a box gets, and screens by name.

/** Lua words that cannot name a memory value, a setting or a data key. */
const LUA_WORDS = new Set(('and break do else elseif end false for function goto if in local nil not or '
    + 'repeat return then true until while').split(' '));

/** A Lua name: lower case, digits and _, not a Lua word; null refuses the edit. */
export function luaName(text) {
    const name = String(text).trim();
    return /^[a-z_][a-z0-9_]*$/.test(name) && !LUA_WORDS.has(name) ? name : null;
}

/** A short reason word, or nothing. */
function reason(text) {
    return String(text).trim() === '' ? '' : luaName(text);
}

/** An event type: words of a-z, 0-9 and _ joined by dots (team_input.hold, x.club.thing). */
function eventType(text) {
    const type = String(text).trim();
    return /^[a-z0-9_]+(\.[a-z0-9_]+)*$/.test(type) ? type : null;
}

/** What may follow "when" on each kind of script: [message key, event type]. */
export const EVENTS = {
    node: [
        ['ev_game_start', 'game.start'], ['ev_game_end', 'game.end'],
        ['ev_hold', 'team_input.hold'], ['ev_press', 'team_input.press'],
        ['ev_release', 'team_input.release'], ['ev_keypad', 'keypad.key'], ['ev_nfc', 'nfc.tag'],
        ['ev_set_owner', 'cmd.set_owner'], ['ev_cmd_mode', 'cmd.mode'],
        ['ev_rebooted', 'node.rebooted'], ['ev_gps', 'gps.fix'], ['ev_hit', 'hit.hit'],
    ],
    field: [
        ['ev_game_start', 'game.start'], ['ev_game_end', 'game.end'],
        ['ev_captured', 'zone.captured'], ['ev_neutralized', 'zone.neutralized'],
        ['ev_node_rebooted', 'node.rebooted'], ['ev_position', 'position.fix'],
    ],
};

/** The event's values the dropdown offers: [message key, data key]. */
const EVENT_KEYS = [
    ['key_team', 'team'], ['key_squad', 'squad'], ['key_ms', 'ms'], ['key_key', 'key'],
    ['key_uid', 'uid'], ['key_node', 'node'], ['key_previous_team', 'previous_team'],
    ['key_name', 'name'], ['key_lat', 'lat'], ['key_lon', 'lon'], ['key_acc', 'acc'],
    ['key_player', 'player'], ['key_role', 'role'], ['key_strength', 'strength'],
];

/** The box's own screens (firmware/esp32/main/screen_renderer.c), which a mode may show without a file. */
export const BUILTIN_SCREENS = ['neutral', 'captured', 'countdown', 'standby', 'code_entry', 'defused', 'exploded',
    'final_score'];

/** The most points a polygon zone may have (ATALAIA_GEO_POLYGON_MAX in core/include/atalaia/geo.h). */
export const POLYGON_MAX = 32;

const HUE = {
    events: 30, timers: 200, memory: 290, game: 350, score: 60, box: 160, settings: 330, field: 120, geo: 180,
    commands: 20,
};

const PAIR = 'AtalaiaPair';
const PAIR_ITEM = 'AtalaiaStateItem';
const POINT = 'AtalaiaPoint';
const ZONE = 'AtalaiaZone';

/** A list of role names separated by commas (medic, terminal), or null. */
function roleList(text) {
    const names = String(text).split(',').map((r) => r.trim()).filter(Boolean);
    return names.length && names.every((r) => luaName(r)) ? names.join(', ') : null;
}

/** A command name: 1-24 of a-z, 0-9 and _, starting with a letter (mode.yaml commands:). */
export function commandName(text) {
    const name = String(text).trim();
    return /^[a-z][a-z0-9_]{0,23}$/.test(name) ? name : null;
}

/** A text field that keeps only what the validator accepts. */
function nameField(name, text, check = luaName) {
    return { type: 'field_input', name, text, spellcheck: false, validator: check };
}

function definitions(t) {
    const options = (pairs) => pairs.map(([key, value]) => [t(key) || value, value]);
    const statement = (def) => ({ previousStatement: null, nextStatement: null, ...def });
    const value = (def) => ({ output: null, ...def });
    const doInput = { type: 'input_statement', name: 'DO' };
    return [
        // ---- memory: state.node{} and state.field{} ----
        {
            type: 'atalaia_state_node', message0: t('state_node'), message1: '%1',
            args1: [{ type: 'input_statement', name: 'ITEMS', check: PAIR_ITEM }],
            colour: HUE.memory, tooltip: t('state_node_tip'),
        },
        {
            type: 'atalaia_state_field', message0: t('state_field'), message1: '%1',
            args1: [{ type: 'input_statement', name: 'ITEMS', check: PAIR_ITEM }],
            colour: HUE.memory, tooltip: t('state_field_tip'),
        },
        {
            type: 'atalaia_state_item', message0: t('state_item'),
            args0: [nameField('KEY', 'owner'), { type: 'input_value', name: 'VALUE' }],
            previousStatement: PAIR_ITEM, nextStatement: PAIR_ITEM,
            colour: HUE.memory, tooltip: t('state_item_tip'),
        },
        value({
            type: 'atalaia_state_get', message0: t('state_get'), args0: [nameField('KEY', 'owner')],
            colour: HUE.memory, tooltip: t('state_get_tip'),
        }),
        statement({
            type: 'atalaia_state_set', message0: t('state_set'),
            args0: [nameField('KEY', 'owner'), { type: 'input_value', name: 'VALUE' }],
            colour: HUE.memory, tooltip: t('state_set_tip'),
        }),

        // ---- events: on(), emit() ----
        ...['node', 'field'].map((kind) => ({
            type: `atalaia_on_${kind}`, message0: t('on'),
            args0: [{ type: 'field_dropdown', name: 'EVENT', options: options(EVENTS[kind]) }],
            message1: '%1', args1: [doInput], colour: HUE.events, tooltip: t('on_tip'),
        })),
        {
            type: 'atalaia_on_custom', message0: t('on_custom'),
            args0: [nameField('EVENT', 'x.club.signal', eventType)],
            message1: '%1', args1: [doInput], colour: HUE.events, tooltip: t('on_custom_tip'),
        },
        value({
            type: 'atalaia_event_value', message0: t('event_value'),
            args0: [{ type: 'field_dropdown', name: 'KEY', options: options(EVENT_KEYS) }],
            colour: HUE.events, tooltip: t('event_value_tip'),
        }),
        value({
            type: 'atalaia_event_value_custom', message0: t('event_value_custom'),
            args0: [nameField('KEY', 'data')], colour: HUE.events, tooltip: t('event_value_custom_tip'),
        }),
        statement({
            type: 'atalaia_emit', message0: t('emit'),
            args0: [
                nameField('TYPE', 'zone.captured', eventType),
                {
                    type: 'field_dropdown', name: 'PRIO',
                    options: [[t('prio_default'), 'default'], [t('prio_critical'), 'critical'],
                        [t('prio_normal'), 'normal']],
                },
            ],
            message1: t('emit_with'), args1: [{ type: 'input_statement', name: 'DATA', check: PAIR }],
            colour: HUE.events, tooltip: t('emit_tip'),
        }),
        {
            type: 'atalaia_pair', message0: t('pair'),
            args0: [nameField('KEY', 'team'), { type: 'input_value', name: 'VALUE' }],
            previousStatement: PAIR, nextStatement: PAIR, colour: HUE.events, tooltip: t('pair_tip'),
        },

        // ---- timers: every(), after(), cancel() ----
        ...['every', 'after'].flatMap((name) => [
            statement({
                type: `atalaia_${name}`, message0: t(name),
                args0: [{ type: 'input_value', name: 'SECONDS', check: 'Number' }, { type: 'input_dummy' }],
                message1: '%1', args1: [doInput], colour: HUE.timers, tooltip: t(`${name}_tip`),
            }),
            statement({
                type: `atalaia_${name}_as`, message0: t(`${name}_as`),
                args0: [
                    { type: 'input_value', name: 'SECONDS', check: 'Number' },
                    { type: 'field_variable', name: 'TIMER', variable: 'timer' },
                    { type: 'input_dummy' },
                ],
                message1: '%1', args1: [doInput], colour: HUE.timers, tooltip: t(`${name}_as_tip`),
            }),
        ]),
        statement({
            type: 'atalaia_cancel', message0: t('cancel'),
            args0: [{ type: 'field_variable', name: 'TIMER', variable: 'timer' }],
            colour: HUE.timers, tooltip: t('cancel_tip'),
        }),

        // ---- game: game.win(), game.finish(), game.time(), game.teams(), return ----
        statement({
            type: 'atalaia_win', message0: t('win'), args0: [{ type: 'input_value', name: 'TEAM' }],
            colour: HUE.game, tooltip: t('win_tip'),
        }),
        statement({
            type: 'atalaia_finish', message0: t('finish'), args0: [nameField('REASON', 'time', reason)],
            colour: HUE.game, tooltip: t('finish_tip'),
        }),
        value({ type: 'atalaia_time', message0: t('time'), output: 'Number', colour: HUE.game, tooltip: t('time_tip') }),
        value({ type: 'atalaia_teams', message0: t('teams'), output: 'Array', colour: HUE.game, tooltip: t('teams_tip') }),
        {
            type: 'atalaia_return', message0: t('return'), previousStatement: null,
            colour: HUE.game, tooltip: t('return_tip'),
        },

        // ---- score: score.add(), score.get() ----
        statement({
            type: 'atalaia_score_add', message0: t('score_add'),
            args0: [
                { type: 'input_value', name: 'POINTS', check: 'Number' },
                { type: 'input_value', name: 'TEAM' },
                nameField('REASON', 'hold', reason),
            ],
            inputsInline: true, colour: HUE.score, tooltip: t('score_add_tip'),
        }),
        value({
            type: 'atalaia_score_get', message0: t('score_get'), args0: [{ type: 'input_value', name: 'TEAM' }],
            output: 'Number', colour: HUE.score, tooltip: t('score_get_tip'),
        }),

        // ---- the box's hardware: ui.screen(), audio.play(), cap("team_display") ----
        statement({
            type: 'atalaia_screen', message0: t('screen'), args0: [nameField('NAME', 'captured')],
            message1: t('screen_with'), args1: [{ type: 'input_statement', name: 'DATA', check: PAIR }],
            colour: HUE.box, tooltip: t('screen_tip'),
        }),
        statement({
            type: 'atalaia_sound', message0: t('sound'), args0: [nameField('CLIP', 'captured')],
            colour: HUE.box, tooltip: t('sound_tip'),
        }),
        statement({
            type: 'atalaia_team_display', message0: t('team_display'),
            args0: [{ type: 'input_value', name: 'TEAM' }], colour: HUE.box, tooltip: t('team_display_tip'),
        }),

        // ---- settings: params ----
        value({
            type: 'atalaia_param', message0: t('param'), args0: [nameField('NAME', 'tick_s')],
            colour: HUE.settings, tooltip: t('param_tip'),
        }),
        {
            type: 'atalaia_param_declare', message0: t('param_declare'),
            args0: [
                nameField('NAME', 'tick_s'),
                {
                    type: 'field_dropdown', name: 'TYPE',
                    options: options([['type_int', 'int'], ['type_bool', 'bool'], ['type_team', 'team'],
                        ['type_string', 'string']]),
                },
            ],
            message1: t('param_default'),
            args1: [
                { type: 'field_input', name: 'DEFAULT', text: '10', spellcheck: false },
                { type: 'field_input', name: 'MIN', text: '1', spellcheck: false },
                { type: 'field_input', name: 'MAX', text: '600', spellcheck: false },
            ],
            message2: t('param_label'), args2: [{ type: 'field_input', name: 'LABEL', text: 'Seconds per tick' }],
            message3: t('param_label_pt'), args3: [{ type: 'field_input', name: 'LABEL_PT', text: '' }],
            colour: HUE.settings, tooltip: t('param_declare_tip'),
        },

        // ---- utilities: rand(), log(), // ----
        value({
            type: 'atalaia_rand', message0: t('rand'),
            args0: [{ type: 'input_value', name: 'FROM', check: 'Number' }, { type: 'input_value', name: 'TO', check: 'Number' }],
            inputsInline: true, output: 'Number', colour: 230, tooltip: t('rand_tip'),
        }),
        statement({
            type: 'atalaia_log', message0: t('log'), args0: [{ type: 'input_value', name: 'TEXT' }],
            colour: 160, tooltip: t('log_tip'),
        }),
        value({
            type: 'atalaia_idiv', message0: t('idiv'),
            args0: [{ type: 'input_value', name: 'A', check: 'Number' }, { type: 'input_value', name: 'B', check: 'Number' }],
            inputsInline: true, output: 'Number', colour: 230, tooltip: t('idiv_tip'),
        }),

        // ---- geo: geo.distance(), geo.in_zone(), zones, positions (ADR-P4-9) ----
        value({
            type: 'atalaia_geo_distance', message0: t('geo_distance'),
            args0: ['LAT1', 'LON1', 'LAT2', 'LON2'].map((name) => ({ type: 'input_value', name, check: 'Number' })),
            inputsInline: true, output: 'Number', colour: HUE.geo, tooltip: t('geo_distance_tip'),
        }),
        value({
            type: 'atalaia_geo_in_zone', message0: t('geo_in_zone'),
            args0: [
                { type: 'input_value', name: 'LAT', check: 'Number' },
                { type: 'input_value', name: 'LON', check: 'Number' },
                { type: 'input_value', name: 'ZONE', check: ZONE },
            ],
            inputsInline: true, output: 'Boolean', colour: HUE.geo, tooltip: t('geo_in_zone_tip'),
        }),
        value({
            type: 'atalaia_geo_circle', message0: t('geo_circle'),
            args0: ['LAT', 'LON', 'RADIUS'].map((name) => ({ type: 'input_value', name, check: 'Number' })),
            inputsInline: true, output: ZONE, colour: HUE.geo, tooltip: t('geo_circle_tip'),
        }),
        value({
            type: 'atalaia_geo_polygon', message0: t('geo_polygon'),
            message1: '%1', args1: [{ type: 'input_statement', name: 'POINTS', check: POINT }],
            output: ZONE, colour: HUE.geo, tooltip: t('geo_polygon_tip'),
        }),
        {
            type: 'atalaia_geo_point', message0: t('geo_point'),
            args0: [{ type: 'input_value', name: 'LAT', check: 'Number' }, { type: 'input_value', name: 'LON', check: 'Number' }],
            inputsInline: true, previousStatement: POINT, nextStatement: POINT, colour: HUE.geo, tooltip: t('geo_point_tip'),
        },
        value({
            type: 'atalaia_event_has_position', message0: t('event_has_position'),
            output: 'Boolean', colour: HUE.geo, tooltip: t('event_has_position_tip'),
        }),

        // ---- GM commands (mode.yaml commands:) and the mode commands a box gets (cmd.mode) ----
        {
            type: 'atalaia_command_declare', message0: t('command_declare'),
            args0: [nameField('NAME', 'refill', commandName), nameField('ROLES', 'zone', roleList)],
            message1: t('param_label'), args1: [{ type: 'field_input', name: 'LABEL', text: 'Refill' }],
            message2: t('param_label_pt'), args2: [{ type: 'field_input', name: 'LABEL_PT', text: '' }],
            colour: HUE.commands, tooltip: t('command_declare_tip'),
        },
        {
            type: 'atalaia_on_command', message0: t('on_command'),
            args0: [nameField('NAME', 'refill', commandName)],
            message1: '%1', args1: [doInput], colour: HUE.events, tooltip: t('on_command_tip'),
        },

        // ---- field.* (field scripts only) ----
        value({
            type: 'atalaia_field_ids', message0: t('field_ids'), args0: [nameField('ROLE', 'zone')],
            output: 'Array', colour: HUE.field, tooltip: t('field_ids_tip'),
        }),
        value({
            type: 'atalaia_field_owner', message0: t('field_owner'), args0: [{ type: 'input_value', name: 'NODE' }],
            colour: HUE.field, tooltip: t('field_owner_tip'),
        }),
        value({
            type: 'atalaia_field_common_owner', message0: t('field_common_owner'),
            args0: [{ type: 'input_value', name: 'NODES', check: 'Array' }],
            colour: HUE.field, tooltip: t('field_common_owner_tip'),
        }),
        statement({
            type: 'atalaia_field_send', message0: t('field_send'),
            args0: [nameField('CMD', 'set_owner'), { type: 'input_value', name: 'NODE' }],
            message1: t('field_send_with'), args1: [{ type: 'input_statement', name: 'DATA', check: PAIR }],
            colour: HUE.field, tooltip: t('field_send_tip'),
        }),
        statement({
            type: 'atalaia_field_send_mode', message0: t('field_send_mode'),
            args0: [nameField('NAME', 'status', commandName), { type: 'input_value', name: 'NODE' }],
            message1: t('field_send_with'), args1: [{ type: 'input_statement', name: 'DATA', check: PAIR }],
            colour: HUE.field, tooltip: t('field_send_mode_tip'),
        }),
        value({
            type: 'atalaia_field_score', message0: t('field_score'), args0: [{ type: 'input_value', name: 'TEAM' }],
            output: 'Number', colour: HUE.field, tooltip: t('field_score_tip'),
        }),
    ];
}

/**
 * Registers every block with Blockly, its texts from t(key). A field's validator cannot be
 * given in JSON, so each block's init sets the validators its definition names.
 */
export function defineBlocks(Blockly, t) {
    for (const def of definitions(t)) {
        const checks = [];
        for (const args of [def.args0, def.args1, def.args2, def.args3]) {
            for (const arg of args || []) {
                if (arg.validator) {
                    checks.push([arg.name, arg.validator]);
                    delete arg.validator;
                }
            }
        }
        Blockly.Blocks[def.type] = {
            init() {
                this.jsonInit(def);
                for (const [name, check] of checks) this.getField(name).setValidator(check);
            },
        };
    }
}

const num = (n) => ({ shadow: { type: 'math_number', fields: { NUM: n } } });
const txt = (s) => ({ shadow: { type: 'text', fields: { TEXT: s } } });

/**
 * The toolbox of one kind of script ('node' or 'field'), category names from t(key). `screens`:
 * the names of the mode's own screens (assets/screens/), offered with the box's built-in ones.
 */
export function toolbox(kind, t, screens = []) {
    const category = (key, colour, contents) => ({ kind: 'category', name: t(key), colour, contents });
    const block = (type, inputs, fields) => ({ kind: 'block', type, ...(inputs ? { inputs } : {}), ...(fields ? { fields } : {}) });
    const events = [
        block(`atalaia_on_${kind}`), block('atalaia_on_custom'), block('atalaia_event_value'),
        block('atalaia_event_value_custom'), block('atalaia_emit'), block('atalaia_pair'),
    ];
    const memory = [
        block(kind === 'field' ? 'atalaia_state_field' : 'atalaia_state_node'),
        block('atalaia_state_item', { VALUE: { shadow: { type: 'logic_null' } } }),
        block('atalaia_state_get'), block('atalaia_state_set'),
    ];
    const timers = [
        block('atalaia_every', { SECONDS: num(10) }), block('atalaia_after', { SECONDS: num(5) }),
        block('atalaia_every_as', { SECONDS: num(10) }), block('atalaia_after_as', { SECONDS: num(5) }),
        block('atalaia_cancel'),
    ];
    const game = [
        block('atalaia_win'), block('atalaia_finish'), block('atalaia_time'), block('atalaia_teams'),
        block('atalaia_return'), block('atalaia_log', { TEXT: txt('') }),
    ];
    const score = [
        block('atalaia_score_add', { POINTS: num(1) }), block('atalaia_score_get'),
        ...(kind === 'field' ? [block('atalaia_field_score')] : []),
    ];
    const screenNames = [...new Set([...screens, ...BUILTIN_SCREENS])];
    const box = [
        ...screenNames.map((name) => block('atalaia_screen', null, { NAME: name })),
        block('atalaia_sound'), block('atalaia_team_display', { TEAM: txt('red') }),
    ];
    const field = [
        block('atalaia_field_ids'), block('atalaia_field_owner'), block('atalaia_field_common_owner'),
        block('atalaia_field_send'), block('atalaia_field_send_mode'),
    ];
    const geo = [
        block('atalaia_geo_in_zone', { LAT: { block: { type: 'atalaia_event_value', fields: { KEY: 'lat' } } },
            LON: { block: { type: 'atalaia_event_value', fields: { KEY: 'lon' } } } }),
        block('atalaia_geo_circle', { LAT: num(38.7), LON: num(-9.1), RADIUS: num(25) }),
        block('atalaia_geo_polygon'), block('atalaia_geo_point', { LAT: num(38.7), LON: num(-9.1) }),
        block('atalaia_geo_distance'), block('atalaia_event_has_position'),
    ];
    const commands = [block('atalaia_command_declare'), block('atalaia_on_command')];
    const settings = [block('atalaia_param'), block('atalaia_param_declare')];
    const logic = [
        block('controls_if'), { kind: 'block', type: 'controls_if', extraState: { hasElse: true } },
        block('logic_compare'),
        block('logic_operation'), block('logic_negate'), block('logic_boolean'), block('logic_null'),
        block('logic_ternary'), block('controls_forEach'),
    ];
    const math = [
        block('math_number'), block('math_arithmetic', { A: num(1), B: num(1) }),
        block('atalaia_idiv', { A: num(10), B: num(3) }), block('math_round', { NUM: num(3.1) }),
        block('atalaia_rand', { FROM: num(1), TO: num(6) }),
    ];
    const text = [block('text'), block('text_join')];
    const lists = [block('lists_length'), block('lists_create_with'), block('lists_getIndex')];
    return {
        kind: 'categoryToolbox',
        contents: [
            category('cat_events', HUE.events, events),
            category('cat_timers', HUE.timers, timers),
            category('cat_memory', HUE.memory, memory),
            category('cat_game', HUE.game, game),
            category('cat_score', HUE.score, score),
            ...(kind === 'node' ? [category('cat_box', HUE.box, box)] : [category('cat_field', HUE.field, field)]),
            category('cat_geo', HUE.geo, geo),
            ...(kind === 'node' ? [category('cat_commands', HUE.commands, commands)] : []),
            category('cat_settings', HUE.settings, settings),
            { kind: 'sep' },
            category('cat_logic', 210, logic),
            category('cat_math', 230, math),
            category('cat_text', 160, text),
            category('cat_lists', 260, lists),
            { kind: 'category', name: t('cat_variables'), colour: 330, custom: 'VARIABLE' },
            { kind: 'category', name: t('cat_functions'), colour: 290, custom: 'PROCEDURE' },
        ],
    };
}
