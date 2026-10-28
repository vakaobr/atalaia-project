// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// German (strings.dart). Drafted by an AI model on 2026-10-22; to be
/// reviewed by a native-speaking player (docs/translations/status.yaml).
library;

const Map<String, String> deStrings = {
  // Common
  'common.cancel': 'Abbrechen',
  'common.close': 'Schließen',
  'common.clear': 'Text löschen',
  'common.ok': 'OK',
  'common.save': 'Speichern',

  // Home and roles
  'home.choose': 'Was soll dieses Handy machen?',
  'home.no_prop':
      'Dieses Handy kann kein Spielprop sein: Das geht nur mit Android (es '
      'braucht Kiosk-Modus, NFC im Hintergrund und USB).',
  'role.prop': 'Spielprop',
  'role.prop_hint':
      'Dieses Handy arbeitet als Box: Es führt den Spielmodus aus, mit '
      'Team-Tasten auf dem Bildschirm, NFC-Tags und optional einem I/O-Pod.',
  'role.player': 'Spielen',
  'role.player_hint':
      'Das Spiel verfolgen: Zeit, Punkte, Ziele, Leben und Nachrichten der '
      'Spielleitung.',
  'role.marshal': 'Marshal',
  'role.marshal_hint':
      'Chrono beim Check-in und Stichproben, das Replik-Register und die Tags '
      'der Spielenden.',
  'role.gm': 'Spielleitung',
  'role.gm_hint': 'Die GM-Konsole, bereitgestellt vom Feld-Controller.',
  'role.controller': 'Feld-Controller',
  'role.controller_hint':
      'Dieses Handy betreibt das Spiel ohne Raspberry Pi: die Konsole, den '
      'Check-in und die Boxen über einen I/O-Pod.',

  // Settings
  'settings.title': 'Einstellungen',
  'settings.language': 'Sprache',
  'settings.lang_pt': 'Português',
  'settings.lang_en': 'English',
  'settings.lang_de': 'Deutsch',
  'settings.lang_zh-tw': '中文（台灣）',
  'settings.theme': 'Darstellung',
  'settings.theme_system': 'System',
  'settings.theme_dark': 'Dunkel',
  'settings.theme_light': 'Hell (Sonne)',
  'settings.field': 'Spielfeld',
  'settings.join_key': 'Beitrittsschlüssel des Felds',
  'settings.join_key_none':
      'Nicht gesetzt: Ohne ihn kannst du keinem Spiel beitreten.',
  'settings.join_key_set': 'Gesetzt (endet auf …{end})',
  'settings.join_key_hint':
      'Die 64 Hex-Ziffern, die der Feld-Controller mit '
      '"python3 -m atalaia_controller join-key" ausgibt. Sie belegen, dass '
      'eine Beitrittskarte oder ein QR-Code zu diesem Feld gehört.',
  'settings.join_key_bad':
      'Der Beitrittsschlüssel hat 64 Hex-Ziffern (0-9, a-f).',
  'settings.join_key_clear': 'Löschen',
  'settings.pin': 'Admin-PIN',
  'settings.pin_none':
      'Keine PIN: Alle können ein Spiel auf diesem Prop pausieren oder beenden.',
  'settings.pin_set':
      'Gesetzt: wird beim Starten, Pausieren, Beenden und Verlassen abgefragt.',
  'settings.pin_hint': '4 bis 8 Ziffern.',
  'settings.pin_remove': 'PIN entfernen',
  'settings.kiosk': 'Kiosk-Modus',
  'settings.kiosk_hint':
      'Während eines Spiels ist das Handy an die App gebunden. Verlässt jemand '
      'sie, warnt die App.',
  'settings.vibrate': 'Bei Spielereignissen vibrieren',
  'settings.vibrate_hint':
      'Ein kurzes Brummen bei einer Nachricht der Spielleitung, wenn eine Box '
      'deines Teams erobert oder verloren wird, wenn das Spiel beginnt oder '
      'endet, wenn bei Progressive Domination die nächste Box aktiv wird und '
      'bei neuen Befehlen (ein Ziel oder die deines Squad-Leads). Kein '
      'Ton. Die Stummschaltung des Handys gilt.',
  'settings.about': 'Über',
  'settings.version': 'Atalaia {version}',
  'settings.core': 'Spielkern {version}',
  'settings.no_core': 'Kein Spielkern auf diesem Handy.',
  'settings.licence': 'Lizenz',
  'settings.licence_text':
      'Freie Software: GPL-3.0 oder neuer, mit der zusätzlichen Erlaubnis für '
      'App-Stores (APP-STORE-PERMISSION.md).',
  'pin.title': 'Admin-PIN',
  'pin.wrong': 'Falsche PIN.',

  // Battery
  'battery.title': 'Akku und Hintergrund',
  'battery.intro':
      'Während eines Spiels kann Android Apps im Hintergrund beenden, um Akku '
      'zu sparen. Damit ein Prop stundenlang durchhält, nimm Atalaia aus der '
      'Akku-Optimierung heraus.',
  'battery.exempt': 'Atalaia ist bereits von der Akku-Optimierung ausgenommen.',
  'battery.not_exempt':
      'Atalaia unterliegt noch der Akku-Optimierung: Android kann die App '
      'während eines Spiels beenden.',
  'battery.request': 'Ausnahme anfordern',
  'battery.open_settings': 'Akku-Einstellungen öffnen',
  'battery.on_samsung_title': 'Samsung',
  'battery.on_samsung':
      'Einstellungen › Akku › Einschränkungen der Hintergrundnutzung: Atalaia '
      'aus den inaktiven Apps nehmen. Dann Einstellungen › Apps › Atalaia › '
      'Akku › Nicht eingeschränkt.',
  'battery.on_xiaomi_title': 'Xiaomi, Redmi, POCO',
  'battery.on_xiaomi':
      'Einstellungen › Akku › App-Akkusparmodus › Atalaia › Keine '
      'Einschränkungen. Unter Sicherheit › Autostart Atalaia einschalten.',
  'battery.on_huawei_title': 'Huawei, Honor',
  'battery.on_huawei':
      'Einstellungen › Akku › App-Start › Atalaia: automatische Verwaltung '
      'ausschalten und die drei Optionen eingeschaltet lassen (automatischer '
      'Start, Start durch andere Apps, Ausführung im Hintergrund).',
  'battery.on_oneplus_title': 'OnePlus, OPPO, realme',
  'battery.on_oneplus':
      'Einstellungen › Akku › Akku-Optimierung › Atalaia › Nicht optimieren. '
      'Bei manchen Modellen auch: Einstellungen › Apps › Atalaia › '
      'Akkunutzung › Hintergrundaktivität zulassen.',
  'battery.on_generic_title': 'Andere Handys',
  'battery.on_generic':
      'Einstellungen › Apps › Atalaia › Akku: „Nicht eingeschränkt" oder '
      '„Nicht optimieren" wählen. Die Namen unterscheiden sich je nach '
      'Hersteller.',

  // Prop
  'prop.intro':
      'Ein neues Spiel nur auf diesem Handy oder eines der Spiele des '
      'Feld-Controllers (mit der Beitrittskarte oder dem QR-Code der '
      'Spielleitung).',
  'prop.new_game': 'Neues Spiel',
  'prop.join': 'Einem Spiel beitreten',
  'prop.capabilities': 'Was dieses Handy hat',
  'prop.start': 'Starten',
  'prop.confirm_start': 'Spiel jetzt starten?',
  'prop.pause': 'Pause',
  'prop.resume': 'Fortsetzen',
  'prop.end': 'Spiel beenden',
  'prop.confirm_end': 'Spiel jetzt beenden?',
  'prop.leave': 'Verlassen',
  'prop.confirm_leave': 'Spiel verlassen?',
  'prop.confirm_leave_body':
      'Das Spiel läuft noch: Dieses Prop zählt dann nicht mehr mit.',
  'prop.log': 'Spielprotokoll',
  'prop.admin': 'Spielleitung',
  'prop.loading': 'Modus wird geladen…',
  'prop.waiting': 'Warten auf den Start',
  'prop.paused': 'PAUSIERT',
  'prop.paused_hint': 'Warte auf die Spielleitung.',
  'prop.ended': 'Spiel vorbei',
  'prop.script_error': 'Der Modus wurde angehalten',
  'prop.tamper':
      'Jemand hat während des Spiels den Kiosk-Modus verlassen. Sag der '
      'Spielleitung Bescheid.',
  'prop.pod_opened':
      'Jemand hat während des Spiels den I/O-Pod geöffnet. Sag der '
      'Spielleitung Bescheid.',
  'prop.pod_reconnecting':
      'Die Verbindung zum I/O-Pod ist abgebrochen. Verbinde neu (Versuch {n}) …',
  'prop.pod_refused':
      'Ein anderer Pod hat geantwortet, der I/O-Pod ist daher nicht mehr verbunden. '
      'Verbinde einen Pod erneut.',
  'prop.pod_unlink': 'I/O-Pod trennen',
  'prop.hold': 'Gedrückt halten\n{team}',
  'prop.nfc_hint': 'Halte den Tag an die Rückseite des Handys.',
  'prop.keypad': 'Tastenfeld',
  'prop.keypad_hide': 'Tastenfeld ausblenden',
  'prop.phase_loading': 'wird geladen',
  'prop.phase_ready': 'startbereit',
  'prop.phase_running': 'läuft',
  'prop.phase_paused': 'pausiert',
  'prop.phase_ended': 'beendet',
  'prop.phase_halted': 'durch einen Fehler angehalten',
  'prop.phase_failed': 'nicht gestartet',
  'prop.notification_title': 'Atalaia: {mode}',
  'prop.notification_running': 'Spiel läuft',
  'prop.notification_left': 'noch {time}',

  // Setup
  'setup.title': 'Neues Spiel',
  'setup.joined': 'Spiel des Controllers',
  'setup.join_info':
      'Spiel {game}, dieses Prop ist Knoten {node}, Kanal {mhz} MHz.',
  'setup.mode': 'Spielmodus',
  'setup.with': 'Mit {mode}',
  'setup.role': 'Rolle im Modus',
  'setup.teams': 'Teams',
  'setup.params': 'Parameter des Modus',
  'setup.any_team': 'Alle Teams',
  'setup.length': 'Dauer',
  'setup.minutes': 'Minuten',
  'setup.minutes_hint': '0 = kein Limit. Danach endet das Spiel von selbst.',
  'setup.prepare': 'Spiel vorbereiten',
  'setup.missing':
      'Diesem Handy fehlt: {caps}. Verbinde einen I/O-Pod, der das hat.',
  'setup.needs_controller':
      'Dieser Modus zählt Punkte über mehrere Boxen mit dem Feld-Controller. '
      'Allein übernimmt dieses Prop nur seinen eigenen Teil.',
  'setup.unknown_mode': 'Dieses Prop hat den Modus dieses Spiels nicht.',
  'setup.unknown_role': 'Der Modus dieses Spiels hat diese Rolle nicht.',

  // Join
  'join.intro':
      'Scanne den Beitritts-QR-Code in der GM-Konsole, halte die '
      'Beitrittskarte an das Handy oder füge den Text atalaia:join:… ein.',
  'join.scan': 'QR-Code scannen',
  'join.scan_hint': 'Richte die Kamera auf den Beitritts-QR-Code.',
  'join.card': 'Beitrittskarte (NFC)',
  'join.card_ready': 'Halte die Karte an die Rückseite des Handys.',
  'join.text': 'Beitrittstext',
  'join.use_text': 'Diesen Text verwenden',
  'join.warning':
      'Karte und Code enthalten den Spielschlüssel: Zeig sie nur den Leuten, '
      'die das Feld aufbauen.',
  'join.no_key':
      'Setze zuerst den Beitrittsschlüssel des Felds in den Einstellungen.',
  'join.no_camera': 'Es gibt keine Kamera, um den Code zu lesen.',
  'join.bad_text': 'Das ist kein gültiger Beitrittscode.',
  'join.not_a_card': 'Diese Karte enthält keine Beitrittsdaten.',
  'join.other_field':
      'Dieser Code gehört zu einem anderen Feld (der Beitrittsschlüssel passt '
      'nicht).',
  'join.bad_body': 'Die Beitrittsdaten sind beschädigt.',
  'join.for_controller':
      'Dieser Code ist für einen Standby-Controller, nicht für ein Prop.',
  'nfc.off': 'NFC ist aus: Schalte es in den Einstellungen des Handys ein.',
  'nfc.none': 'Dieses Handy hat kein NFC.',

  // I/O pod
  'pod.title': 'I/O-Pod',
  'pod.intro':
      'Ein I/O-Pod leiht dem Handy große Tasten, Lichter, eine Sirene, einen '
      'NFC-Leser und LoRa-Funk, über USB (bevorzugt) oder Bluetooth.',
  'pod.none': 'Kein Pod verbunden: Das Spiel nutzt nur das Handy.',
  'pod.link': 'Pod verbinden',
  'pod.find': 'Pods suchen',
  'pod.found_none': 'Kein Pod gefunden.',
  'pod.linked': 'Pod über {kind} verbunden: Firmware {fw}, {n} Funktionen.',
  'pod.open_failed': 'Die Verbindung zum Pod ließ sich nicht öffnen.',
  'pod.no_ident': 'Der Pod hat nicht geantwortet.',
  'pod.reconnecting':
      'Die Verbindung zum Pod ist abgebrochen. Verbinde neu (Versuch {n}) …',
  'pod.refused':
      'Ein anderer Pod hat geantwortet, die Verbindung wurde daher nicht wiederhergestellt. '
      'Verbinde einen Pod erneut.',
  'pod.unlink': 'Pod trennen',

  // Capabilities
  'cap.team_input': 'Team-Tasten',
  'cap.keypad': 'Tastenfeld',
  'cap.display': 'Bildschirm',
  'cap.team_display': 'Teamfarbe',
  'cap.led': 'Lichter',
  'cap.audio': 'Ton',
  'cap.haptic': 'Vibration',
  'cap.nfc': 'NFC',
  'cap.gps': 'GPS',
  'cap.imu': 'Beschleunigungssensor',
  'cap.qr_scanner': 'QR-Leser',
  'cap.button': 'Tasten',
  'cap.lora': 'LoRa-Funk',

  // Teams
  'team.red': 'Rot',
  'team.blue': 'Blau',
  'team.green': 'Grün',
  'team.yellow': 'Gelb',
  'team.orange': 'Orange',
  'team.purple': 'Lila',

  // Player
  'player.intro':
      'Verbinde dich mit dem Feld-Controller: Scanne den QR-Code der '
      'Anzeigetafel oder gib die Adresse und den Zugangscode der Spielleitung '
      'ein.',
  'player.scan': 'QR-Code der Anzeigetafel scannen',
  'player.scan_hint': 'Richte die Kamera auf den QR-Code der Anzeigetafel.',
  'player.by_hand': 'Oder eintippen',
  'player.address': 'Adresse des Controllers',
  'player.code': 'Zugangscode',
  'player.connect': 'Verbinden',
  'code.is_poster':
      'Das ist das Check-in-Plakat eines Felds. Nutze es unter Spielen > Am '
      'Feld einchecken.',
  'code.is_join_card':
      'Das ist ein Beitrittscode für ein Spielprop. Nutze ihn unter Spielprop '
      '> Einem Spiel beitreten.',
  'code.is_site_link':
      'Das ist ein Link zur Online-Anmeldung eines Felds. Nutze ihn unter '
      'Spielen > Online-Anmeldung.',
  'code.is_scoreboard':
      'Das ist der Link zur Anzeigetafel eines Spiels. Nutze ihn unter '
      'Spielen > Ein Spiel ohne Check-in verfolgen.',
  'player.bad_link': 'Adresse oder Zugangscode fehlt.',
  'player.link_unreachable':
      'Der Controller antwortet nicht. Bist du im WLAN des Felds?',
  'player.link_mismatch':
      'Der antwortende Controller ist nicht der, für den dieser Code gemacht wurde. Mach nicht weiter und sag der Orga Bescheid.',
  'player.link_not_controller':
      'Unter dieser Adresse antwortet kein Feld-Controller.',
  'player.connecting': 'Verbindung zum Feld-Controller…',
  'player.offline': 'Offline. Verbindung wird wiederhergestellt…',
  'player.denied': 'Der Zugangscode wurde abgelehnt.',
  'player.no_game': 'Es läuft noch kein Spiel.',
  'player.left': 'verbleibend',
  'player.score': 'Punkte',
  'player.my_team': 'dein Team',
  'player.pick_team': 'Tippe auf dein Team, um es hervorzuheben.',
  'player.eliminated': 'ausgeschieden',
  'player.lives_left': '{n} Leben',
  'player.objectives': 'Ziele',
  'player.node': 'Box {n}',
  'player.held_by': 'Gehalten von Team {team}',
  'player.held_by_none': 'Von niemandem gehalten',
  'player.active_box': 'Aktive Box: {zone}',
  'player.active_box_tag': 'AKTIV',
  'player.scenario': 'Szenario-Ziele',
  'player.objective_waiting': 'Beginnt mit dem Spiel',
  'player.objective_active': 'Läuft',
  'player.objective_done': 'Erfüllt von Team {team}',
  'player.objective_done_no_team': 'Erfüllt',
  'player.objective_failed': 'Gescheitert',
  'player.objective_failed_captured':
      'Gescheitert: von einem anderen Team genommen',
  'player.objective_failed_defused': 'Gescheitert: Die Bombe wurde entschärft',
  'player.objective_failed_time': 'Gescheitert: Zeit abgelaufen',
  'player.objective_failed_blocked':
      'Gescheitert: Ein früheres Ziel ist gescheitert',
  'player.objective_failed_lives': 'Gescheitert: zu wenige Leben übrig',
  'player.objective_for_team': 'Für Team {team}',
  'player.objective_for_squad': 'Für Team {team}, Squad {squad}',
  'player.objective_points': '+{n}',
  'player.lives': 'Leben',
  'player.events': 'Was passiert ist',
  'player.no_events': 'Noch nichts.',
  'player.message': 'Spielleitung: {text}',
  'player.ended': 'Das Spiel ist vorbei.',
  'player.tie': 'Unentschieden',
  'player.winner': 'Team {team} gewinnt',
  'state.ready': 'bereit',
  'state.running': 'läuft',
  'state.paused': 'pausiert',
  'state.ended': 'beendet',

  // Events
  'event.game.start': 'Das Spiel hat begonnen',
  'event.game.pause': 'Spiel pausiert',
  'event.game.resume': 'Das Spiel geht weiter',
  'event.game.end': 'Das Spiel ist zu Ende',
  'event.zone.captured': 'Team {team} hat {zone} eingenommen',
  'event.zone.neutralized': '{zone} ist frei',
  'event.bomb.armed': 'Bombe scharf gemacht von Team {team} ({fuse} s)',
  'event.bomb.defused': 'Bombe entschärft von Team {team}',
  'event.bomb.exploded': 'Die Bombe ist hochgegangen',
  'event.bomb.reset': 'Die Bombe wurde zurückgesetzt',
  'event.score.delta': 'Punkte für Team {team}: {amount}',
  'event.code.used': 'Team {team} hat einen Code benutzt',
  'event.player.respawn': '{player} ist wieder drin ({lives} Leben)',
  'event.player.checkin': '{player} hat eingecheckt',
  'event.kill.confirmed': 'Kill bestätigt von Team {team} ({player})',
  'event.kill.denied': 'Team {team} hat den Tag von {player} zurückgeholt',
  'event.team.eliminated': 'Team {team} hat keine Leben mehr',
  'event.holdall.scoring_start': 'Team {team} hält alle Zonen',
  'event.holdall.scoring_stop': 'Team {team} hat eine Zone verloren',
  'event.laststand.countdown_start': 'Last Stand: Der Countdown läuft',
  'event.laststand.countdown_cancel': 'Last Stand: Countdown abgebrochen',
  'event.laststand.defeated': 'Last Stand: Die Verteidigung ist gefallen',
  'event.gm.message': 'Spielleitung: {text}',
  'event.visibility.granted': 'Team {team} sieht das Spielfeld',
  'event.chrono.violation': 'Eine Replik über dem Limit',
  'event.node.tamper': 'Jemand hat an einer Box manipuliert ({reason})',
  'event.medic.heal':
      '{player} wurde geheilt (Heilungen im Kit übrig: {remaining})',
  'event.medic.empty': 'Ein Medic-Kit ist leer',
  'event.hacking.solved': 'Team {team} hat ein Terminal gehackt',
  'event.hacking.solved.no_team': 'Ein Terminal wurde gehackt',
  'event.vip.extracted': 'Team {team} hat die Extraktionszone erreicht',
  'event.money.collected': '{player} hat {amount} Geld eingesammelt',
  'event.money.deposited': '{player} hat {amount} für Team {team} eingezahlt',
  'event.progressive.activated':
      'Box {zone} ist jetzt aktiv (Nr. {step}): nur sie kann eingenommen werden',
  'event.progressive.completed':
      'Team {team} hat Box {zone} abgeschlossen (Nr. {step})',
  'event.scenario.started': 'Das Szenario hat begonnen',
  'event.scenario.objective.completed': 'Team {team} hat ein Ziel erfüllt',
  'event.scenario.objective.completed.no_team': 'Ein Ziel wurde erfüllt',
  'event.scenario.objective.failed':
      'Team {team} ist an einem Ziel gescheitert',
  'event.scenario.objective.failed.no_team': 'Ein Ziel ist gescheitert',
  'event.scenario.objective.revealed': 'Ein neues Ziel für Team {team}',
  'event.scenario.objective.revealed.no_team': 'Ein neues Ziel',
  'event.scenario.objective.completed.named':
      'Team {team} erfüllt: {objective}',
  'event.scenario.objective.completed.named.no_team': 'Erfüllt: {objective}',
  'event.scenario.objective.failed.named':
      'Team {team} gescheitert: {objective}',
  'event.scenario.objective.failed.named.no_team': 'Gescheitert: {objective}',
  'event.scenario.objective.revealed.named':
      'Ein neues Ziel für Team {team}: {objective}',
  'event.scenario.objective.revealed.named.no_team':
      'Ein neues Ziel: {objective}',
  'event.scenario.objective.revealed.leader':
      'Dein Squad-Lead hat neue Befehle',
  'player.leader_orders':
      'Befehle für dein Squad: Dein Squad-Lead gibt sie weiter',

  // GM
  'gm.intro':
      'Die GM-Konsole des Feld-Controllers. Gib die Adresse des Controllers '
      'ein; die Konsole fragt nach dem Zugangscode.',
  'gm.address': 'Adresse der Konsole',
  'gm.open': 'Konsole öffnen',
  'gm.bad_url': 'Diese Adresse funktioniert nicht.',
  'gm.change': 'Adresse ändern',

  // Marshal
  'marshal.no_identity':
      'Um Messwerte aufzuzeichnen, muss der Controller des Felds dich als '
      'Marshal bestätigen: Check-in am Feld mit dem Plakat, dann nimmt die '
      'Orga dich in ihre Liste auf. Name und ID kommen aus dieser Liste, der '
      'Signaturschlüssel wird automatisch erstellt.',
  'marshal.identity': 'Wer du bist',
  'marshal.name': 'Name des Marshals',
  'marshal.id': 'ID des Marshals',
  'marshal.field_id': 'ID des Felds',
  'marshal.chrono_id': 'ID des Chronos',
  'marshal.key': 'Signaturschlüssel',
  'marshal.no_key': 'Noch kein Schlüssel: Messwerte müssen signiert sein.',
  'marshal.key_id': 'Öffentlicher Schlüssel {id}…',
  'marshal.new_key': 'Neuer Schlüssel',
  'marshal.new_key_body':
      'Alte Messwerte bleiben mit dem alten Schlüssel signiert; neue werden '
      'mit dem neuen Schlüssel signiert.',
  'marshal.records': 'Gespeicherte Messwerte',
  'marshal.readings':
      '{n} Messwerte auf diesem Handy. Sie werden 365 Tage aufbewahrt und dann '
      'gelöscht.',
  'marshal.erase': 'Messwerte einer Person löschen',
  'marshal.erase_do': 'Löschen',
  'marshal.checking': 'Frage den Feld-Controller …',
  'marshal.you_are': 'Du bist Marshal {id} ({name})',
  'marshal.id_from_gm':
      'ID und Name stammen aus der Marshal-Liste der Spielleitung; der Feld-Controller hat sie bestätigt.',
  'marshal.not_listed':
      'Der Feld-Controller hat dich nicht auf seiner Marshal-Liste. Bitte die Spielleitung, dich als Marshal einzutragen.',
  'marshal.revoked':
      'Die Spielleitung hat dich von der Marshal-Liste genommen; dieses Handy ist hier kein Marshal mehr. Die {n} noch nicht gesendeten Serien bleiben auf diesem Handy und können gesendet werden, wenn die Spielleitung dich wieder einträgt.',
  'marshal.offline_never':
      'Der Feld-Controller ist nicht erreichbar, und dieses Handy wurde hier noch nicht als Marshal bestätigt. Verbinde dich einmal mit dem Netz des Felds und frag erneut.',
  'marshal.offline_expired':
      'Der Feld-Controller ist nicht erreichbar, und seine Bestätigung vom {at} ist abgelaufen. Verbinde dich mit dem Netz des Felds und frag erneut.',
  'marshal.offline_ok':
      'Offline: Der Feld-Controller hat dich am {at} als Marshal {id} bestätigt. Das gilt bis {until}; danach verbinde dich mit dem Netz des Felds, um erneut zu bestätigen.',
  'marshal.retry': 'Erneut fragen',
  'marshal.expired_now':
      'Die Bestätigung des Feld-Controllers ist abgelaufen: Frag erneut, bevor du aufzeichnest.',

  // Chrono
  'chrono.title': 'Chrono',
  'chrono.hint': 'Check-in und Stichproben, gegen das Limit des Felds.',
  'chrono.template': 'Limits des Felds',
  'chrono.template_set': 'Vom Controller des Felds festgelegt.',
  'chrono.template_local':
      'Der Controller des Felds urteilt mit seiner eigenen Liste, und sein '
      'Urteil zählt. Diese Liste dient nur der Vorschau auf diesem Handy.',
  'chrono.template_unknown':
      'Der Controller des Felds nutzt die Limits „{name}", die diese App '
      'nicht hat. Sein Urteil zählt; die Werte hier sind nur ein Anhaltspunkt.',
  'limits.portugal': 'Portugal',
  'limits.uk': 'Vereinigtes Königreich',
  'limits.germany': 'Deutschland',
  'limits.generic_cqb': 'Allgemein CQB',
  'replica.class_rifle': 'Gewehr',
  'replica.class_dmr': 'DMR',
  'replica.class_sniper': 'Sniper',
  'replica.class_cqb': 'CQB',
  'replica.class_semi': 'Halbautomat',
  'chrono.unverified':
      'Die Limits „{name}" sind nicht geprüft: Sie stammen aus der Recherche '
      'des Projekts, nicht aus einer offiziellen Quelle. Prüfe sie vor dem '
      'Einsatz gegen die aktuellen Regeln.',
  'chrono.checkin': 'Check-in',
  'chrono.spotcheck': 'Stichprobe',
  'chrono.replica': 'Replik',
  'chrono.replica_nfc': 'Oder halte den Tag der Replik an das Handy.',
  'chrono.unknown_tag': 'Dieser Tag ist nicht im Replik-Register.',
  'chrono.no_class': 'Die Limits des Felds haben keine Klasse „{class}".',
  'chrono.limit': 'Limit: {j} J ({fps} fps mit 0,20 g)',
  'chrono.bb': 'BB-Gewicht',
  'chrono.velocity': 'Geschwindigkeit',
  'chrono.energy': 'Energie: {j} J',
  'chrono.record': 'Schuss aufzeichnen',
  'chrono.new_series': 'Neue Serie',
  'chrono.pass': 'OK',
  'chrono.warn': 'WARNUNG',
  'chrono.fail': 'DURCHGEFALLEN',
  'chrono.highest': 'Höchstwert: {j} J · Limit {limit} J',
  'chrono.vs_checkin': 'Beim Check-in: {j} J (+{pct} % Toleranz)',

  // Replicas
  'replica.title': 'Replik-Register',
  'replica.add': 'Replik registrieren',
  'replica.none': 'Noch keine Repliken registriert.',
  'replica.count': '{n} Repliken registriert',
  'replica.owner': 'ID der spielenden Person',
  'replica.type': 'Typ',
  'replica.class': 'Klasse',
  'replica.model': 'Hersteller und Modell',
  'replica.tag': 'Tag der Replik',
  'replica.tap_tag':
      'Halte den NFC-Tag der Replik an das Handy oder scanne ihr QR-Etikett.',
  'replica.tag_read': 'Tag: {uid}',
  'replica.scan': 'QR-Etikett scannen',
  'replica.scan_hint': 'Richte die Kamera auf das QR-Etikett der Replik.',
  'replica.needs_tag': 'Klasse oder Tag der Replik fehlt.',
  'replica.type_aeg': 'AEG',
  'replica.type_gbb': 'GBB',
  'replica.type_hpa': 'HPA',
  'replica.type_bolt_action': 'Repetierer',
  'replica.type_dmr': 'DMR',
  'replica.type_sniper': 'Sniper',
  'replica.type_pistol': 'Pistole',
  'replica.type_shotgun': 'Shotgun',

  // Tags
  'tags.title': 'Tags der Spielenden',
  'tags.hint': 'Die signierten NFC-Tags für ein Spiel schreiben.',
  'tags.intro':
      'Tags werden vom Feldcontroller signiert, der den Schlüssel des Spiels '
      'verwahrt: Du brauchst nie den Beitrittsschlüssel des Felds. Sei im '
      'WLAN des Felds, tippe eine spielende Person ein und halte einen '
      'leeren Tag ans Handy.',
  'tags.for_game': 'Spiel: {game}',
  'tags.loading': 'Frage den Feldcontroller…',
  'tags.offline':
      'Der Feldcontroller ist nicht erreichbar: Verbinde dich mit dem WLAN '
      'des Felds und versuch es nochmal.',
  'tags.not_marshal':
      'Der Feldcontroller sagt, du bist hier kein Marshal: Frag die '
      'Spielleitung.',
  'tags.session': 'Dein Check-in ist abgelaufen: Check erneut ein.',
  'tags.no_key':
      'Das Spiel läuft nicht auf dem Controller (es ist beendet oder hat '
      'seinen Schlüssel verloren), also kann er keine Tags signieren.',
  'tags.refused': 'Der Feldcontroller hat den Tag abgelehnt: {error}',
  'tags.bad_answer':
      'Die Antwort des Controllers ist kein gültiger Tag für diese Person.',
  'tags.player': 'ID der spielenden Person',
  'tags.player_hint': 'Buchstaben, Ziffern, - _ und . (bis zu 32), z. B. p-17',
  'tags.bad_player': 'Die ID hat 1 bis 32 Buchstaben, Ziffern, -, _ oder .',
  'tags.no_team': 'Kein Team',
  'tags.write': 'Tag schreiben',
  'tags.hold': 'Halte den Tag an die Rückseite des Handys…',
  'tags.written': 'Gerade geschrieben',
  'tags.write_not_ndef': 'Dieser Tag nimmt keine NDEF-Daten an.',
  'tags.write_read_only': 'Dieser Tag ist gesperrt.',
  'tags.write_too_small': 'Der Tag ist zu klein.',
  'tags.write_io':
      'Schreiben fehlgeschlagen: Halte den Tag still und versuch es nochmal.',
  'tags.write_unavailable': 'Dieses Handy kann keine NFC-Tags schreiben.',

  // Field check-in, replicas to chrono, positions (plan phase E)
  'checkin.title': 'Am Feld einchecken',
  'checkin.intro':
      'Scanne das Check-in-Plakat des Felds mit der Kamera (oder füge seinen Text ein). Das Handy erreicht den Controller des Felds über das WLAN des Felds; Internet ist nicht nötig.',
  'checkin.scan': 'Plakat scannen',
  'checkin.scan_hint': 'Richte die Kamera auf den QR-Code des Check-in-Plakats',
  'checkin.by_text': 'Oder füge den Text des Plakats ein',
  'checkin.text_hint': 'atalaia:checkin:…',
  'checkin.use_text': 'Diesen Text verwenden',
  'checkin.bad_poster':
      'Dieses Check-in-Plakat ist nicht lesbar. Frag die Orga nach einem anderen.',
  'checkin.not_poster': 'Das ist kein Check-in-Plakat von Atalaia.',
  // Why the field controller did not answer (check-R5)
  'diag.title': 'Details',
  'diag.timeout': 'keine Antwort rechtzeitig',
  'diag.refused': 'Verbindung abgelehnt',
  'diag.unreachable': 'keine Route zur Adresse',
  'diag.tls': 'Zertifikat nicht akzeptiert',
  'diag.http': 'HTTP {status}',
  'diag.other': 'Verbindungsfehler',
  'diag.line': '{kind} · {url} · {time}',
  'checkin.unreachable':
      'Der Controller des Felds antwortet nicht. Bist du im WLAN des Felds?',
  'checkin.join_wifi':
      'Der Controller des Felds antwortet nicht: Verbinde dich mit dem WLAN „{ssid}" und versuch es nochmal.',
  'checkin.mismatch':
      'Der antwortende Controller ist nicht der des Plakats (Plakat {poster}, Controller {got}). Mach nicht weiter und sag der Orga Bescheid.',
  'checkin.not_controller':
      'Unter dieser Adresse antwortet kein Feld-Controller.',
  'checkin.changed':
      'Diesem Feld wurde mit einem anderen Zertifikat vertraut ({old}); das Plakat zeigt {new}. Wenn die Orga bestätigt, dass der Controller gewechselt hat, vergiss das Feld und scanne das Plakat erneut.',
  'checkin.forget_field': 'Dieses Feld vergessen',
  'checkin.error': 'Der Controller hat abgelehnt: {error}',
  'checkin.offline':
      'Keine Verbindung zum Controller des Felds: Versuch es im Netz des Felds nochmal.',
  'checkin.expired': 'Dieser Check-in gilt nicht mehr: Checke erneut ein.',
  'checkin.connecting': 'Verbindung zum Controller des Felds…',
  'checkin.notice_title': 'Deine Daten bei {field}',
  'checkin.notice_ok': 'Gelesen, weiter',
  'checkin.trusted': 'Zertifikat des Felds {ca}',
  'checkin.no_games': 'An diesem Feld ist kein Spiel für den Check-in offen.',
  'checkin.game': 'Spiel',
  'checkin.for_game': 'Spiel: {game}',
  'checkin.name': 'Name oder Callsign',
  'checkin.name_hint': 'Orga und Marshals sehen ihn; andere Spielende nicht.',
  'checkin.federation_required': 'Verbandsnummer ({label})',
  'checkin.federation_optional': 'Verbandsnummer ({label}, optional)',
  'checkin.federation_hint':
      'Die Orga sieht sich den Ausweis am Tisch an; die App prüft ihn nicht.',
  'checkin.need_name': 'Gib einen Namen oder ein Callsign ein.',
  'checkin.need_federation':
      'Dieses Feld verlangt deine Verbandsnummer ({label}).',
  'checkin.pick_game': 'Wähle das Spiel.',
  'checkin.team_pref': 'Wunschteam',
  'checkin.any_team': 'Egal',
  'checkin.bring': 'Repliken, die du mitbringst',
  'checkin.submit': 'Einchecken',
  'checkin.status_title': 'Mein Check-in',
  'checkin.status.pending': 'Wartet auf Bestätigung am Orga-Tisch.',
  'checkin.status.checked_in': 'Eingecheckt.',
  'checkin.status.left': 'Du hast dieses Spiel verlassen.',
  'checkin.status.removed': 'Die Orga hat diesen Check-in entfernt.',
  'checkin.role.player': 'Spielen',
  'checkin.role.squad_leader': 'Squad-Lead',
  'checkin.role.vip': 'VIP',
  'checkin.role.marshal': 'Marshal',
  'checkin.role.gm': 'GM',
  'checkin.role.spectator': 'Zuschauen',
  'checkin.my_declaration': 'Meine Repliken in diesem Spiel',
  'checkin.no_replicas': 'Du hast noch keine Replik angemeldet.',
  'checkin.declare': 'Repliken wählen',
  'checkin.follow': 'Spiel verfolgen',
  'checkin.leave': 'Spiel verlassen',
  'checkin.leave_body':
      'Dein Name und deine Verbandsnummer werden aus diesem Spiel gelöscht. Bereits gechronte Repliken bleiben gespeichert.',
  'checkin.left': 'Du hast das Spiel verlassen; deine Daten wurden gelöscht.',
  'chrono_state.pending': 'nicht gechront',
  'chrono_state.passed': 'bestanden',
  'chrono_state.refused': 'abgelehnt',
  'chrono_state.withdrawn': 'zurückgezogen',
  'chrono_state.refused_today': 'heute abgelehnt',
  'declare.title': 'Repliken für dieses Spiel',
  'declare.intro':
      'Wähle die Repliken, die du in diesem Spiel nutzt (bis zu {max}). Bring sie zu den Marshals zum Chronen.',
  'declare.none': 'Noch keine Repliken: Füge deine hinzu.',
  'declare.add': 'Replik hinzufügen',
  'declare.type': 'Typ',
  'declare.class': 'Klasse',
  'declare.make': 'Hersteller und Modell (optional)',
  'declare.save': 'Speichern',
  'declare.saved': 'Gespeichert: Orga und Marshals sehen sie jetzt.',
  'declare.locked':
      'Eine gechronte Replik bleibt angemeldet: Bitte einen Marshal, sie zu ändern.',
  'queue.title': 'Repliken zum Chronen',
  'queue.hint':
      'Die Liste des Felds: wer Repliken angemeldet hat, die noch nicht gechront wurden.',
  'queue.check_in_first':
      'Checke zuerst mit dem Plakat am Feld ein; danach gibt dir die Orga die Marshal-Rolle.',
  'queue.not_marshal': 'Diese Liste ist nur für Marshals und die Orga.',
  'queue.counts':
      'Zu chronen: {pending} · bestanden: {passed} · abgelehnt: {refused}',
  'queue.scan': 'Etikett einer Replik scannen',
  'queue.scan_hint': 'Richte die Kamera auf das QR-Etikett der Replik',
  'queue.not_found':
      'Diese Replik ist in diesem Spiel nicht angemeldet: Wähle die Anmeldung der spielenden Person.',
  'queue.refresh': 'Aktualisieren',
  'queue.empty': 'Noch niemand hat Repliken angemeldet.',
  'queue.manual': 'Von Hand einchecken',
  'queue.manual_do': 'Einchecken',
  'queue.manual_done': 'Eingecheckt: {id}',
  'queue.send_pending': '{n} noch nicht gesendete Serien senden',
  'queue.send_failed':
      '{n} Serien wurden nicht angenommen; sie bleiben auf diesem Handy.',
  'queue.held':
      '{n} Serien wurden nicht angenommen, weil der Controller dich nicht auf seiner Marshal-Liste hat; sie bleiben auf diesem Handy.',
  'queue.waiting_confirmation': 'wartet auf Bestätigung',
  'queue.sticker_title': 'NFC-Aufkleber verwenden?',
  'queue.sticker_body':
      'Den NFC-Aufkleber der Replik ans Telefon halten, um sie damit zu registrieren, oder das gedruckte QR-Etikett verwenden.',
  'queue.sticker_qr': 'QR-Etikett verwenden',
  'queue.sticker_taken':
      'Dieser Aufkleber ist schon für eine andere Replik registriert.',
  'queue.unregistered': 'noch nicht registriert',
  'label.title': 'Replik-Etikett',
  'label.show': 'Etikett zeigen',
  'label.share': 'Etikett teilen / drucken',
  'label.share_all': 'Alle Etiketten teilen / drucken',
  'label.share_title': 'Replik-Etiketten',
  'label.hint':
      'Klebe dieses Etikett auf die Replik. Der Marshal scannt es, um die Replik in der Chrono-Liste zu finden. Es enthält nur diesen Code, nichts über dich. Gedruckt wird es mit 30 × 30 mm; mehrere Etiketten passen auf ein A4-Blatt.',
  'label.share_unavailable':
      'Dieses Telefon kann keine Datei an das Teilen-Menü übergeben. Nutze stattdessen „Etikett zeigen“.',
  'label.share_failed': 'Das Teilen-Menü hat sich nicht geöffnet.',
  'label.none_yet':
      'Das Etikett erscheint hier, sobald du diese Replik für ein Spiel angemeldet hast.',
  'chrono.send': 'An den Controller senden',
  'chrono.sent_pass': 'Gesendet: bestanden.',
  'chrono.sent_fail': 'Gesendet: abgelehnt.',
  'chrono.sent_warn': 'Gesendet: Warnung.',
  'chrono.sent_unjudged': 'Gesendet: keine Klasse zum Vergleich.',
  'chrono.sent_null': 'Gesendet.',
  'chrono.send_failed':
      'Nicht gesendet: {error}. Bleibt auf diesem Handy und wird später gesendet.',
  'player.checkin': 'Am Feld einchecken',
  'player.watch': 'Ein Spiel ohne Check-in verfolgen',
  'player.continue': 'Weiter: {game}',
  'player.me': 'Du: {role}, {team}',
  'player.no_team': 'noch kein Team',
  'player.positions': 'Sichtbare Positionen: {n}',
  'player.share': 'Meine Position teilen',
  'player.share_hint':
      'Nur während des Spiels; der Controller entscheidet, wer sie sieht. Die Orga und die Marshals sehen sie auf ihren ATAK-Geräten.',
  'player.share_on': 'Wird geteilt: {n} Position(en) gesendet',
  'player.share_stopped':
      'Teilen beendet: Das Spiel ist vorbei oder der Check-in hat sich geändert.',
  'player.no_location': 'Dieses Handy hat keinen Standort.',
  'player.location_denied': 'Keine Berechtigung für den Standort.',
  'player.location_denied_ios':
      'Keine Berechtigung für den Standort. Erlaube ihn unter Einstellungen > Atalaia > Standort (Beim Verwenden der App) und prüfe, ob die Ortungsdienste an sind.',
  'player.share_ios_note':
      'Auf dem iPhone wird deine Position nur geteilt, solange Atalaia auf dem Bildschirm offen ist: Sie pausiert, wenn du die App wechselst oder das Handy sperrst, und läuft weiter, wenn du zurückkommst.',
  'player.sharing_title': 'Atalaia: Deine Position wird geteilt',
  'player.sharing_text': 'Während des Spiels',
  // The out-of-bounds warning (decisions MF-31 to MF-40)
  'player.out_title': 'Außerhalb des Felds',
  'player.out_text': 'Du hast die Feldgrenze verlassen. Geh zurück hinein.',
  'player.bounds_watch':
      'Dieses Handy vibriert, wenn du die Feldgrenze verlässt.',
  'prop.link.connecting': 'Verbindung zum Controller…',
  'prop.link.linked': 'Über WLAN mit dem Controller verbunden',
  'prop.link.refused':
      'Der Controller hat dieses Gerät abgelehnt (anderes Spiel?)',
  'prop.link.offline': 'Keine Verbindung zum Controller: neuer Versuch…',
  'prop.link.closed':
      'Ein anderes Gerät hat den Platz dieses Geräts übernommen',
  'prop.radio.configuring': 'Funk des Pods wird eingerichtet…',
  'prop.radio.linked': 'Der Funk des Pods ist auf dem Kanal des Felds',
  'prop.radio.heard': 'Über den Funk des Pods mit dem Controller verbunden',
  'prop.radio.offline': 'Der Funk des Pods antwortet nicht: neuer Versuch…',
  'prop.radio.closed': 'Der Funk des Pods ist aus',
  'prop.gm_message': 'Spielleitung: {text}',
  // Beacons im Gebäude (Entscheidungen BLE-1 bis BLE-9)
  'player.beacons_why_title': 'Positionen im Gebäude',
  'player.beacons_why':
      'Dieses Feld hat Bluetooth-Beacons im Gebäude. Um zu sagen, in welchem Raum du bist, kann Atalaia sie hören, während du deine Position teilst: nur die Beacons des Felds, und es sendet nur, welches am stärksten ist. Android fragt dafür nach den Berechtigungen für Bluetooth und Standort. Ohne sie bleibt deine Position nur GPS.',
  'player.beacons_allow': 'Weiter',
  'player.beacons_skip': 'Jetzt nicht',
  'player.beacons_on':
      'Hört auf die Beacons des Felds: im Gebäude ist deine Position der Raum.',
  'player.beacons_skipped':
      'Positionen im Gebäude sind aus. Deine GPS-Position wird weiter geteilt.',
  'player.beacons_denied':
      'Positionen im Gebäude sind aus: keine Berechtigung für Bluetooth. Deine GPS-Position wird weiter geteilt.',
  'player.beacons_off':
      'Positionen im Gebäude sind aus: Bluetooth ist ausgeschaltet. Schalte es ein und teile erneut.',
  'player.beacons_unavailable':
      'Dieses Handy kann die Beacons des Felds nicht hören. Deine GPS-Position wird weiter geteilt.',
  'player.beacons_ios':
      'Auf dem iPhone werden die Beacons des Felds im Gebäude noch nicht genutzt: Deine Position ist nur GPS.',
  'player.my_room': 'Deine Position: {room}',
  'player.map_title': 'Feldplan',
  'player.map_semantics': 'Plan des Felds, {level}: {n} Positionen',
  'player.map_off_plan': '{n} Positionen nicht auf diesem Plan',
  'player.map_level_unknown':
      'Leere Punkte: Spielende, die noch nicht gesagt haben, auf welchem Stockwerk sie sind.',
  'player.map_level_unknown_short': 'Stockwerk unbekannt',
  'player.map_cell': 'Dein Feld: {cell}',
  'player.map_you': 'Du',
  'player.map_player': 'Eine mitspielende Person',
  'player.map_player_team': 'Mitspielende Person von {team}',
  'player.level_n': 'Ebene {n}',
  'player.level_title': 'Auf welchem Stockwerk bist du?',
  'player.level_unknown': 'Weiß nicht',
  'player.level_hint':
      'Dein Team sieht dich auf diesem Stockwerk. Das Handy kann Stockwerke nicht selbst unterscheiden.',
  'player.level_beacon': 'Dein Stockwerk kommt vom Beacon im Raum: {level}.',
  'player.feature.safe_zone': 'Sicherheitszone',
  'player.feature.respawn': 'Respawn',
  'player.feature.hq': 'Hauptquartier',
  'player.feature.parking': 'Parkplatz',
  'player.feature.first_aid': 'Erste Hilfe',
  'player.feature.objective': 'Ziel',
  'player.feature.other': 'Sonstiges',
  'player.feature.boundary': 'Feldgrenze',
  'player.share_hint_squads':
      'Nur während des Spiels; der Controller entscheidet, wer sie sieht: dein Squad, wenn das Spiel es erlaubt, und die Orga und die Marshals auf ihren ATAK-Geräten.',
  'checkin.team_squad': '{team} › Squad {squad}',
  'branding.logo': 'Logo von {name}',
  // Online registration on the field's site server (decision S16-13)
  'player.site': 'Online-Anmeldung',
  'site.title': 'Online-Anmeldung',
  'site.intro':
      'Du meldest dich mit einem Konto auf der Website des Felds für ein '
      'Spiel an. Nutze den Button „Anmelden" auf der Seite des Spiels oder '
      'füge hier die Adresse der Seite des Felds oder des Spiels ein.',
  'site.address': 'Adresse der Seite des Felds oder des Spiels',
  'site.open': 'Öffnen',
  'site.bad_address':
      'Das ist nicht die Adresse einer Feld- oder Spielseite (https://…/f/…).',
  'site.confirm_text':
      'Du meldest dich gleich mit deinem Konto bei {host} an. Mach nur weiter, '
      'wenn das die Website des Felds ist, auf dem du spielst: Wer den Link '
      'erstellt hat, könnte eine andere Website angegeben haben.',
  'site.confirm': 'Das ist die Website, weiter',
  'site.login_at': 'Bei {host} anmelden',
  'site.login_hint':
      'Mit dem Konto, das du auf dieser Website erstellt hast. Die App behält '
      'die Sitzung auf diesem Handy; das Passwort wird nicht gespeichert.',
  'site.username': 'Benutzername',
  'site.password': 'Passwort',
  'site.login': 'Anmelden',
  'site.need_login': 'Gib Benutzername und Passwort ein.',
  'site.totp_text':
      'Dieses Konto hat Zwei-Faktor-Authentifizierung: Gib den Code aus deiner '
      'Authenticator-App ein.',
  'site.code': '6-stelliger Code',
  'site.logged_in': 'Mit dem Konto {user} bei {host}',
  'site.logout': 'Abmelden',
  'site.games': 'Spiele',
  'site.no_games':
      'Dieses Feld hat für die nächsten Tage keine Spiele veröffentlicht.',
  'site.game_gone':
      'Dieses Spiel ist nicht mehr veröffentlicht oder schon vorbei.',
  'site.cancelled': 'Abgesagt',
  'site.cancelled_reason': 'Dieses Spiel wurde abgesagt: {reason}',
  'site.open_until': 'Anmeldung offen bis {when}',
  'site.left': '{n} Plätze',
  'site.opens': 'Anmeldung öffnet {when}',
  'site.full': 'Ausgebucht',
  'site.closed': 'Anmeldung geschlossen',
  'site.no_online': 'Keine Online-Anmeldung: Frag die Orga des Felds.',
  'site.reg.registered': 'Du bist für dieses Spiel angemeldet.',
  'site.reg.checked_in': 'Du hast für dieses Spiel eingecheckt.',
  'site.reg.no_show': 'Du bist zu diesem Spiel nicht gekommen.',
  'site.reg.cancelled': 'Du hast deine Anmeldung storniert.',
  'site.form': 'Anmeldung',
  'site.form_change': 'Anmeldung ändern',
  'site.name_hint': 'Der Name, den Orga und Marshals in diesem Spiel sehen.',
  'site.replicas': 'Repliken, die du nutzt (bis zu {n})',
  'site.class_not_here': '{class}: Diese Klasse gibt es auf diesem Feld nicht',
  'site.too_many': 'Dieses Feld erlaubt bis zu {n} Repliken pro Person.',
  'site.register': 'Anmelden',
  'site.save': 'Änderungen speichern',
  'site.changed': 'Anmeldung geändert.',
  'site.cancel_reg': 'Anmeldung stornieren',
  'site.cancel_title': 'Anmeldung stornieren?',
  'site.cancel_text':
      'Du gibst deinen Platz in {game} auf, und das Check-in-Ticket gilt nicht mehr.',
  'site.cancel_yes': 'Anmeldung stornieren',
  'site.data_note':
      'Das Feld erhält den Namen, den du für das Spiel wählst, deinen '
      'Teamwunsch, deine Verbandsnummer (wenn das Spiel danach fragt) und die '
      'angemeldeten Repliken, und löscht sie 30 Tage nach dem Spiel.',
  'site.show_ticket': 'Check-in-Ticket zeigen',
  'site.no_ticket_here':
      'Das Ticket dieser Anmeldung ist nicht auf diesem Handy. Fordere ein '
      'neues an: Das alte gilt dann nicht mehr.',
  'site.new_ticket': 'Neues Ticket anfordern',
  'site.ticket': 'Check-in-Ticket',
  'site.ticket_text':
      'Zeig diesen Code am Feld einem Marshal oder checke in der App mit '
      '„Am Feld einchecken" ein und wähle diese Anmeldung. Der Text des '
      'Tickets:',
  'site.copy': 'Text kopieren',
  'site.copied': 'Kopiert.',
  'site.ticket_secret':
      'Wer dieses Ticket hat, kann an deiner Stelle einchecken: Teile es nicht.',
  'site.my_tickets': 'Meine Tickets',
  'site.no_tickets': 'Noch keine Tickets auf diesem Handy.',
  'site.claim': 'ID dieses Handys verwenden',
  'site.claim_text':
      'Wenn du mit diesem Handy bei {field} eingecheckt hast, kann das Konto '
      'dieselbe Spiel-ID übernehmen (deine Repliken und Chrono-Werte). Der '
      'Controller des Felds bestätigt das bei seiner nächsten Synchronisation.',
  'site.claim_pick': 'IDs dieses Handys',
  'site.claim_at': 'Beim Controller {field}',
  'site.claim_none': 'Dieses Handy hat noch an keinem Feld eingecheckt.',
  'site.claim_send': 'Diese ID beanspruchen',
  'site.claim_linked': 'Das Konto hat an diesem Feld schon die ID {id}.',
  'site.claim.pending':
      'Gesendet: wartet auf die Bestätigung durch den Controller des Felds.',
  'site.claim.confirmed': 'Bestätigt.',
  'site.claim.refused':
      'Der Controller des Felds hat diese ID nicht bestätigt (ein anderes '
      'Handy oder ein Check-in von Hand).',
  'site.error': 'Die Website hat abgelehnt: {error}',

  // Spielverlauf
  'history.title': 'Spielverlauf',
  'history.reload': 'Neu laden',
  'history.intro':
      'Die Spiele, an denen du teilgenommen hast, nach den Aufzeichnungen '
      'der Seite von den Feldern, an denen dieses Konto eine Spieler-ID '
      'hat: die Punktestände und deine eigenen Ereignisse.',
  'history.none':
      'Noch keine Spiele. Ein Spiel erscheint hier, sobald das Feld es an '
      'die Seite geschickt hat.',
  'history.unnamed': 'Spiel',
  'history.at': 'Auf dem Feld {field}',
  'history.state.ready': 'Nicht gestartet',
  'history.state.running': 'Läuft',
  'history.state.paused': 'Pausiert',
  'history.state.ended': 'Beendet',
  'history.winner': 'Sieger: {team}',
  'history.no_winner': 'Kein Sieger (Gleichstand oder keine Punkte).',
  'history.scores': 'Punktestände',
  'history.no_scores': 'Die Seite hat keine Punktestände für dieses Spiel.',
  'history.events': 'Deine Ereignisse',
  'history.no_events':
      'Die Seite hat keine Ereignisse von dir in diesem Spiel.',
  'history.registered': 'Du warst in diesem Spiel eingecheckt.',
  'history.you': 'du',
  'site.err.offline':
      'Die Website ist nicht erreichbar. Versuch es später nochmal.',
  'site.err.login_required': 'Die Sitzung ist abgelaufen: Melde dich neu an.',
  'site.err.invalid_credentials':
      'Falscher Benutzername oder falsches Passwort.',
  'site.err.invalid_code': 'Falscher Code. Versuch den nächsten.',
  'site.err.invalid_totp_session':
      'Der Code-Schritt ist abgelaufen: Gib dein Passwort erneut ein.',
  'site.err.too_many_attempts': 'Zu viele Versuche: Warte kurz.',
  'site.err.field_not_found': 'Diese Website hat kein solches Feld.',
  'site.err.http_404':
      'Diese Website hat keine Online-Anmeldung (ein älterer Server?).',
  'site.err.scheduled_game_not_found': 'Dieses Spiel gibt es nicht mehr.',
  'site.err.registration_not_found': 'Diese Anmeldung gibt es nicht mehr.',
  'site.err.registration_closed':
      'Die Anmeldung für dieses Spiel ist geschlossen.',
  'site.err.game_full': 'Dieses Spiel ist ausgebucht.',
  'site.err.already_registered': 'Du bist für dieses Spiel schon angemeldet.',
  'site.err.not_registered': 'Diese Anmeldung ist nicht mehr gültig.',
  'site.err.game_started': 'Das Spiel hat begonnen.',
  'site.err.federation_number_required':
      'Dieses Spiel verlangt eine Verbandsnummer.',
  'site.err.display_name_invalid': 'Der Name muss 1 bis 32 Zeichen lang sein.',
  'site.err.team_preference_invalid':
      'Dieses Team gibt es in diesem Spiel nicht.',
  'site.err.too_many_replicas': 'Zu viele Repliken für dieses Feld.',
  'site.err.replica_class_invalid':
      'Eine der Repliken hat eine Klasse, die es auf diesem Feld nicht gibt.',
  'site.err.replicas_not_asked':
      'Dieses Spiel fragt bei der Anmeldung nicht nach Repliken.',
  'site.err.player_id_exists':
      'Das Konto hat an diesem Feld schon eine Spiel-ID.',
  'site.err.player_id_taken': 'Diese ID gehört zu einem anderen Konto.',
  'site.err.player_secret_invalid': 'Das Geheimnis dieser ID ist ungültig.',
  'checkin.registered': 'Online-Anmeldung',
  'checkin.no_registration': 'Keine (spontan da)',
  'checkin.registered_hint':
      'Wenn du dich auf der Website des Felds angemeldet hast, wähle die '
      'Anmeldung: Ihr Ticket geht mit dem Check-in mit.',
  'checkin.ticket_other_id':
      'Dieses Handy hat an diesem Feld schon eine andere ID. Nutze „ID dieses '
      'Handys verwenden" in der Online-Anmeldung oder checke ohne die '
      'Anmeldung ein.',

  // Field controller (slice S6 of PE24)
  'ctl.intro':
      'Dieses Handy ist der Feld-Controller eines kleinen Spiels, ohne '
      'Raspberry Pi: Es führt das Spiel aus, stellt die GM-Konsole, den '
      'Check-in und die Anzeigetafel im WLAN des Felds bereit und spricht über '
      'einen I/O-Pod mit den Boxen. Es läuft auch bei ausgeschaltetem '
      'Bildschirm weiter.',
  'ctl.refresh': 'Aktualisieren',
  'ctl.phase_stopped': 'Gestoppt',
  'ctl.phase_starting': 'Startet…',
  'ctl.phase_running': 'Läuft',
  'ctl.phase_stopping': 'Stoppt…',
  'ctl.stopped_hint':
      'Spiele bleiben erhalten: Beim nächsten Start geht das laufende Spiel '
      'weiter.',
  'ctl.no_game': 'Kein laufendes Spiel. Erstelle eines in der Konsole.',
  'ctl.game': '{name}: {state}',
  'ctl.game_ready': 'startbereit',
  'ctl.game_running': 'läuft',
  'ctl.game_paused': 'pausiert',
  'ctl.game_ended': 'beendet',
  'ctl.clients':
      'Verbindungen: {stream} zur Konsole oder Anzeigetafel, {mqtt} über MQTT, '
      '{props} von Spielprops im WLAN.',
  'ctl.start': 'Controller starten',
  'ctl.stop': 'Controller stoppen',
  'ctl.error_storage':
      'Dieses Handy hat der App keinen privaten Ordner gegeben: Der '
      'Controller kann seine Spiele nicht speichern.',
  'ctl.error_start': 'Der Controller ist nicht gestartet.',
  'ctl.error_ended': 'Der Controller hat sich von selbst beendet.',
  'ctl.no_foreground':
      'Android hat dem Controller seine Benachrichtigung nicht erlaubt: Bei '
      'ausgeschaltetem Bildschirm kann er stoppen. Lass die App offen oder '
      'erlaube ihre Benachrichtigungen.',
  'ctl.battery':
      'Die Akku-Optimierung kann den Controller mitten im Spiel stoppen.',
  'ctl.battery_ask': 'Ausnahme anfordern',
  'ctl.network': 'Netz des Felds',
  'ctl.open': 'Im WLAN des Felds erreichbar',
  'ctl.open_on':
      'Handys, Computer und Spielprops verbinden sich über HTTPS (Port 8443, '
      'mit der CA des Felds) und MQTT (Port 1883).',
  'ctl.open_off':
      'Nur dieses Handy erreicht den Controller: Im Netz lauscht nichts.',
  'ctl.addresses': 'Die Konsole, auf Computern im Netz des Felds:',
  'ctl.no_address':
      'Dieses Handy ist in keinem WLAN: Schalte seinen Hotspot ein oder '
      'verbinde es mit dem Netz des Felds.',
  'ctl.ca': 'Fingerabdruck der CA des Felds',
  'ctl.ca_hint':
      'Er steht auf dem Check-in-Plakat: Die Handys der Spielenden prüfen ihn.',
  'ctl.wifi': 'WLAN des Felds',
  'ctl.wifi_unavailable': 'Das WLAN dieses Handys lässt sich nicht abfragen.',
  'ctl.wifi_off': 'WLAN aus',
  'ctl.wifi_network': 'Im Netz {ssid}',
  'ctl.wifi_unknown': 'In einem WLAN (für den Namen ist der Standort nötig)',
  'ctl.hotspot_on': 'Hotspot an',
  'ctl.hotspot_off': 'Hotspot aus',
  'ctl.hotspot_unknown': 'Hotspot: Zustand unbekannt',
  'ctl.hotspot_settings': 'Hotspot-Einstellungen',
  'ctl.wifi_settings': 'WLAN-Einstellungen',
  'ctl.local_intro':
      'Kein Router und kein Hotspot? Das Handy kann ein Netz nur für dieses '
      'Spiel aufbauen (Android wählt Name und Passwort und ändert sie jedes '
      'Mal: Schreib sie nicht aufs Plakat).',
  'ctl.local_start': 'Netz für das Spiel aufbauen',
  'ctl.local_stop': 'Netz des Spiels ausschalten',
  'ctl.local_on': 'Netz des Spiels: {ssid}',
  'ctl.local_password': 'Passwort: {password}',
  'ctl.local_qr':
      'QR-Code für das Netz {ssid}: Spielende scannen ihn mit der Kamera.',
  'ctl.local_error_permission':
      'Die Berechtigung für Geräte in der Nähe (oder für den Standort) fehlt.',
  'ctl.local_error_location_off':
      'Schalte den Standort ein und versuch es erneut.',
  'ctl.local_error_incompatible_mode':
      'Dieses Handy kann das Netz nicht aufbauen, solange es in einem anderen '
      'WLAN ist oder sein Hotspot an ist.',
  'ctl.local_error_tethering_disallowed':
      'Dieses Handy erlaubt nicht, seine Verbindung zu teilen.',
  'ctl.local_error_no_channel': 'Kein WLAN-Kanal ist frei.',
  'ctl.local_error_generic': 'Android hat das Netz nicht aufgebaut.',
  'ctl.local_error_unavailable': 'Dieses Handy kann keine Netze aufbauen.',
  'ctl.radio': 'Funk',
  'ctl.radio_none': 'Kein Funk: nur Spielprops im WLAN',
  'ctl.radio_pod': 'I/O-Pod: {name}',
  'ctl.radio_hint':
      'Die Boxen des Felds brauchen einen I/O-Pod, verbunden über USB oder '
      'Bluetooth.',
  'ctl.radio_locked': 'Um den Funk zu ändern, stoppe den Controller.',
  'ctl.radio_up': 'Funk aktiv',
  'ctl.radio_down': 'Funk ausgefallen',
  'ctl.radio_connecting': 'Funk wird verbunden…',
  'ctl.pod_forget': 'Pod entkoppeln',
  'ctl.codes': 'Zugangscodes',
  'ctl.codes_hint':
      'Die Konsole fragt nach einem davon. Der GM-Code steuert das Spiel: '
      'Zeig ihn nicht den Spielenden.',
  'ctl.code_gm': 'GM-Code',
  'ctl.code_read': 'Lese-Code (Anzeigetafel)',
  // Slice S7c: the field card written by this phone's NFC.
  'ctl.card': 'Feldkarte',
  'ctl.card_hint':
      'Neue Boxen kommen mit der Feldkarte in dieses Feld: Schreib sie auf '
      'eine NTAG215- oder NTAG216-Karte und halte sie einmal an jede neue '
      'Box. Boxen mit Display lassen sich auch über den Code koppeln, den '
      'sie zeigen (Reiter „Aufnehmen“ der Konsole).',
  'ctl.card_write': 'Feldkarte schreiben',
  'ctl.card_warn_title': 'Das Hauptgeheimnis des Felds',
  'ctl.card_warn':
      'Diese Karte enthält den Beitrittsschlüssel des Felds: Wer sie hat, '
      'kann Beitrittskarten für die Boxen dieses Felds erstellen und die '
      'Schlüssel späterer Spiele lesen, die per Funk gesendet werden. Schließ '
      'sie weg; geht sie verloren oder wird kopiert, braucht das Feld einen '
      'neuen Schlüssel.',
  'ctl.card_write_go': 'Karte schreiben',
  'ctl.card_done': 'Feldkarte geschrieben (Feld {fingerprint}).',
  'ctl.card_failed':
      'Die Feldkarte konnte nicht erstellt werden: versuch es noch einmal.',
  'ctl.tags': 'Tags der Spielenden',
  'ctl.tags_hint':
      'Schreibe die signierten NFC-Tags des laufenden Spiels mit dem NFC '
      'dieses Handys. Der Spielschlüssel bleibt auf diesem Handy.',
  'ctl.tags_none':
      'Starte zuerst ein Spiel: Tags werden mit dem Schlüssel des laufenden '
      'Spiels signiert.',
  'ctl.tags_open': 'Tags der Spielenden schreiben',
  'ctl.firmware': 'Firmware-Updates',
  'ctl.fw_keys': 'Firmware-Release-Schlüssel',
  'ctl.fw_keys_none':
      'Keine: Dieser Controller nimmt kein Firmware-Release für die Boxen an.',
  'ctl.fw_keys_set':
      '{n} Schlüssel: Releases, die sie signieren, werden angenommen.',
  'ctl.fw_keys_hint':
      'Die öffentlichen Hälften der Release-Schlüssel (Base64, je 44 '
      'Zeichen), einer pro Zeile, wie in [firmware] release_keys des Pi. '
      'Die Boxen prüfen jedes Release noch einmal mit den Schlüsseln in '
      'ihrer eigenen Firmware. Ein laufender Controller startet dafür neu.',
  'ctl.fw_keys_bad':
      'Jeder Schlüssel hat 44 Base64-Zeichen (32 Bytes); höchstens 8.',
  'ctl.code_hidden': 'Verborgen',
  'ctl.show_codes': 'Codes zeigen',
  'ctl.hide_codes': 'Codes verbergen',
  'ctl.copy': 'Kopieren: {what}',
  'ctl.copied': 'Kopiert: {what}',
  'ctl.console': 'GM-Konsole',
  'ctl.open_console': 'Konsole öffnen',
  'ctl.console_title': 'Konsole dieses Controllers',
  'ctl.no_console':
      'Diese App wurde ohne die Dateien der Konsole gebaut: Öffne sie von '
      'einem Computer aus.',
  'ctl.poster_hint':
      'Um das Check-in-Plakat zu drucken, öffne {url} auf einem Computer im '
      'Netz des Felds (Tab Check-in).',
  'ctl.poster_hint_closed':
      'Für das Check-in-Plakat muss der Controller im WLAN des Felds '
      'erreichbar sein.',
  'ctl.notif_title': 'Atalaia: Feld-Controller',
  'ctl.notif_starting': 'Startet…',
  'ctl.notif_idle': 'Kein laufendes Spiel',
  'ctl.notif_game': '{name}: {state}',
  // The phone controller's [modes] settings (slice S7b of PE24).
  'ctl_modes.title': 'Moduspakete',
  'ctl_modes.tile': 'Moduspakete (Feld-Controller)',
  'ctl_modes.tile_hint':
      '{keys} vertrauenswürdige Schlüssel, {box} Box-Schlüssel',
  'ctl_modes.intro':
      'Die Schlüssel, denen der Feld-Controller dieses Handys bei signierten Moduspaketen vertraut, die Schlüssel in der Firmware der Boxen (der Controller bietet den Boxen nur Pakete an, die sie annehmen), widerrufene Schlüssel und der Index des Registers: der Abschnitt [modes] eines Pi. Sie gelten ab dem nächsten Start des Controllers.',
  'ctl_modes.keys':
      'Vertrauenswürdige Modusschlüssel (einer pro Zeile, Base64)',
  'ctl_modes.box_keys': 'Modusschlüssel der Boxen (einer pro Zeile, Base64)',
  'ctl_modes.revoked':
      'IDs widerrufener Schlüssel (eine pro Zeile, 16 Hexziffern)',
  'ctl_modes.index':
      'Index des Registers (eine https://-Adresse oder eine Datei; optional)',
  'ctl_modes.bad_key':
      'Zeile {line}: kein Modusschlüssel (Base64 von 32 Bytes).',
  'ctl_modes.bad_id': 'Zeile {line}: keine Schlüssel-ID (16 Hexziffern).',
  'ctl_modes.bad_index': 'Der Index ist eine https://-Adresse oder eine Datei.',
  'ctl_modes.saved': 'Gespeichert: gilt ab dem nächsten Start des Controllers.',
  // The phone controller's slice S7 settings (PE24-118 onward).
  'ctl_site.tile': 'Site-Server, Ausfallübernahme und ATAK (Feld-Controller)',
  'ctl_site.tile_hint':
      'Ausfallübernahme {mode}; Site-Server {sync}; ATAK {atak}',
  'ctl_site.on': 'an',
  'ctl_site.off': 'aus',
  'ctl_site.title': 'Site-Server, Ausfallübernahme und ATAK',
  'ctl_site.intro':
      'Der Feld-Controller dieses Handys so, wie ihn die controller.toml eines Pi festlegt: seine Ausfallübernahme, der Site-Server des Felds (Spiele, Protokolle und Punkte gehen dorthin, sobald Internet da ist; Anmeldelisten, Branding und die Szenariobibliothek kommen von dort) und der ATAK-Feed. Gilt ab dem nächsten Start des Controllers.',
  'ctl_site.failover': 'Ausfallübernahme',
  'ctl_site.failover_auto': 'Automatische Ausfallübernahme',
  'ctl_site.manual': 'Manuell',
  'ctl_site.auto': 'Automatisch',
  'ctl_site.failover_hint':
      'Manuell: Die Spielleitung befördert einen Bereitschafts-Controller. Automatisch: Ein Bereitschafts-Controller übernimmt nach drei verpassten Signalen (30 s). Ein Handy im Akkubetrieb gibt einem Pi am Netz den Vortritt, wenn beide kandidieren.',
  'ctl_site.sync': 'Site-Server',
  'ctl_site.sync_hint': 'Offline zuerst: Ein Spiel wartet nie auf das Netz.',
  'ctl_site.url': 'Adresse (https://…)',
  'ctl_site.key': 'API-Schlüssel des Felds (vom Site-Server)',
  'ctl_site.key_set':
      'API-Schlüssel {fp}… (einen neuen eingeben, um ihn zu ersetzen)',
  'ctl_site.branding':
      'Branding, gespeicherte Teams und Check-in-Einstellungen des Felds vom Site-Server',
  'ctl_site.library': 'Szenarien und Spielvorlagen des Felds vom Site-Server',
  'ctl_site.remote_gm': 'Remote-Spielleitung',
  'ctl_site.remote_gm_hint':
      'Die Spielleitung des Felds auf dem Site-Server darf das laufende Spiel starten, pausieren und beenden. Standardmäßig aus.',
  'ctl_site.atak': 'ATAK-Feed (Cursor on Target)',
  'ctl_site.atak_hint':
      'Die Boxen und Zonen auf ATAK-Karten, über das WLAN des Felds.',
  'ctl_site.multicast': 'Multicast-Adresse (239.2.3.1:6969)',
  'ctl_site.staff': 'ATAK-Geräte der Orga (Host:Port, durch Kommas getrennt)',
  'ctl_site.players':
      'Spielerpositionen an die Geräte der Orga (nie per Multicast)',
  'ctl_site.remote': 'Remote-ATAK über den Site-Server',
  'ctl_site.remote_players': 'Auch Spielerpositionen über den Site-Server',
  'ctl_site.bad_sync': 'Site-Server: {why}',
  'ctl_site.bad_atak': 'ATAK: {why}',
  'apd.section': 'APD-Mitgliedschaft',
  'apd.accepts_any': 'Jede APD wird akzeptiert.',
  'apd.accepts': 'Akzeptierte APDs: {list}',
  'apd.pick': 'Deine APD',
  'apd.unlisted': 'Nicht in der Liste',
  'apd.number': 'Mitgliedsnummer',
  'apd.number_required': 'Mitgliedsnummer (erforderlich)',
  'apd.expires': 'Gültig bis (JJJJ-MM-TT)',
  'apd.expires_required': 'Gültig bis, JJJJ-MM-TT (erforderlich)',
  'apd.date_format': '2027-01-31',
  'apd.hint':
      'Die App prüft sie nicht: Ein Marshal vergleicht sie mit deinem Ausweis.',
  'apd.need_number': 'Dieses Feld verlangt deine APD-Mitgliedsnummer.',
  'apd.need_expiry':
      'Dieses Feld verlangt das Ablaufdatum deiner Mitgliedschaft.',
  'apd.bad_date':
      'Das Datum als JJJJ-MM-TT schreiben, zum Beispiel 2027-01-31.',
  'apd.until': 'bis {date}',
  'apd.overridden': 'von einem Marshal zugelassen',
  'apd.status.valid': 'Mitgliedschaft gültig',
  'apd.status.expired': 'Mitgliedschaft abgelaufen',
  'apd.status.not_accepted': 'APD hier nicht akzeptiert',
  'apd.status.missing': 'Mitgliedschaft fehlt',
  'apd.hint_marshal': 'Ein Marshal sieht sich deinen Mitgliedsausweis an.',
  'queue.confirm': 'Zulassen',
  'site.err.membership_missing':
      'Dieses Feld braucht für die Anmeldung deine APD-Mitgliedsnummer.',
  'site.err.apd_not_accepted': 'Dieses Feld akzeptiert diese APD nicht.',
  'site.err.membership_expired':
      'Die Mitgliedschaft ist am Tag dieses Spiels abgelaufen.',
  // The remote GM may see shared positions (PKD-5)
  'player.share_remote_gm':
      'Hat das Feld eine Remote-Spielleitung, die im Site-Server angemeldet ist, sieht die Remote-Spielleitung deine Position ebenfalls, solange du sie teilst. Der Site-Server speichert sie nicht.',
};
