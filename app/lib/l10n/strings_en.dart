// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// English (strings.dart).
library;

const Map<String, String> enStrings = {
  // Common
  'common.cancel': 'Cancel',
  'common.close': 'Close',
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

  // Settings
  'settings.title': 'Settings',
  'settings.language': 'Language',
  'settings.lang_pt': 'Português',
  'settings.lang_en': 'English',
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
  'player.bad_link': 'The address or the access code is missing.',
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
      'Before recording readings, give your name and id and make your marshal '
      'key (below, under "Who you are").',
  'marshal.identity': 'Who you are',
  'marshal.name': "Marshal's name",
  'marshal.id': "Marshal's id",
  'marshal.field_id': "Field's id",
  'marshal.chrono_id': "Chronograph's id",
  'marshal.key': 'Signing key',
  'marshal.no_key': 'No key yet: readings must be signed.',
  'marshal.key_id': 'Public key {id}…',
  'marshal.make_key': 'Make one',
  'marshal.new_key': 'New key',
  'marshal.new_key_body':
      'Old readings stay signed with the old key; new ones are signed with '
      'the new key.',
  'marshal.records': 'Stored readings',
  'marshal.readings':
      '{n} readings on this phone. They are kept for 365 days, then deleted.',
  'marshal.erase': "Erase someone's readings",
  'marshal.erase_do': 'Erase',

  // Chrono
  'chrono.title': 'Chronograph',
  'chrono.hint': "Check-in and spot checks, against the field's limit.",
  'chrono.template': "Field's limits",
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
      "Tags are signed with the game's key, so every game has its own. Pick "
      'the game with its join card or QR code.',
  'tags.game': 'Pick the game',
  'tags.for_game': 'Game {game} ({mode})',
  'tags.other_game': 'Another game',
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
};
