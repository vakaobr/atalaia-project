<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Translation glossary

One word for one thing, in every part of the project: the project page, the GM console,
the mode editor, the app and the Field Box's screens. Translators use these words; a
reviewer who finds a better one changes it here first, then in every file (`python3
tools/i18n_check.py` lists the files per language). See [README.md](README.md) for the
process.

**Status of the German column: drafted by an AI model (2026-10-22), not yet reviewed by a
native-speaking player** (decision P5H-5; `status.yaml`). Words marked *(check)* are the
ones a reviewer should look at first.

## How each language is written

| | Portuguese (pt-PT) | German (de) |
|---|---|---|
| Who is addressed | "tu" (Mantém premido, Escolhe) | "du", lower case (Halte gedrückt, Wähle) as German airsoft clubs and forums write; buttons in the infinitive (Speichern, Starten) |
| People | inclusive, without gendered forms: "quem joga", "participante", "a organização" | neutral forms where they read naturally: "Spielende", "Teilnehmende", "die Spielleitung", "das Team"; no gender star or colon; when nothing neutral reads well, rephrase ("wer spielt") rather than use the generic masculine |
| English loanwords | where Portuguese players use them: Respawn, marshal, squad, GM | as German players use them: Respawn, Spawn, Medic, Marshal, Squad, Team, Briefing, Domination, Chrono |
| Numbers | decimal comma (1,3 J) | decimal comma (1,3 J), a dot for thousands only when needed |
| Quotation marks | « » | „ " |
| Dates | 8 de novembro de 2026 | 8. November 2026 |

## Terms

| English | Portuguese (pt-PT) | German (de) | Notes |
|---|---|---|---|
| game master, GM | organização, GM | Spielleitung, GM | "Spielleitung" (also "SL", "Orga") is what German airsoft events call the organisers; GM in short labels |
| organisers (staff) | organização | Orga, Spielleitung | |
| marshal | marshal | Marshal | used as is at German milsim events *(check: some clubs say "Schiedsrichter")* |
| player | quem joga, jogador/a | Spielende, wer spielt | "Spieler:in" is not used (P5H-5: no gender colon); the role in a menu: *Spielen* |
| participant | participante | Teilnehmende | |
| spectator | espectador/a | Zuschauende | |
| squad leader | líder de squad | Squad-Lead | *(check: "Squadleader", "Gruppenführung")* |
| team | equipa | Team | "Mannschaft" sounds like football |
| squad | squad | Squad | |
| field | campo | Spielfeld, Feld | |
| game (one round) | jogo | Spiel, Runde | |
| game mode | modo de jogo | Spielmodus | |
| mode (short) | modo | Modus | plural Modi |
| scenario | cenário | Szenario | |
| objective | objetivo | Ziel | the scenario's objectives: "Szenario-Ziele" |
| target (to shoot) | alvo | Zielscheibe, Ziel | |
| zone | zona | Zone | |
| capture | capturar | einnehmen | "Zone einnehmen" |
| neutral (zone nobody holds) | LIVRE | FREI | |
| held (a zone) | ocupada | gehalten | |
| bomb | bomba | Bombe | |
| arm / armed | armar / armada | scharf machen, schärfen / SCHARF | "einen Zünder schärfen" is the military term |
| defuse / defused | desarmar / desarmada | entschärfen / ENTSCHÄRFT | |
| explode | explodir | explodieren, hochgehen | |
| respawn | respawn, reentrada | Respawn | "zum Respawn gehen" |
| lives | vidas | Leben | |
| medic | medic | Medic | |
| bandage | ligadura | Verband | |
| hit | baixa, toque | Treffer | "Treffer!" is what players call |
| kill confirmed (the tag) | baixa confirmada | Kill bestätigt | |
| check-in | registo de presença, check-in | Check-in | |
| chrono (power check) | cronografagem, cronógrafo | Chrono, chronen | "Chrono-Wert", "gechront" |
| replica | réplica | Replik | *(check: many players just say "Airsoft" or "Waffe")* |
| joule limit | limite em joules | Joule-Limit | |
| game prop | dispositivo de jogo | Spielprop, Prop | *(check)* |
| Field Box | Field Box, caixa | Field Box, Box | product name kept |
| box (any game device) | caixa | Box | |
| field controller | controlador de campo | Feld-Controller | |
| GM console | consola do GM | GM-Konsole | |
| site server | servidor do site | Site-Server | |
| player app | app | App | "die App" |
| mode editor | editor de modos | Modus-Editor | |
| radio | rádio | Funk | LoRa radio: "LoRa-Funk" |
| channel | canal | Kanal | |
| join (a game) | juntar, entrar | beitreten | |
| invite (a box) | convidar | einladen | |
| adopt (a box into a field) | adotar | aufnehmen | the box becomes the field's |
| pair | emparelhar | koppeln | |
| firmware update | atualização de firmware | Firmware-Update | |
| admin PIN | PIN de administração | Admin-PIN | |
| scoreboard | marcador | Anzeigetafel, Scoreboard | |
| score / points | pontuação / pontos | Punktestand / Punkte | |
| pause / paused | pausa / em pausa | Pause / PAUSIERT | |
| game over | fim do jogo | SPIEL VORBEI | never "Spielende", which reads as "the players" (P5H-10) |
| waiting | à espera | WARTEN | |
| ready | pronta | BEREIT | |
| settings | definições | Einstellungen | |
| signed package | pacote assinado | signiertes Paket | |
| mode key / manifest / sign | chave de modos / manifesto / assinar | Modus-Schlüssel / Manifest / signieren | the editor's *Make the package* (P5I-1 to P5I-6) |
| registry | registo | Registry | |
| licence | licença | Lizenz | |
| Wi-Fi | Wi-Fi | WLAN | |
| phone | telemóvel | Handy | |
| keypad | teclado | Tastenfeld | |
| NFC tag | etiqueta NFC | Tag | |
| join card / key / code | cartão / chave / código de entrada | Beitrittskarte / -schlüssel / -code | |
| field card | cartão de campo | Feldkarte | |
| standby controller | controlador de reserva | Bereitschafts-Controller | |
| airtime | tempo de emissão | Sendezeit | "Duty Cycle" kept |
| map features | marcações no mapa | Kartenelemente | Safe Zone, HQ kept in English |
| floor plan / level | planta / piso | Grundriss / Ebene | |
| crest | emblema | Wappen | |
| federation number | número de federado | Verbandsnummer | |
| callsign | alcunha | Callsign | |
| spot check | verificação aleatória (check) | Stichprobe | |
| bolt action | ferrolho | Repetierer | Sniper, Shotgun kept |
| bomb site | local da bomba | Bombenplatz | |
| reveal (an objective) | revelar | aufdecken | |
| remote GM | GM remoto | Remote-Spielleitung | |
| field owners | donos de campo | Feldbetreibende | |
| modifier / role package | modificador / pacote de papel | Modifikator / Rollenpaket | |
| event (in a script) | evento | Ereignis | |
| build guide | guia de montagem | Bauanleitung | the project page's `/montagem/`, `/de/bauen/` (P5J-11) |
| Satellite (the box) | caixa satélite, satélite | Satellit, Satelliten-Box | |
| I/O pod | módulo de E/S | I/O-Pod | |
| target addon | módulo de alvo | Ziel-Addon | *(check)* |
| enclosure switch (tamper) | interruptor da caixa | Gehäuseschalter | the alert: "violação" / "Manipulationsalarm" *(check)* |
| Li-ion cell | célula (de iões de lítio) | Zelle, Akku | "pilha" is a disposable battery |

## Mode names

German players use most English mode names as they are; the German name is what the GM
console and the app show when a mode's `mode.yaml` gets an `i18n.de` block (P5H-7: not yet).

| English | Portuguese (pt-PT) | German (de) |
|---|---|---|
| Domination | Domínio | Domination |
| Hold-All Domination | Domínio Total | Hold-All Domination |
| Bomb / Rush | Bomba / Rush | Bombe / Rush |
| Last Stand | Último Elemento | Last Stand |
| Kill Confirmed | Baixa Confirmada | Kill Confirmed |
| Respawn and Lives | Reentradas e Vidas | Respawn und Leben |
| Player Check-in | Registo de Presença | Check-in |
| Codes | Códigos | Codes |
| Medic Kit | Ligaduras | Medic-Kit |
| Master and Satellites | Mestre e Satélites | Master und Satelliten |
| Target Windows | Janelas de Alvo | Zielfenster |
| VIP / Payload | VIP / Carga | VIP / Payload |
| Hacking Terminal | Hackeia o terminal | Hacking-Terminal |
| Objectives | Objetivos | Ziele |
