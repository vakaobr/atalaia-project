// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// English (strings.dart).
library;

const Map<String, String> enStrings = {
  // Common
  'common.cancel': 'Cancel',
  'common.close': 'Close',
  'common.clear': 'Clear the text',
  'common.ok': 'OK',
  'common.save': 'Save',

  // Home and roles
  'home.choose': 'What will this phone do?',
  'home.no_prop':
      'This phone cannot be a game prop: only Android can (it needs kiosk '
      'mode, background NFC and USB).',
  'role.prop': 'Game prop',
  'role.prop_hint':
      'This phone acts as a box: it runs the game mode, with team buttons on '
      'the screen, NFC tags and an optional I/O pod.',
  'role.player': 'Player',
  'role.player_hint':
      'Follow the game: time, scores, objectives, lives and messages from '
      'the game master.',
  'role.marshal': 'Marshal',
  'role.marshal_hint':
      'Chrono check-in and spot checks, the replica registry and players\' '
      'tags.',
  'role.gm': 'Game master',
  'role.gm_hint': "The game master's console, served by the field controller.",
  'role.controller': 'Field controller',
  'role.controller_hint':
      'This phone runs the game with no Raspberry Pi: the console, check-in '
      'and the boxes through an I/O pod.',

  // Settings
  'settings.title': 'Settings',
  'settings.language': 'Language',
  'settings.lang_pt': 'Português',
  'settings.lang_en': 'English',
  'settings.lang_de': 'Deutsch',
  'settings.lang_zh-tw': '中文（台灣）',
  'settings.theme': 'Look',
  'settings.theme_system': 'System',
  'settings.theme_dark': 'Dark',
  'settings.theme_light': 'Light (sun)',
  'settings.field': 'Field',
  'settings.join_key': 'Field join key',
  'settings.join_key_none': 'Not set: without it you cannot join games.',
  'settings.join_key_set': 'Set (ends in …{end})',
  'settings.join_key_hint':
      'The 64 hex digits the field controller prints with '
      '"python3 -m atalaia_controller join-key". They prove a join card or QR '
      'code belongs to this field.',
  'settings.join_key_bad': 'The join key is 64 hex digits (0-9, a-f).',
  'settings.join_key_clear': 'Clear',
  'settings.pin': 'Admin PIN',
  'settings.pin_none': 'No PIN: anyone can pause or end a game on this prop.',
  'settings.pin_set': 'Set: asked to start, pause, end and leave.',
  'settings.pin_hint': '4 to 8 digits.',
  'settings.pin_remove': 'Remove the PIN',
  'settings.kiosk': 'Kiosk mode',
  'settings.kiosk_hint':
      'During a game the phone is pinned to the app. If someone gets out, the '
      'app warns.',
  'settings.vibrate': 'Vibrate on game events',
  'settings.vibrate_hint':
      'A short buzz for a message from the game master, a box of your team '
      'captured or lost, the game starting or ending, the next box becoming '
      'active in Progressive Domination, and new orders (an objective or '
      "your squad leader's). No sound. The phone's own silent settings apply.",
  'settings.about': 'About',
  'settings.version': 'Atalaia {version}',
  'settings.core': 'Game core {version}',
  'settings.no_core': 'No game core on this phone.',
  'settings.licence': 'Licence',
  'settings.licence_text':
      'Free software: GPL-3.0 or later, with the additional permission for '
      'app stores (APP-STORE-PERMISSION.md).',
  'pin.title': 'Admin PIN',
  'pin.wrong': 'Wrong PIN.',

  // Battery
  'battery.title': 'Battery and background',
  'battery.intro':
      'During a game, Android may stop apps in the background to save '
      'battery. For a prop to last hours of play, take Atalaia out of battery '
      'optimisation.',
  'battery.exempt': 'Atalaia is already out of battery optimisation.',
  'battery.not_exempt':
      'Atalaia is still under battery optimisation: Android may stop it '
      'during a game.',
  'battery.request': 'Ask for the exemption',
  'battery.open_settings': 'Open battery settings',
  'battery.on_samsung_title': 'Samsung',
  'battery.on_samsung':
      'Settings › Battery › Background usage limits: take Atalaia out of the '
      'sleeping apps. Then Settings › Apps › Atalaia › Battery › Unrestricted.',
  'battery.on_xiaomi_title': 'Xiaomi, Redmi, POCO',
  'battery.on_xiaomi':
      'Settings › Battery › App battery saver › Atalaia › No restrictions. In '
      'Security › Autostart, turn Atalaia on.',
  'battery.on_huawei_title': 'Huawei, Honor',
  'battery.on_huawei':
      'Settings › Battery › App launch › Atalaia: turn off automatic '
      'management and leave the three options on (auto-launch, secondary '
      'launch, run in background).',
  'battery.on_oneplus_title': 'OnePlus, OPPO, realme',
  'battery.on_oneplus':
      "Settings › Battery › Battery optimization › Atalaia › Don't optimize. "
      'On some models also: Settings › Apps › Atalaia › Battery usage › Allow '
      'background activity.',
  'battery.on_generic_title': 'Other phones',
  'battery.on_generic':
      'Settings › Apps › Atalaia › Battery: choose "Unrestricted" or "Don\'t '
      'optimize". The names differ between makers.',

  // Prop
  'prop.intro':
      "A new game on this phone alone, or one of the field controller's "
      'games (with the join card or QR code the game master makes).',
  'prop.new_game': 'New game',
  'prop.join': 'Join a game',
  'prop.capabilities': 'What this phone has',
  'prop.start': 'Start',
  'prop.confirm_start': 'Start the game now?',
  'prop.pause': 'Pause',
  'prop.resume': 'Resume',
  'prop.end': 'End the game',
  'prop.confirm_end': 'End the game now?',
  'prop.leave': 'Leave',
  'prop.confirm_leave': 'Leave the game?',
  'prop.confirm_leave_body':
      'The game is still running: this prop stops counting.',
  'prop.log': 'Game log',
  'prop.admin': 'Game master',
  'prop.loading': 'Loading the mode…',
  'prop.waiting': 'Waiting for the start',
  'prop.paused': 'PAUSED',
  'prop.paused_hint': 'Wait for the game master.',
  'prop.ended': 'Game over',
  'prop.script_error': 'The mode stopped',
  'prop.tamper':
      'Someone left kiosk mode during the game. Tell the game master.',
  'prop.pod_opened':
      'Someone opened the I/O pod during the game. Tell the game master.',
  'prop.pod_reconnecting': 'The I/O pod link was lost. Reconnecting (try {n})…',
  'prop.pod_refused':
      'A different pod answered, so the I/O pod is not linked any more. Link a pod again.',
  'prop.pod_unlink': 'Unlink the I/O pod',
  'prop.hold': 'Hold\n{team}',
  'prop.nfc_hint': 'Hold the tag to the back of the phone.',
  'prop.keypad': 'Keypad',
  'prop.keypad_hide': 'Hide the keypad',
  'prop.phase_loading': 'loading',
  'prop.phase_ready': 'ready to start',
  'prop.phase_running': 'running',
  'prop.phase_paused': 'paused',
  'prop.phase_ended': 'ended',
  'prop.phase_halted': 'stopped by an error',
  'prop.phase_failed': 'did not start',
  'prop.notification_title': 'Atalaia: {mode}',
  'prop.notification_running': 'Game running',
  'prop.notification_left': '{time} left',

  // Setup
  'setup.title': 'New game',
  'setup.joined': "Controller's game",
  'setup.join_info':
      'Game {game}, this prop is node {node}, channel {mhz} MHz.',
  'setup.mode': 'Game mode',
  'setup.with': 'With {mode}',
  'setup.role': 'Role in the mode',
  'setup.teams': 'Teams',
  'setup.params': "The mode's parameters",
  'setup.any_team': 'Every team',
  'setup.length': 'Length',
  'setup.minutes': 'Minutes',
  'setup.minutes_hint': '0 = no limit. At the end, the game ends by itself.',
  'setup.prepare': 'Prepare the game',
  'setup.missing': 'This phone lacks: {caps}. Link an I/O pod that has it.',
  'setup.needs_controller':
      'This mode scores across several boxes through the field controller. '
      'On its own, this prop only does its own part.',
  'setup.unknown_mode': "This prop does not have this game's mode.",
  'setup.unknown_role': "This game's mode has no such role.",

  // Join
  'join.intro':
      "Scan the join QR code on the game master's console, hold the join card "
      'to the phone, or paste the atalaia:join:… text.',
  'join.scan': 'Scan the QR code',
  'join.scan_hint': 'Point at the join QR code.',
  'join.card': 'Join card (NFC)',
  'join.card_ready': 'Hold the card to the back of the phone.',
  'join.text': 'Join text',
  'join.use_text': 'Use this text',
  'join.warning':
      'The card and the code carry the game key: show them only to the people '
      'setting up the field.',
  'join.no_key': 'First set the field join key in the settings.',
  'join.no_camera': 'There is no camera to read the code.',
  'join.bad_text': 'This is not a valid join code.',
  'join.not_a_card': 'This card has no join data.',
  'join.other_field':
      'This code is from another field (the join key does not match).',
  'join.bad_body': 'The join data is damaged.',
  'join.for_controller': 'This code is for a standby controller, not a prop.',
  'nfc.off': "NFC is off: turn it on in the phone's settings.",
  'nfc.none': 'This phone has no NFC.',

  // I/O pod
  'pod.title': 'I/O pod',
  'pod.intro':
      'An I/O pod lends big buttons, lights, a siren, an NFC reader and a LoRa '
      'radio to the phone, over USB (preferred) or Bluetooth.',
  'pod.none': 'No pod linked: the game uses the phone alone.',
  'pod.link': 'Link a pod',
  'pod.find': 'Find pods',
  'pod.found_none': 'No pod found.',
  'pod.linked': 'Pod linked over {kind}: firmware {fw}, {n} capabilities.',
  'pod.open_failed': 'Could not open the link to the pod.',
  'pod.no_ident': 'The pod did not answer.',
  'pod.reconnecting': 'The link to the pod was lost. Reconnecting (try {n})…',
  'pod.refused':
      'A different pod answered, so the link was not restored. Link a pod again.',
  'pod.unlink': 'Unlink the pod',

  // Capabilities
  'cap.team_input': 'team buttons',
  'cap.keypad': 'keypad',
  'cap.display': 'screen',
  'cap.team_display': 'team colour',
  'cap.led': 'lights',
  'cap.audio': 'sound',
  'cap.haptic': 'vibration',
  'cap.nfc': 'NFC',
  'cap.gps': 'GPS',
  'cap.imu': 'accelerometer',
  'cap.qr_scanner': 'QR reader',
  'cap.button': 'buttons',
  'cap.lora': 'LoRa radio',

  // Teams
  'team.red': 'red',
  'team.blue': 'blue',
  'team.green': 'green',
  'team.yellow': 'yellow',
  'team.orange': 'orange',
  'team.purple': 'purple',

  // Player
  'player.intro':
      "Connect to the field controller: scan the scoreboard's QR code, or "
      'type the address and the access code the game master gave you.',
  'player.scan': "Scan the scoreboard's QR code",
  'player.scan_hint': "Point at the scoreboard's QR code.",
  'player.by_hand': 'Or type them',
  'player.address': "Controller's address",
  'player.code': 'Access code',
  'player.connect': 'Connect',
  'code.is_poster':
      "This is a field's check-in poster. Use it under Player > Check in at "
      'the field.',
  'code.is_join_card':
      'This is a join code for a game prop. Use it under Game prop > Join a '
      'game.',
  'code.is_site_link':
      "This is a link to a field's online registration. Use it under Player "
      '> Online registration.',
  'code.is_scoreboard':
      "This is a game scoreboard's link. Use it under Player > Follow a game "
      'without checking in.',
  'player.bad_link': 'The address or the access code is missing.',
  'player.link_unreachable':
      'The controller does not answer. Are you on the field\'s Wi-Fi?',
  'player.link_mismatch':
      'The controller answering is not the one this code was made for. Do not go on, and tell the organisers.',
  'player.link_not_controller':
      'What answers at this address is not a field controller.',
  'player.connecting': 'Connecting to the field controller…',
  'player.offline': 'Offline. Reconnecting…',
  'player.denied': 'The access code was refused.',
  'player.no_game': 'No game is running yet.',
  'player.left': 'to go',
  'player.score': 'Score',
  'player.my_team': 'your team',
  'player.pick_team': 'Tap your team to highlight it.',
  'player.eliminated': 'eliminated',
  'player.lives_left': '{n} lives',
  'player.objectives': 'Objectives',
  'player.node': 'Box {n}',
  'player.held_by': 'Held by {team}',
  'player.held_by_none': 'Held by nobody',
  'player.active_box': 'Active box: {zone}',
  'player.active_box_tag': 'ACTIVE',
  'player.scenario': 'Scenario objectives',
  'player.objective_waiting': 'Starts with the game',
  'player.objective_active': 'In progress',
  'player.objective_done': 'Completed by {team}',
  'player.objective_done_no_team': 'Completed',
  'player.objective_failed': 'Failed',
  'player.objective_failed_captured': 'Failed: taken by another team',
  'player.objective_failed_defused': 'Failed: the bomb was defused',
  'player.objective_failed_time': 'Failed: out of time',
  'player.objective_failed_blocked': 'Failed: an earlier objective failed',
  'player.objective_failed_lives': 'Failed: too few lives left',
  'player.objective_for_team': 'For {team}',
  'player.objective_for_squad': 'For {team}, squad {squad}',
  'player.objective_points': '+{n}',
  'player.lives': 'Lives',
  'player.events': 'What happened',
  'player.no_events': 'Nothing yet.',
  'player.message': 'Game master: {text}',
  'player.ended': 'The game is over.',
  'player.tie': 'Tie',
  'player.winner': '{team} team wins',
  'state.ready': 'ready',
  'state.running': 'running',
  'state.paused': 'paused',
  'state.ended': 'ended',

  // Events
  'event.game.start': 'The game started',
  'event.game.pause': 'Game paused',
  'event.game.resume': 'The game resumed',
  'event.game.end': 'The game ended',
  'event.zone.captured': '{team} captured {zone}',
  'event.zone.neutralized': '{zone} is neutral',
  'event.bomb.armed': 'Bomb armed by {team} ({fuse} s)',
  'event.bomb.defused': 'Bomb defused by {team}',
  'event.bomb.exploded': 'The bomb exploded',
  'event.bomb.reset': 'The bomb was reset',
  'event.score.delta': 'Points for {team}: {amount}',
  'event.code.used': '{team} used a code',
  'event.player.respawn': '{player} is back in ({lives} lives)',
  'event.player.checkin': '{player} checked in',
  'event.kill.confirmed': 'Kill confirmed by {team} ({player})',
  'event.kill.denied': "{team} recovered {player}'s tag",
  'event.team.eliminated': '{team} has no lives left',
  'event.holdall.scoring_start': '{team} holds every zone',
  'event.holdall.scoring_stop': '{team} lost a zone',
  'event.laststand.countdown_start': 'Last stand: the countdown started',
  'event.laststand.countdown_cancel': 'Last stand: countdown cancelled',
  'event.laststand.defeated': 'Last stand: the defence fell',
  'event.gm.message': 'Game master: {text}',
  'event.visibility.granted': '{team} sees the field',
  'event.chrono.violation': 'A replica above the limit',
  'event.node.tamper': 'Someone tampered with a box ({reason})',
  'event.medic.heal':
      '{player} was healed (heals left in the kit: {remaining})',
  'event.medic.empty': 'A medic kit is empty',
  'event.hacking.solved': '{team} hacked a terminal',
  'event.hacking.solved.no_team': 'A terminal was hacked',
  'event.vip.extracted': '{team} reached the extraction zone',
  'event.money.collected': '{player} collected {amount} money',
  'event.money.deposited': '{player} banked {amount} for {team}',
  'event.progressive.activated':
      'Box {zone} is active now (number {step}): the only one that can be captured',
  'event.progressive.completed': '{team} completed box {zone} (number {step})',
  'event.scenario.started': 'The scenario has started',
  'event.scenario.objective.completed': '{team} completed an objective',
  'event.scenario.objective.completed.no_team': 'An objective was completed',
  'event.scenario.objective.failed': '{team} failed an objective',
  'event.scenario.objective.failed.no_team': 'An objective failed',
  'event.scenario.objective.revealed': 'A new objective for {team}',
  'event.scenario.objective.revealed.no_team': 'A new objective',
  'event.scenario.objective.completed.named': '{team} completed: {objective}',
  'event.scenario.objective.completed.named.no_team': 'Completed: {objective}',
  'event.scenario.objective.failed.named': '{team} failed: {objective}',
  'event.scenario.objective.failed.named.no_team': 'Failed: {objective}',
  'event.scenario.objective.revealed.named':
      'A new objective for {team}: {objective}',
  'event.scenario.objective.revealed.named.no_team':
      'A new objective: {objective}',
  'event.scenario.objective.revealed.leader':
      'Your squad leader has new orders',
  'player.leader_orders':
      'Orders for your squad: your squad leader will pass them on',

  // GM
  'gm.intro':
      "The field controller's game master console. Type the controller's "
      'address; the console asks for the access code.',
  'gm.address': "Console's address",
  'gm.open': 'Open the console',
  'gm.bad_url': 'This address will not do.',
  'gm.change': 'Change the address',

  // Marshal
  'marshal.no_identity':
      'To record readings the field controller must confirm you as a marshal: '
      'check in at the field with the poster, and the organisers put you on '
      'their list. Your name and id come from that list, and your signing '
      'key is made for you.',
  'marshal.identity': 'Who you are',
  'marshal.name': "Marshal's name",
  'marshal.id': "Marshal's id",
  'marshal.field_id': "Field's id",
  'marshal.chrono_id': "Chronograph's id",
  'marshal.key': 'Signing key',
  'marshal.no_key': 'No key yet: readings must be signed.',
  'marshal.key_id': 'Public key {id}…',
  'marshal.new_key': 'New key',
  'marshal.new_key_body':
      'Old readings stay signed with the old key; new ones are signed with '
      'the new key.',
  'marshal.records': 'Stored readings',
  'marshal.readings':
      '{n} readings on this phone. They are kept for 365 days, then deleted.',
  'marshal.erase': "Erase someone's readings",
  'marshal.erase_do': 'Erase',
  'marshal.checking': 'Asking the field controller…',
  'marshal.you_are': 'You are marshal {id} ({name})',
  'marshal.id_from_gm':
      "The id and name come from the GM's marshal list; the field controller confirmed them.",
  'marshal.not_listed':
      'The field controller does not have you on its marshal list. Ask the GM to add you as a marshal.',
  'marshal.revoked':
      'The GM took you off the marshal list, so this phone is no longer a marshal here. The {n} series not yet sent stay on this phone and can be sent if the GM adds you again.',
  'marshal.offline_never':
      "The field controller cannot be reached, and this phone has not been confirmed as a marshal here yet. Join the field's network once and ask again.",
  'marshal.offline_expired':
      "The field controller cannot be reached, and its confirmation of {at} has run out. Join the field's network and ask again.",
  'marshal.offline_ok':
      "Offline: the field controller confirmed you as marshal {id} on {at}. That holds until {until}; after that, join the field's network to confirm again.",
  'marshal.retry': 'Ask again',
  'marshal.expired_now':
      "The field controller's confirmation has run out: ask again before recording.",

  // Chrono
  'chrono.title': 'Chronograph',
  'chrono.hint': "Check-in and spot checks, against the field's limit.",
  'chrono.template': "Field's limits",
  'chrono.template_set': 'Set by the field controller.',
  'chrono.template_local':
      'The field controller judges with its own list, and its verdict is the '
      'one that counts. This list is only for the preview on this phone.',
  'chrono.template_unknown':
      'The field controller uses the limits "{name}", which this app does '
      'not have. Its verdict is the one that counts; the figures here are '
      'only a guide.',
  'limits.portugal': 'Portugal',
  'limits.uk': 'United Kingdom',
  'limits.germany': 'Germany',
  'limits.generic_cqb': 'Generic CQB',
  'replica.class_rifle': 'Rifle',
  'replica.class_dmr': 'DMR',
  'replica.class_sniper': 'Sniper',
  'replica.class_cqb': 'CQB',
  'replica.class_semi': 'Semi-auto',
  'chrono.unverified':
      'The "{name}" limits are unverified: they come from the project\'s '
      'research, not an official source. Check them against current rules '
      'before use.',
  'chrono.checkin': 'Check-in',
  'chrono.spotcheck': 'Spot check',
  'chrono.replica': 'Replica',
  'chrono.replica_nfc': "Or hold the replica's tag to the phone.",
  'chrono.unknown_tag': 'This tag is not in the replica registry.',
  'chrono.no_class': 'The field\'s limits have no "{class}" class.',
  'chrono.limit': 'Limit: {j} J ({fps} fps with 0.20 g)',
  'chrono.bb': 'BB weight',
  'chrono.velocity': 'Velocity',
  'chrono.energy': 'Energy: {j} J',
  'chrono.record': 'Record the shot',
  'chrono.new_series': 'New series',
  'chrono.pass': 'PASS',
  'chrono.warn': 'WARN',
  'chrono.fail': 'FAIL',
  'chrono.highest': 'Highest: {j} J · limit {limit} J',
  'chrono.vs_checkin': 'At check-in: {j} J (+{pct}% tolerance)',

  // Replicas
  'replica.title': 'Replica registry',
  'replica.add': 'Register a replica',
  'replica.none': 'No replicas registered yet.',
  'replica.count': '{n} replicas registered',
  'replica.owner': "Player's id",
  'replica.type': 'Type',
  'replica.class': 'Class',
  'replica.model': 'Make and model',
  'replica.tag': "Replica's tag",
  'replica.tap_tag':
      "Hold the replica's NFC tag to the phone, or scan its QR label.",
  'replica.tag_read': 'Tag: {uid}',
  'replica.scan': 'Scan a QR label',
  'replica.scan_hint': "Point at the replica's QR label.",
  'replica.needs_tag': "The replica's class or tag is missing.",
  'replica.type_aeg': 'AEG',
  'replica.type_gbb': 'GBB',
  'replica.type_hpa': 'HPA',
  'replica.type_bolt_action': 'Bolt action',
  'replica.type_dmr': 'DMR',
  'replica.type_sniper': 'Sniper',
  'replica.type_pistol': 'Pistol',
  'replica.type_shotgun': 'Shotgun',

  // Tags
  'tags.title': "Players' tags",
  'tags.hint': 'Write the signed NFC tags for a game.',
  'tags.intro':
      "Tags are signed by the field controller, which keeps the game's key: "
      "you never need the field join key. Be on the field's Wi-Fi, type a "
      'player and hold a blank tag to the phone.',
  'tags.for_game': 'Game: {game}',
  'tags.loading': 'Asking the field controller…',
  'tags.offline':
      "The field controller cannot be reached: join the field's Wi-Fi and try "
      'again.',
  'tags.not_marshal':
      'The field controller says you are not a marshal here: ask the game '
      'master.',
  'tags.session': 'Your check-in has run out: check in again.',
  'tags.no_key':
      'The game is not running on the controller (it ended, or it lost the '
      "game's key), so it cannot sign tags.",
  'tags.refused': 'The field controller refused the tag: {error}',
  'tags.bad_answer':
      "The controller's answer is not a valid tag for this player.",
  'tags.player': "Player's id",
  'tags.player_hint': 'Letters, digits, - _ and . (up to 32), e.g. p-17',
  'tags.bad_player': 'The id is 1 to 32 letters, digits, -, _ or .',
  'tags.no_team': 'No team',
  'tags.write': 'Write the tag',
  'tags.hold': 'Hold the tag to the back of the phone…',
  'tags.written': 'Written just now',
  'tags.write_not_ndef': 'This tag does not take NDEF data.',
  'tags.write_read_only': 'This tag is locked.',
  'tags.write_too_small': 'The tag is too small.',
  'tags.write_io': 'Writing failed: keep the tag in place and try again.',
  'tags.write_unavailable': 'This phone does not write NFC tags.',

  // Field check-in, replicas to chrono, positions (plan phase E)
  'checkin.title': 'Check in at the field',
  'checkin.intro':
      'Scan the field\'s check-in poster with the camera (or paste its text). The phone reaches the field\'s controller over the field\'s Wi-Fi; no internet needed.',
  'checkin.scan': 'Scan the poster',
  'checkin.scan_hint': 'Point at the QR code on the check-in poster',
  'checkin.by_text': 'Or paste the poster\'s text',
  'checkin.text_hint': 'atalaia:checkin:…',
  'checkin.use_text': 'Use this text',
  'checkin.bad_poster':
      'This check-in poster cannot be read. Ask the organisers for another.',
  'checkin.not_poster': 'This is not an Atalaia check-in poster.',
  // Why the field controller did not answer (check-R5)
  'diag.title': 'Details',
  'diag.timeout': 'no answer in time',
  'diag.refused': 'connection refused',
  'diag.unreachable': 'no route to the address',
  'diag.tls': 'certificate not accepted',
  'diag.http': 'HTTP {status}',
  'diag.other': 'connection error',
  'diag.line': '{kind} · {url} · {time}',
  'checkin.unreachable':
      'The field\'s controller does not answer. Are you on the field\'s Wi-Fi?',
  'checkin.join_wifi':
      'The field\'s controller does not answer: join the Wi-Fi network “{ssid}” and try again.',
  'checkin.mismatch':
      'The controller answering is not the poster\'s (poster {poster}, controller {got}). Do not go on, and tell the organisers.',
  'checkin.not_controller':
      'What answers at this address is not a field controller.',
  'checkin.changed':
      'This field was trusted with another certificate ({old}); the poster shows {new}. If the organisers confirm the controller changed, forget the field and scan the poster again.',
  'checkin.forget_field': 'Forget this field',
  'checkin.error': 'The controller refused: {error}',
  'checkin.offline':
      'No connection to the field\'s controller: try again on the field\'s network.',
  'checkin.expired': 'This check-in is no longer valid: check in again.',
  'checkin.connecting': 'Connecting to the field\'s controller…',
  'checkin.notice_title': 'Your data at {field}',
  'checkin.notice_ok': 'I have read it, go on',
  'checkin.trusted': 'Field certificate {ca}',
  'checkin.no_games': 'No game is open for check-in at this field.',
  'checkin.game': 'Game',
  'checkin.for_game': 'Game: {game}',
  'checkin.name': 'Name or callsign',
  'checkin.name_hint':
      'The organisers and marshals see it; other players do not.',
  'checkin.federation_required': 'Federation number ({label})',
  'checkin.federation_optional': 'Federation number ({label}, optional)',
  'checkin.federation_hint':
      'The organisers look at the card at the desk; the app does not check it.',
  'checkin.need_name': 'Type a name or a callsign.',
  'checkin.need_federation':
      'This field asks for your federation number ({label}).',
  'checkin.pick_game': 'Pick the game.',
  'checkin.team_pref': 'Preferred team',
  'checkin.any_team': 'Any',
  'checkin.bring': 'Replicas you bring',
  'checkin.submit': 'Check in',
  'checkin.status_title': 'My check-in',
  'checkin.status.pending':
      'Waiting for confirmation at the organisers\' desk.',
  'checkin.status.checked_in': 'Checked in.',
  'checkin.status.left': 'You left this game.',
  'checkin.status.removed': 'The organisers removed this check-in.',
  'checkin.role.player': 'Player',
  'checkin.role.squad_leader': 'Squad leader',
  'checkin.role.vip': 'VIP',
  'checkin.role.marshal': 'Marshal',
  'checkin.role.gm': 'GM',
  'checkin.role.spectator': 'Spectator',
  'checkin.my_declaration': 'My replicas in this game',
  'checkin.no_replicas': 'You have not declared any replica yet.',
  'checkin.declare': 'Pick the replicas',
  'checkin.follow': 'Follow the game',
  'checkin.leave': 'Leave the game',
  'checkin.leave_body':
      'Your name and federation number are erased from this game. Replicas already chronographed stay on record.',
  'checkin.left': 'You left the game; your data was erased.',
  'chrono_state.pending': 'not chronographed',
  'chrono_state.passed': 'passed',
  'chrono_state.refused': 'refused',
  'chrono_state.withdrawn': 'withdrawn',
  'chrono_state.refused_today': 'refused today',
  'declare.title': 'Replicas for this game',
  'declare.intro':
      'Pick the replicas you will use in this game (up to {max}). Take them to the marshals for the chronograph.',
  'declare.none': 'No replicas yet: add yours.',
  'declare.add': 'Add a replica',
  'declare.type': 'Type',
  'declare.class': 'Class',
  'declare.make': 'Make and model (optional)',
  'declare.save': 'Save',
  'declare.saved': 'Saved: the organisers and marshals see them now.',
  'declare.locked':
      'A chronographed replica stays declared: ask a marshal to change it.',
  'queue.title': 'Replicas to chrono',
  'queue.hint':
      'The field\'s list: who declared replicas that have not been through the chronograph yet.',
  'queue.check_in_first':
      'Check in at the field with the poster first; the organisers then give you the marshal role.',
  'queue.not_marshal': 'This list is for marshals and the organisers only.',
  'queue.counts':
      'To chrono: {pending} · passed: {passed} · refused: {refused}',
  'queue.scan': 'Scan a replica\'s label',
  'queue.scan_hint': 'Point at the replica\'s QR label',
  'queue.not_found':
      'This replica is not declared in this game: pick the player\'s declaration.',
  'queue.refresh': 'Refresh',
  'queue.empty': 'Nobody has declared replicas yet.',
  'queue.manual': 'Check in by hand',
  'queue.manual_do': 'Check in',
  'queue.manual_done': 'Checked in: {id}',
  'queue.send_pending': 'Send {n} series not sent yet',
  'queue.send_failed': '{n} series were not accepted; they stay on this phone.',
  'queue.held':
      '{n} series were not accepted because the controller does not have you on its marshal list; they stay on this phone.',
  'queue.waiting_confirmation': 'waiting for confirmation',
  'queue.sticker_title': 'Use an NFC sticker?',
  'queue.sticker_body':
      "Hold the replica's NFC sticker to the phone to register it by the sticker, or use the printed QR label.",
  'queue.sticker_qr': 'Use the QR label',
  'queue.sticker_taken':
      'That sticker is already registered to another replica.',
  'queue.unregistered': 'not registered yet',
  'label.title': 'Replica label',
  'label.show': 'Show label',
  'label.share': 'Share / print label',
  'label.share_all': 'Share / print all labels',
  'label.share_title': 'Replica labels',
  'label.hint':
      'Stick this label on the replica. The marshal scans it to find the replica in the chrono queue. It holds only this code, nothing about you. It prints at 30 × 30 mm; several labels go on one A4 sheet.',
  'label.share_unavailable':
      'This phone cannot hand a file to the share sheet. Use Show label instead.',
  'label.share_failed': 'The share sheet did not open.',
  'label.none_yet':
      'The label shows here once you have declared this replica for a game.',
  'chrono.send': 'Send to the controller',
  'chrono.sent_pass': 'Sent: passed.',
  'chrono.sent_fail': 'Sent: refused.',
  'chrono.sent_warn': 'Sent: warning.',
  'chrono.sent_unjudged': 'Sent: no class to compare with.',
  'chrono.sent_null': 'Sent.',
  'chrono.send_failed':
      'Not sent: {error}. It stays on this phone to send later.',
  'player.checkin': 'Check in at the field',
  'player.watch': 'Follow a game without checking in',
  'player.continue': 'Continue: {game}',
  'player.me': 'You: {role}, {team}',
  'player.no_team': 'no team yet',
  'player.positions': 'Positions you see: {n}',
  'player.share': 'Share my position',
  'player.share_hint':
      'Only during the game; the controller decides who sees it. The organisers and the marshals see it on their ATAK devices.',
  'player.share_on': 'Sharing: {n} position(s) sent',
  'player.share_stopped':
      'Sharing stopped: the game ended or the check-in changed.',
  'player.no_location': 'This phone has no location.',
  'player.location_denied': 'No permission for the location.',
  'player.location_denied_ios':
      'No permission for the location. Allow it in Settings > Atalaia > Location (While Using the App), and check that Location Services is on.',
  'player.share_ios_note':
      'On iPhone your position is shared only while Atalaia is open on the screen: it pauses when you switch to another app or lock the phone, and goes on when you come back.',
  'player.sharing_title': 'Atalaia: sharing your position',
  'player.sharing_text': 'During the game',
  // The out-of-bounds warning (decisions MF-31 to MF-40)
  'player.out_title': 'Out of bounds',
  'player.out_text': 'You have left the field\'s boundary. Go back inside.',
  'player.bounds_watch':
      'This phone vibrates if you leave the field\'s boundary.',
  'prop.link.connecting': 'Connecting to the controller…',
  'prop.link.linked': 'Linked to the controller over Wi-Fi',
  'prop.link.refused': 'The controller refused this device (another game?)',
  'prop.link.offline': 'No connection to the controller: trying again…',
  'prop.link.closed': 'Another device took this one\'s place',
  'prop.radio.configuring': 'Setting up the pod\'s radio…',
  'prop.radio.linked': 'The pod\'s radio is on the field\'s channel',
  'prop.radio.heard': 'Linked to the controller over the pod\'s radio',
  'prop.radio.offline': 'The pod\'s radio is not answering: trying again…',
  'prop.radio.closed': 'The pod\'s radio is off',
  'prop.gm_message': 'Game master: {text}',
  // Indoor beacons (decisions BLE-1 to BLE-9)
  'player.beacons_why_title': 'Indoor positions',
  'player.beacons_why':
      'This field has Bluetooth beacons indoors. To tell which room you are in, Atalaia can listen for them while you share your position: only the field\'s own beacons, and it sends only which one is strongest. Android asks for the Bluetooth and location permissions for this. Without them your position stays GPS only.',
  'player.beacons_allow': 'Continue',
  'player.beacons_skip': 'Not now',
  'player.beacons_on':
      'Listening for the field\'s beacons: indoors your position is the room.',
  'player.beacons_skipped':
      'Indoor positions are off. Your GPS position is still shared.',
  'player.beacons_denied':
      'Indoor positions are off: no permission for Bluetooth. Your GPS position is still shared.',
  'player.beacons_off':
      'Indoor positions are off: Bluetooth is switched off. Switch it on and share again.',
  'player.beacons_unavailable':
      'This phone cannot listen for the field\'s beacons. Your GPS position is still shared.',
  'player.beacons_ios':
      'On iPhone the field\'s indoor beacons are not used yet: your position is GPS only.',
  'player.my_room': 'Your position: {room}',
  'player.map_title': 'Field map',
  'player.map_semantics': 'Map of the field, {level}: {n} positions',
  'player.map_off_plan': '{n} positions not on this plan',
  'player.map_level_unknown':
      'Hollow dots: players who have not said which floor they are on.',
  'player.map_level_unknown_short': 'floor not known',
  'player.map_cell': 'Your cell: {cell}',
  'player.map_you': 'You',
  'player.map_player': 'A player',
  'player.map_player_team': 'A player of {team}',
  'player.level_n': 'Level {n}',
  'player.level_title': 'Which floor are you on?',
  'player.level_unknown': 'Not sure',
  'player.level_hint':
      'Your team sees you on that floor. Your phone cannot tell floors apart by itself.',
  'player.level_beacon': 'Your floor comes from the room beacon: {level}.',
  'player.feature.safe_zone': 'Safe zone',
  'player.feature.respawn': 'Respawn',
  'player.feature.hq': 'Headquarters',
  'player.feature.parking': 'Parking',
  'player.feature.first_aid': 'First aid',
  'player.feature.objective': 'Objective',
  'player.feature.other': 'Other',
  'player.feature.boundary': 'Field boundary',
  'player.share_hint_squads':
      'Only during the game; the controller decides who sees it: your squad if the game allows it, and the organisers and the marshals on their ATAK devices.',
  'checkin.team_squad': '{team} › squad {squad}',
  'branding.logo': 'Logo of {name}',
  // Online registration on the field's site server (decision S16-13)
  'player.site': 'Online registration',
  'site.title': 'Online registration',
  'site.intro':
      'You register for a game with an account on the field\'s site. Use the '
      '"Register" button on the game\'s page, or paste the address of the '
      'field\'s or the game\'s page here.',
  'site.address': 'Address of the field\'s or the game\'s page',
  'site.open': 'Open',
  'site.bad_address':
      'This is not the address of a field or game page (https://…/f/…).',
  'site.confirm_text':
      'You are about to log in with your account at {host}. Only go on if it '
      'is the site of the field where you will play: whoever made the link '
      'could have named another site.',
  'site.confirm': 'This is the site, go on',
  'site.login_at': 'Log in at {host}',
  'site.login_hint':
      'With the account you made on this site. The app keeps the session on '
      'this phone; the password is not kept.',
  'site.username': 'Username',
  'site.password': 'Password',
  'site.login': 'Log in',
  'site.need_login': 'Type your username and password.',
  'site.totp_text':
      'This account has two-step verification: type the code from your '
      'authenticator app.',
  'site.code': '6-digit code',
  'site.logged_in': 'With the account {user} at {host}',
  'site.logout': 'Log out',
  'site.games': 'Games',
  'site.no_games': 'This field has no games published for the coming days.',
  'site.game_gone': 'That game is no longer published or has ended.',
  'site.cancelled': 'Cancelled',
  'site.cancelled_reason': 'This game has been cancelled: {reason}',
  'site.open_until': 'Registration open until {when}',
  'site.left': '{n} places',
  'site.opens': 'Registration opens {when}',
  'site.full': 'Full',
  'site.closed': 'Registration closed',
  'site.no_online': 'No online registration: ask the field\'s organisers.',
  'site.reg.registered': 'You are registered for this game.',
  'site.reg.checked_in': 'You checked in for this game.',
  'site.reg.no_show': 'You did not come to this game.',
  'site.reg.cancelled': 'You cancelled your registration.',
  'site.form': 'Registration',
  'site.form_change': 'Change your registration',
  'site.name_hint': 'The name the organisers and marshals see in this game.',
  'site.replicas': 'Replicas you will use (up to {n})',
  'site.class_not_here': '{class}: this field has no such class',
  'site.too_many': 'This field takes up to {n} replicas per person.',
  'site.register': 'Register',
  'site.save': 'Save the changes',
  'site.changed': 'Registration changed.',
  'site.cancel_reg': 'Cancel the registration',
  'site.cancel_title': 'Cancel the registration?',
  'site.cancel_text':
      'You give up your place in {game} and the check-in ticket stops working.',
  'site.cancel_yes': 'Cancel the registration',
  'site.data_note':
      'The field gets the name you choose for the game, your team preference, '
      'your federation number (if the game asks for one) and the declared '
      'replicas, and erases them 30 days after the game.',
  'site.show_ticket': 'Show the check-in ticket',
  'site.no_ticket_here':
      'This registration\'s ticket is not on this phone. Ask for a new one: '
      'the old one stops working.',
  'site.new_ticket': 'Ask for a new ticket',
  'site.ticket': 'Check-in ticket',
  'site.ticket_text':
      'At the field, show this code to a marshal, or check in in the app with '
      '"Check in at the field" and pick this registration. The ticket\'s text:',
  'site.copy': 'Copy the text',
  'site.copied': 'Copied.',
  'site.ticket_secret':
      'Whoever has this ticket can check in in your place: do not share it.',
  'site.my_tickets': 'My tickets',
  'site.no_tickets': 'No tickets on this phone yet.',
  'site.claim': 'Use this phone\'s id',
  'site.claim_text':
      'If you have checked in at {field} with this phone, the account can '
      'take the same player id (your replicas and chrono readings). The '
      'field\'s controller confirms it at its next sync.',
  'site.claim_pick': 'This phone\'s ids',
  'site.claim_at': 'At the controller {field}',
  'site.claim_none': 'This phone has not checked in at any field yet.',
  'site.claim_send': 'Claim this id',
  'site.claim_linked': 'The account already has the id {id} at this field.',
  'site.claim.pending':
      'Sent: waiting for the field\'s controller to confirm it.',
  'site.claim.confirmed': 'Confirmed.',
  'site.claim.refused':
      'The field\'s controller did not confirm that id (another phone, or a '
      'check-in made by hand).',
  'site.error': 'The site refused: {error}',

  // Game history
  'history.title': 'Game history',
  'history.reload': 'Reload',
  'history.intro':
      'The games you played, from the site\'s records of the fields where '
      'this account has a player id: the scores and your own events.',
  'history.none':
      'No games yet. A game shows here once the field has sent it to the '
      'site.',
  'history.unnamed': 'Game',
  'history.at': 'At {field}',
  'history.state.ready': 'Not started',
  'history.state.running': 'Running',
  'history.state.paused': 'Paused',
  'history.state.ended': 'Ended',
  'history.winner': 'Winner: {team}',
  'history.no_winner': 'No winner (a tie, or no points).',
  'history.scores': 'Scores',
  'history.no_scores': 'The site has no scores for this game.',
  'history.events': 'Your events',
  'history.no_events': 'The site has no events of yours for this game.',
  'history.registered': 'You were checked in to this game.',
  'history.you': 'you',
  'site.err.offline': 'The site cannot be reached. Try again in a while.',
  'site.err.login_required': 'The session has ended: log in again.',
  'site.err.invalid_credentials': 'Wrong username or password.',
  'site.err.invalid_code': 'Wrong code. Try the next one.',
  'site.err.invalid_totp_session':
      'The code step has expired: type your password again.',
  'site.err.too_many_attempts': 'Too many attempts: wait a little.',
  'site.err.field_not_found': 'This site has no such field.',
  'site.err.http_404':
      'This site has no online registration (an older server?).',
  'site.err.scheduled_game_not_found': 'That game no longer exists.',
  'site.err.registration_not_found': 'That registration no longer exists.',
  'site.err.registration_closed': 'Registration for this game is closed.',
  'site.err.game_full': 'This game is full.',
  'site.err.already_registered': 'You are already registered for this game.',
  'site.err.not_registered': 'This registration is no longer live.',
  'site.err.game_started': 'The game has started.',
  'site.err.federation_number_required':
      'This game asks for a federation number.',
  'site.err.display_name_invalid': 'The name must be 1 to 32 characters.',
  'site.err.team_preference_invalid': 'That team is not in this game.',
  'site.err.too_many_replicas': 'Too many replicas for this field.',
  'site.err.replica_class_invalid':
      'One of the replicas has a class this field does not have.',
  'site.err.replicas_not_asked':
      'This game does not ask for replicas at registration.',
  'site.err.player_id_exists':
      'The account already has a player id at this field.',
  'site.err.player_id_taken': 'That id belongs to another account.',
  'site.err.player_secret_invalid': 'This id\'s secret is not valid.',
  'checkin.registered': 'Online registration',
  'checkin.no_registration': 'None (walk-in)',
  'checkin.registered_hint':
      'If you registered on the field\'s site, pick the registration: its '
      'ticket goes with the check-in.',
  'checkin.ticket_other_id':
      'This phone already has another id at this field. Use "Use this phone\'s '
      'id" in online registration, or check in without the registration.',

  // Field controller (slice S6 of PE24)
  'ctl.intro':
      'This phone is the field controller of a small game, with no Raspberry '
      'Pi: it runs the game, serves the game master\'s console, check-in and '
      'the scoreboard on the field\'s Wi-Fi, and talks to the boxes through an '
      'I/O pod. It keeps running with the screen off.',
  'ctl.refresh': 'Refresh',
  'ctl.phase_stopped': 'Stopped',
  'ctl.phase_starting': 'Starting…',
  'ctl.phase_running': 'Running',
  'ctl.phase_stopping': 'Stopping…',
  'ctl.stopped_hint':
      'Games are kept: when it starts again, the live game goes on.',
  'ctl.no_game': 'No live game. Create one in the console.',
  'ctl.game': '{name}: {state}',
  'ctl.game_ready': 'ready to start',
  'ctl.game_running': 'running',
  'ctl.game_paused': 'paused',
  'ctl.game_ended': 'ended',
  'ctl.clients':
      'Connections: {stream} to the console or scoreboard, {mqtt} over MQTT, '
      '{props} from game props on Wi-Fi.',
  'ctl.start': 'Start the controller',
  'ctl.stop': 'Stop the controller',
  'ctl.error_storage':
      'This phone gave the app no private folder: the controller cannot keep '
      'its games.',
  'ctl.error_start': 'The controller did not start.',
  'ctl.error_ended': 'The controller stopped by itself.',
  'ctl.no_foreground':
      'Android did not let the controller show its notification: with the '
      'screen off it may stop. Keep the app open, or allow its notifications.',
  'ctl.battery': 'Battery optimisation may stop the controller mid-game.',
  'ctl.battery_ask': 'Ask for the exemption',
  'ctl.network': "Field's network",
  'ctl.open': "Open on the field's Wi-Fi",
  'ctl.open_on':
      'Phones, computers and game props connect over HTTPS (port 8443, with '
      "the field's CA) and MQTT (port 1883).",
  'ctl.open_off':
      'Only this phone reaches the controller: nothing listens on the network.',
  'ctl.addresses': "The console, on computers on the field's network:",
  'ctl.no_address':
      'This phone is on no Wi-Fi network: turn its hotspot on or join the '
      "field's network.",
  'ctl.ca': "The field CA's fingerprint",
  'ctl.ca_hint': "It is on the check-in poster: players' phones check it.",
  'ctl.wifi': "Field's Wi-Fi",
  'ctl.wifi_unavailable': "This phone's Wi-Fi cannot be seen.",
  'ctl.wifi_off': 'Wi-Fi off',
  'ctl.wifi_network': 'On the network {ssid}',
  'ctl.wifi_unknown': 'On a Wi-Fi network (its name needs location)',
  'ctl.hotspot_on': 'Hotspot on',
  'ctl.hotspot_off': 'Hotspot off',
  'ctl.hotspot_unknown': 'Hotspot: state unknown',
  'ctl.hotspot_settings': 'Hotspot settings',
  'ctl.wifi_settings': 'Wi-Fi settings',
  'ctl.local_intro':
      'No router or hotspot? The phone can make a network for this game only '
      '(Android picks its name and password and changes them each time: do '
      'not put them on the poster).',
  'ctl.local_start': 'Make a network for the game',
  'ctl.local_stop': "Turn the game's network off",
  'ctl.local_on': "The game's network: {ssid}",
  'ctl.local_password': 'Password: {password}',
  'ctl.local_qr':
      'QR code to join the network {ssid}: players scan it with their camera.',
  'ctl.local_error_permission':
      'The nearby devices (or location) permission is missing.',
  'ctl.local_error_location_off': 'Turn location on and try again.',
  'ctl.local_error_incompatible_mode':
      'This phone cannot make the network while on another Wi-Fi network or '
      'with its hotspot on.',
  'ctl.local_error_tethering_disallowed':
      'This phone does not allow sharing its connection.',
  'ctl.local_error_no_channel': 'No Wi-Fi channel is free.',
  'ctl.local_error_generic': 'Android did not make the network.',
  'ctl.local_error_unavailable': 'This phone cannot make networks.',
  'ctl.radio': 'Radio',
  'ctl.radio_none': 'No radio: game props on Wi-Fi only',
  'ctl.radio_pod': 'I/O pod: {name}',
  'ctl.radio_hint':
      "The field's boxes need an I/O pod linked over USB or Bluetooth.",
  'ctl.radio_locked': 'To change the radio, stop the controller.',
  'ctl.radio_up': 'Radio up',
  'ctl.radio_down': 'Radio down',
  'ctl.radio_connecting': 'Reaching the radio…',
  'ctl.pod_forget': 'Unlink the pod',
  'ctl.codes': 'Access codes',
  'ctl.codes_hint':
      "The console asks for one of these. The game master's runs the game: "
      'do not show it to players.',
  'ctl.code_gm': "Game master's code",
  'ctl.code_read': 'Read-only code (scoreboard)',
  // Slice S7c: the field card written by this phone's NFC.
  'ctl.card': 'Field card',
  'ctl.card_hint':
      'New boxes join this field with the field card: write it on an '
      'NTAG215 or NTAG216 card and tap it once on each new box. Boxes with '
      "a screen can also be paired by the code they show (the console's "
      'Adopt tab).',
  'ctl.card_write': 'Write the field card',
  'ctl.card_warn_title': "The field's master secret",
  'ctl.card_warn':
      'This card holds the field join key: whoever has it can make join '
      "cards for this field's boxes and read later games' keys sent over "
      'the radio. Keep it locked away; if it is lost or copied, the field '
      'needs a new key.',
  'ctl.card_write_go': 'Write the card',
  'ctl.card_done': 'Field card written (field {fingerprint}).',
  'ctl.card_failed': 'The field card could not be made: try again.',
  'ctl.tags': "Players' tags",
  'ctl.tags_hint':
      "Write the running game's signed NFC tags with this phone's NFC. The "
      'game key stays on this phone.',
  'ctl.tags_none':
      "Start a game first: tags are signed with the running game's key.",
  'ctl.tags_open': "Write players' tags",
  'ctl.firmware': 'Firmware updates',
  'ctl.fw_keys': 'Firmware release keys',
  'ctl.fw_keys_none':
      'None: this controller takes no firmware release for the boxes.',
  'ctl.fw_keys_set': '{n} key(s): releases they sign are taken.',
  'ctl.fw_keys_hint':
      "The release keys' public halves (base64, 44 characters each), one "
      "per line, as in the Pi's [firmware] release_keys. The boxes check "
      'every release again with the keys in their own firmware. A running '
      'controller restarts to take them.',
  'ctl.fw_keys_bad': 'Each key is 44 base64 characters (32 bytes); at most 8.',
  'ctl.code_hidden': 'Hidden',
  'ctl.show_codes': 'Show the codes',
  'ctl.hide_codes': 'Hide the codes',
  'ctl.copy': 'Copy: {what}',
  'ctl.copied': 'Copied: {what}',
  'ctl.console': "Game master's console",
  'ctl.open_console': 'Open the console',
  'ctl.console_title': "This controller's console",
  'ctl.no_console':
      "This app was built without the console's files: open it from a "
      'computer.',
  'ctl.poster_hint':
      "To print the check-in poster, open {url} on a computer on the field's "
      'network (Check-in tab).',
  'ctl.poster_hint_closed':
      "The check-in poster needs the controller open on the field's Wi-Fi.",
  'ctl.notif_title': 'Atalaia: field controller',
  'ctl.notif_starting': 'Starting…',
  'ctl.notif_idle': 'No live game',
  'ctl.notif_game': '{name}: {state}',
  // The phone controller's [modes] settings (slice S7b of PE24).
  'ctl_modes.title': 'Mode packages',
  'ctl_modes.tile': 'Mode packages (field controller)',
  'ctl_modes.tile_hint': '{keys} trusted keys, {box} box keys',
  'ctl_modes.intro':
      'The keys this phone\'s field controller trusts for signed mode packages, the keys built into the boxes\' firmware (the controller offers the boxes only packages they take), revoked keys and the registry\'s index: a Pi\'s [modes] settings. They apply when the controller next starts.',
  'ctl_modes.keys': 'Trusted mode keys (one per line, base64)',
  'ctl_modes.box_keys': 'The boxes\' mode keys (one per line, base64)',
  'ctl_modes.revoked': 'Revoked key ids (one per line, 16 hex digits)',
  'ctl_modes.index':
      'The registry\'s index (an https:// address or a file; optional)',
  'ctl_modes.bad_key': 'Line {line}: not a mode key (base64 of 32 bytes).',
  'ctl_modes.bad_id': 'Line {line}: not a key id (16 hex digits).',
  'ctl_modes.bad_index': 'The index is an https:// address or a file.',
  'ctl_modes.saved': 'Saved: they apply when the controller next starts.',
  // The phone controller's slice S7 settings (PE24-118 onward).
  'ctl_site.tile': 'Site server, failover and ATAK (field controller)',
  'ctl_site.tile_hint': 'Failover {mode}; site server {sync}; ATAK {atak}',
  'ctl_site.on': 'on',
  'ctl_site.off': 'off',
  'ctl_site.title': 'Site server, failover and ATAK',
  'ctl_site.intro':
      'This phone\'s field controller as a Pi\'s controller.toml has it: its failover, the field\'s site server (the games, logs and scores go there when the internet is there; rosters, branding and the scenario library come from it) and the ATAK feed. They apply when the controller next starts.',
  'ctl_site.failover': 'Failover',
  'ctl_site.failover_auto': 'Automatic failover',
  'ctl_site.manual': 'Manual',
  'ctl_site.auto': 'Automatic',
  'ctl_site.failover_hint':
      'Manual: the GM promotes a standby controller. Automatic: a standby takes over after three missed beacons (30 s). A phone on battery yields to a Pi on mains when both stand.',
  'ctl_site.sync': 'Site server',
  'ctl_site.sync_hint': 'Offline first: a game never waits for the network.',
  'ctl_site.url': 'Address (https://…)',
  'ctl_site.key': 'The field\'s API key (from the site server)',
  'ctl_site.key_set': 'API key {fp}… (type a new one to replace it)',
  'ctl_site.branding':
      'The field\'s branding, saved teams and check-in settings from the site server',
  'ctl_site.library':
      'The field\'s scenarios and game presets from the site server',
  'ctl_site.remote_gm': 'Remote GM',
  'ctl_site.remote_gm_hint':
      'The field\'s GMs on the site server may start, pause and end the live game. Off by default.',
  'ctl_site.atak': 'ATAK feed (Cursor on Target)',
  'ctl_site.atak_hint':
      'The boxes and zones on ATAK maps, over the field\'s Wi-Fi.',
  'ctl_site.multicast': 'Multicast address (239.2.3.1:6969)',
  'ctl_site.staff': 'Staff ATAK devices (host:port, comma between)',
  'ctl_site.players':
      'Player positions to the staff devices (never to multicast)',
  'ctl_site.remote': 'Remote ATAK through the site server',
  'ctl_site.remote_players': 'Player positions through the site server too',
  'ctl_site.bad_sync': 'Site server: {why}',
  'ctl_site.bad_atak': 'ATAK: {why}',
  'apd.section': 'APD membership',
  'apd.accepts_any': 'Any APD is accepted.',
  'apd.accepts': 'Accepted APDs: {list}',
  'apd.pick': 'Your APD',
  'apd.unlisted': 'Not in the list',
  'apd.number': 'Membership number',
  'apd.number_required': 'Membership number (required)',
  'apd.expires': 'Valid until (YYYY-MM-DD)',
  'apd.expires_required': 'Valid until, YYYY-MM-DD (required)',
  'apd.date_format': '2027-01-31',
  'apd.hint':
      'The app does not check it: a marshal compares it with your card.',
  'apd.need_number': 'This field asks for your APD membership number.',
  'apd.need_expiry': 'This field asks for the date your membership expires.',
  'apd.bad_date': 'Write the date as YYYY-MM-DD, for instance 2027-01-31.',
  'apd.until': 'until {date}',
  'apd.overridden': 'let in by a marshal',
  'apd.status.valid': 'Membership valid',
  'apd.status.expired': 'Membership expired',
  'apd.status.not_accepted': 'APD not accepted here',
  'apd.status.missing': 'Membership missing',
  'apd.hint_marshal': 'A marshal will look at your membership card.',
  'queue.confirm': 'Let in',
  'site.err.membership_missing':
      'This field needs your APD membership number to register.',
  'site.err.apd_not_accepted': 'This field does not accept that APD.',
  'site.err.membership_expired':
      'The membership has expired by the day of this game.',
  // The remote GM may see shared positions (PKD-5)
  'player.share_remote_gm':
      'If the field has a remote GM signed in on the site server, the remote GM sees your position too while you share it. The site server does not keep it.',
  // The account's login methods and the login without a password (PKA-1);
  // the texts are the site server's own (staff_i18n.py) where the same.
  'acct.passkey_cancelled':
      'The passkey was not used (the request was cancelled or timed out).',
  'acct.passkey_failed': 'Could not log in with the passkey.',
  'acct.passkey_none': 'This account has no passkeys.',
  'acct.oidc.state_invalid':
      'This login request expired or was not made by this app. Try again.',
  'acct.oidc.denied': 'The login was refused at the provider.',
  'acct.oidc.consent_required':
      'To make a new account, tick the agreement above first.',
  'acct.oidc.too_many_attempts':
      'Too many new accounts from this address. Try again later.',
  'acct.oidc.quota_exceeded':
      'This field has reached its limit of accounts. Talk to the field\'s staff.',
  'acct.oidc.id_token_invalid':
      'The provider\'s answer was not accepted. Try again.',
  'acct.oidc.token_exchange_failed':
      'The provider refused the request. Try again.',
  'acct.oidc.provider_unreachable':
      'Could not reach the provider. Try again in a moment.',
  'acct.oidc.try_again': 'Try again.',
  'acct.oidc.other': 'Could not log in with the provider.',
  'acct.title': 'Ways to log in',
  'acct.intro':
      'The ways to log in to this account: password, Google, Microsoft or Apple, passkeys and the TOTP code. Every change is recorded in the server\'s audit log.',
  'acct.confirm_title': 'Confirm it is you',
  'acct.confirm_password': 'Current password',
  'acct.confirm_password_hint':
      'The changes below ask for the current password. Type it here before making them.',
  'acct.confirm_recent':
      'This account has no password: the changes ask for a confirmation made in the last 10 minutes (logging in counts too). Confirm with one of the ways below, then repeat the action.',
  'acct.confirm_with': 'Confirm with {provider}',
  'acct.confirmed': 'Confirmed. Repeat the action.',
  'acct.reauthed': 'Confirmed with the provider. Repeat the action.',
  'acct.providers_title': 'Google, Microsoft and Apple',
  'acct.providers_none': 'No login is linked to this account.',
  'acct.providers_off': 'This server has no Google, Microsoft or Apple login.',
  'acct.provider_linked_at': 'linked {when}',
  'acct.provider_last_login': 'last login {when}',
  'acct.link': 'Link {provider}',
  'acct.unlink': 'Unlink',
  'acct.unlink_confirm': 'Unlink {provider} from this account?',
  'acct.linked': 'Login linked to the account.',
  'acct.unlinked': 'Login unlinked.',
  'acct.passkeys_title': 'Passkeys',
  'acct.passkeys_intro':
      'A passkey logs in with no password and no code, and counts as the second factor for the admin, GM and marshal roles.',
  'acct.passkeys_none': 'No passkeys.',
  'acct.passkey_name': 'Name of the new passkey',
  'acct.passkey_add': 'Add a passkey',
  'acct.passkey_added': 'Passkey added.',
  'acct.passkey_unsupported':
      'This phone does not support passkeys (it needs Android 14 or newer).',
  'acct.passkey_synced': 'synced',
  'acct.passkey_device': 'this device only',
  'acct.passkey_created': 'created {when}',
  'acct.passkey_used': 'used {when}',
  'acct.passkey_unused': 'never used',
  'acct.rename': 'Rename',
  'acct.passkey_rename_label': 'New name of the passkey',
  'acct.passkey_renamed': 'Name saved.',
  'acct.passkey_remove': 'Remove',
  'acct.passkey_remove_confirm': 'Remove the passkey {name}?',
  'acct.passkey_removed': 'Passkey removed.',
  'acct.pw_title': 'Password',
  'acct.pw_state_set': 'This account has a password.',
  'acct.pw_state_none': 'This account has no password.',
  'acct.pw_off':
      'Password login is turned off on this server: a password cannot be set or changed.',
  'acct.pw_new': 'New password',
  'acct.pw_set_button': 'Set a password',
  'acct.pw_change_button': 'Change the password',
  'acct.pw_changed': 'Password saved. The account\'s other sessions ended.',
  'acct.pw_remove': 'Log in without a password',
  'acct.pw_remove_confirm': 'Remove this account\'s password?',
  'acct.pw_removed': 'Password removed.',
  'acct.totp_title': 'TOTP code',
  'acct.totp_on': 'TOTP is on for this account.',
  'acct.totp_off': 'TOTP is not on for this account.',
  'acct.totp_enable': 'Turn TOTP on',
  'acct.totp_enrol_intro':
      'Add this secret to the authenticator app ({digits} digits, a new code every {s} s) and type the code the app shows below.',
  'acct.totp_secret': 'Secret',
  'acct.totp_uri': 'otpauth address (for apps that take one)',
  'acct.totp_confirm': 'Turn on with this code',
  'acct.totp_enabled': 'TOTP turned on.',
  'acct.totp_disable_intro':
      'To turn it off: the app\'s current code, plus the password above if the account has one.',
  'acct.totp_disable': 'Turn TOTP off',
  'acct.totp_disabled': 'TOTP turned off.',
  'acct.oidc.already_linked': 'This account already has that login linked.',
  'acct.oidc.identity_taken':
      'That login is already linked to another account.',
  'acct.oidc.provider_already_linked':
      'This account already has a login from that provider. Unlink the existing one first.',
  'acct.oidc.identity_mismatch':
      'That is not the login linked to this account. Use the same provider account.',
  'acct.e.last_login_method':
      'That is the account\'s last way to log in: add another one first.',
  'acct.e.second_factor_required_by_role':
      'A role on this account needs a second factor (TOTP or a passkey): keep at least one.',
  'acct.e.totp_required_by_role':
      'A role on this account needs a second factor: add a passkey before turning TOTP off.',
  'acct.e.password_login_disabled':
      'Password login is turned off on this server, so a password cannot be set or changed.',
  'acct.e.confirmation_required':
      'Confirm it is you first (see the confirmation above), then repeat the action.',
  'acct.e.invalid_password': 'Wrong password.',
  'acct.e.invalid_code': 'Wrong code.',
  'acct.e.no_password': 'This account has no password.',
  'acct.e.identity_not_found': 'That login is not linked to this account.',
  'acct.e.passkey_not_found': 'That passkey no longer exists.',
  'acct.e.too_many_passkeys':
      'Too many passkeys on this account. Remove one first.',
  'acct.e.passkey_exists': 'This passkey is already registered.',
  'acct.e.passkey_invalid': 'The server did not accept this passkey.',
  'acct.e.invalid_passkey': 'The passkey was not accepted.',
  'acct.e.invalid_challenge': 'The passkey request expired. Try again.',
  'acct.e.name_invalid': 'That name is not valid.',
  'acct.e.totp_already_enabled': 'TOTP is already on.',
  'acct.e.totp_not_pending': 'Start turning TOTP on first.',
  'acct.e.totp_not_enabled': 'TOTP is not on.',
  'acct.e.no_passkey': 'This account has no passkeys.',
  'acct.e.password_too_short': 'The password is too short.',
  'acct.e.password_too_long': 'The password is too long.',
  'acct.e.password_is_username': 'The password cannot be the account name.',
  'acct.e.password_breached':
      'This password appears in known data breaches. Choose another.',
  'acct.e.provider_not_configured': 'This server does not offer that login.',
  'acct.browser_unavailable': 'Could not open the phone\'s browser.',
  'acct.oidc.cancelled': 'The login was cancelled.',
  'acct.oidc.browser_unavailable':
      'Could not open the phone\'s browser, or this server does not take a login through the app.',
  'acct.waiting': 'Waiting for {provider} in the browser…',
  'acct.waiting_cancel': 'Cancel',
  'acct.open': 'Ways to log in to the account',
  'acct.confirm_passkey': 'Confirm with a passkey',
  'acct.confirm_code': 'TOTP code',
  'acct.confirm_code_button': 'Confirm with the code',
  'acct.passkey_name_hint': 'Name of the new passkey (optional)',
  'acct.passkey_here': 'The passkey is kept by the phone\'s password manager.',
  'acct.code': 'Code from the authenticator app',
  'acct.save': 'Save',
  'acct.cancel': 'Cancel',
  'acct.remove_confirm_yes': 'Remove',
  'acct.unlink_yes': 'Unlink',
  'acct.pw_remove_yes': 'Remove',
  'acct.copy': 'Copy',
  'acct.error_generic': 'That did not work: {error}',
  'site.login_or': 'or',
  'site.login_with': 'Log in with {provider}',
  'site.login_passkey': 'Log in with a passkey',
  'site.login_consent':
      'If this is a first login, I agree to a new account being made (only the identifier the provider gives is kept; see the field\'s privacy notice).',
  'site.login_waiting': 'Waiting for the login in the browser…',
  'site.login_waiting_cancel': 'Cancel',
  'site.account': 'Ways to log in to the account',
  // Android props fetch signed mode packages from their controller (PKF-1).
  'propmodes.keys': 'Mode keys for fetched modes',
  'propmodes.keys_none':
      'None: this prop runs only the modes built into the app.',
  'propmodes.keys_set':
      '{n} key(s): a mode they sign may be fetched from the controller.',
  'propmodes.keys_hint':
      "The public halves (base64, 44 characters each) of the mode keys this prop trusts, one per line, at most 4: as the mode keys built into a Field Box's firmware. A game whose mode the app lacks is fetched from its controller only when a key in this list signed it. Never add a key you were not given by the project or your club.",
  'propmodes.keys_bad':
      'Each key is 44 base64 characters (32 bytes); at most 4.',
  'propmodes.fetching':
      "Getting the game's mode from the controller and checking its signature…",
  'propmodes.err.no_key':
      'This phone trusts no mode key, so it takes no mode from the controller. Add the key of the project or your club in Settings.',
  'propmodes.err.unreachable':
      "Could not reach the controller with the field's certificate. Join the field's Wi-Fi and try again.",
  'propmodes.err.not_offered':
      'The controller does not offer {mode}, or the game has already started. Ask the GM to send it signed, or to start from built-in modes.',
  'propmodes.err.download':
      'The download of {mode} broke or was not the size announced. Try again.',
  'propmodes.err.bad_release':
      'Refused: the signed release of {mode} is not in the accepted form. It was not run.',
  'propmodes.err.bad_signature':
      'Refused: {mode} is not signed, or not signed by a key this phone trusts. It was not run.',
  'propmodes.err.kind': 'Refused: {mode} is not a kind of package a prop runs.',
  'propmodes.err.tier':
      'Refused: {mode} needs a stronger device than this phone.',
  'propmodes.err.builtin':
      'Refused: {mode} has the id of a mode built into the app; those are never replaced.',
  'propmodes.err.too_big':
      'Refused: {mode} is too large for a prop (256 KiB at most).',
  'propmodes.err.bad_hash':
      'Refused: {mode} is not the file that was signed. It was not run.',
  'propmodes.err.bad_archive':
      'Refused: the package of {mode} is damaged or not in the accepted form. It was not run.',
  'propmodes.err.load':
      'Refused: {mode} does not load in the sandbox. It was not run.',
  'propmodes.err.no_space':
      'No room for {mode}: the phone keeps at most 8 fetched modes, 512 KiB in all.',
  'propmodes.err.other': 'The mode could not be fetched ({mode}).',
  // The membership texts of a field outside Portugal (decision MEM-4)
  'apd.section_m': 'Association membership',
  'apd.accepts_any_m': 'Any association is accepted.',
  'apd.accepts_m': 'Accepted associations: {list}',
  'apd.pick_m': 'Your association',
  'apd.need_number_m': 'This field asks for your membership number.',
  'apd.status.not_accepted_m': 'Association not accepted here',
  'site.err.membership_missing_m':
      'This field needs your membership number to register.',
  'site.err.apd_not_accepted_m': 'This field does not accept that association.',
  // The registration import on the phone controller's own screen (decision PIM-1);
  // the file and row texts are the console's (checkin_import in its i18n).
  'ctl.import': 'Registration list',
  'ctl.import_hint':
      'For a field with no site server: import a list of registrations (CSV or JSON) from another platform as this game\'s expected players. Check it first; nothing changes until you import.',
  'ctl.import_open': 'Import a registration list',
  'ctl.import_none': 'Start a game to import a registration list into it.',
  'ctl_import.pick': 'Choose a file',
  'ctl_import.pick_again': 'Choose another file',
  'ctl_import.picked': 'File: {name}',
  'ctl_import.no_file': 'No file chosen yet.',
  'ctl_import.no_picker':
      'This phone cannot open a file chooser here. Import the list from the GM console in a browser instead.',
  'ctl_import.offline': 'The controller did not answer. Is it running?',
  'ctl_import.failed': 'The controller refused the list: {detail}',
  'ctl_import.rows_more': '{n} more rows are not shown.',
  'ctl_import.title': 'Import a registration list',
  'ctl_import.intro':
      'For a field with no site server: a list of registrations from another platform (CSV or JSON, the site server\'s import format) becomes this game\'s expected players, and a marshal ticks each one when they arrive. Only display_name, external_ref, team_preference, federation_number and replicas are read; any other column (an email, a phone number) is only named, never read.',
  'ctl_import.source': 'Source',
  'ctl_import.source_hint':
      'The other platform\'s name (a-z, 0-9, dot, dash, underscore). The same source and external_ref update the same player.',
  'ctl_import.basis':
      'This field is responsible for the list: it has its own legal basis for holding these players\' data.',
  'ctl_import.check': 'Check the file',
  'ctl_import.run': 'Import',
  'ctl_import.order': 'Check first: nothing is changed until Import.',
  'ctl_import.checked': 'Checked, nothing imported yet.',
  'ctl_import.imported': 'Imported.',
  'ctl_import.counts':
      '{rows} rows: {created} new, {updated} changed, {unchanged} unchanged, {skipped} skipped, {refused} refused.',
  'ctl_import.ignored': 'Columns not read: {names}',
  'ctl_import.more': 'and {n} more',
  'ctl_import.missing':
      '{n} imported players that have not arrived are not in this file (they stay).',
  'ctl_import.row': 'Row',
  'ctl_import.result': 'Result',
  'ctl_import.line': 'line {n}',
  'ctl_import.done': 'Imported: {created} new, {updated} changed.',
  'ctl_import.results.created': 'new',
  'ctl_import.results.updated': 'changed',
  'ctl_import.results.unchanged': 'unchanged',
  'ctl_import.results.skipped': 'skipped',
  'ctl_import.results.refused': 'refused',
  'ctl_import.codes.empty': 'the file is empty',
  'ctl_import.codes.display_name_column_missing': 'no display_name column',
  'ctl_import.codes.column_twice': 'a column twice',
  'ctl_import.codes.encoding_invalid': 'the file is not UTF-8 text',
  'ctl_import.codes.csv_invalid': 'not valid CSV',
  'ctl_import.codes.json_invalid': 'not valid JSON (an array of objects)',
  'ctl_import.codes.too_large': 'the file is over 1 MiB',
  'ctl_import.codes.too_many_rows': 'more than 5,000 rows',
  'ctl_import.codes.format_invalid': 'not a CSV or JSON file',
  'ctl_import.codes.source_invalid':
      'the source is not valid (a-z, 0-9, dot, dash, underscore; not "site")',
  'ctl_import.codes.basis_not_confirmed':
      'confirm that this field has its own basis for the list',
  'ctl_import.codes.game_ended': 'the game has ended',
  'ctl_import.codes.row_length':
      'the row does not have as many cells as the header',
  'ctl_import.codes.row_not_object': 'not an object',
  'ctl_import.codes.display_name_invalid':
      'name missing or not 1-32 characters on one line',
  'ctl_import.codes.external_ref_invalid': 'external_ref over 128 characters',
  'ctl_import.codes.team_preference_invalid': 'not a team of this game',
  'ctl_import.codes.federation_number_invalid': 'number over 32 characters',
  'ctl_import.codes.federation_number_required':
      'this field asks for the number',
  'ctl_import.codes.replicas_invalid':
      'replicas not as type:class[:make model]|…',
  'ctl_import.codes.replicas_not_asked':
      'this game does not take declared replicas',
  'ctl_import.codes.too_many_replicas': 'more replicas than the field allows',
  'ctl_import.codes.replica_type_invalid': 'replica type unknown',
  'ctl_import.codes.replica_class_invalid':
      'replica class not in the field\'s limits',
  'ctl_import.codes.make_model_invalid': 'make and model over 64 characters',
  'ctl_import.codes.external_ref_twice': 'external_ref twice in the file',
  'ctl_import.codes.already_arrived': 'already arrived: not changed',
  'ctl_import.codes.removed': 'removed: not changed',
  'ctl_import.codes.no_external_ref': 'no external_ref: added again each time',
  'ctl_import.codes.federation_number_dropped':
      'number not kept: this field asks for none',
  'player.buzz_title': 'Atalaia: following the game',
  'player.buzz_text': 'Vibrating on game events while the app is closed',
  'player.saved': 'Fields remembered',
  'player.saved_forget': 'Forget this field',
};
