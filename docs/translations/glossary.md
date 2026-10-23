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

**Status of the German and Traditional Chinese (zh-tw) columns: drafted by an AI model
(2026-10-22), not yet reviewed by a native-speaking player** (decisions P5H-5, P5K-11;
`status.yaml`). Words marked *(check)* are the ones a reviewer should look at first.

## How each language is written

| | Portuguese (pt-PT) | German (de) | Traditional Chinese, Taiwan (zh-tw) |
|---|---|---|---|
| Who is addressed | "tu" (Mantém premido, Escolhe) | "du", lower case (Halte gedrückt, Wähle) as German airsoft clubs and forums write; buttons in the infinitive (Speichern, Starten) | 「你」（不用「您」，也不用「妳」），如台灣生存遊戲社團與論壇的寫法；按鈕用動詞（儲存、開始） |
| People | inclusive, without gendered forms: "quem joga", "participante", "a organização" | neutral forms where they read naturally: "Spielende", "Teilnehmende", "die Spielleitung", "das Team"; no gender star or colon; when nothing neutral reads well, rephrase ("wer spielt") rather than use the generic masculine | 「你」「玩家」「參加者」「主辦」本身就不分性別；不用「他／她」，必要時改寫句子 |
| English loanwords | where Portuguese players use them: Respawn, marshal, squad, GM | as German players use them: Respawn, Spawn, Medic, Marshal, Squad, Team, Briefing, Domination, Chrono | 台灣玩家照用的：GM、Respawn（也說「復活」）、Hit、VIP、LoRa、Wi-Fi、App、NFC；其餘用中文 |
| Numbers | decimal comma (1,3 J) | decimal comma (1,3 J), a dot for thousands only when needed | 小數點（1.3 J）；中文與英文、數字之間留半形空格（GM 控制台、3 秒） |
| Quotation marks | « » | „ " | 「 」，引號中的引號『 』；全形標點（，。：；！？（）） |
| Dates | 8 de novembro de 2026 | 8. November 2026 | 2026 年 11 月 8 日 |

## Terms

| English | Portuguese (pt-PT) | German (de) | Traditional Chinese (zh-tw) | Notes |
|---|---|---|---|---|
| game master, GM | organização, GM | Spielleitung, GM | 主辦、GM | "Spielleitung" (also "SL", "Orga") is what German airsoft events call the organisers; GM in short labels; zh-tw: 台灣活動稱主辦單位「主辦」；短標籤用 GM |
| organisers (staff) | organização | Orga, Spielleitung | 主辦、工作人員 | |
| marshal | marshal | Marshal | 裁判 | used as is at German milsim events *(check: some clubs say "Schiedsrichter")*; zh-tw: 台灣場地與活動稱 marshal 為「裁判」 *(check)* |
| player | quem joga, jogador/a | Spielende, wer spielt | 玩家 | "Spieler:in" is not used (P5H-5: no gender colon); the role in a menu: *Spielen* |
| participant | participante | Teilnehmende | 參加者 | |
| spectator | espectador/a | Zuschauende | 觀眾 | |
| squad leader | líder de squad | Squad-Lead | 小隊長 | *(check: "Squadleader", "Gruppenführung")* |
| team | equipa | Team | 隊伍、隊 | "Mannschaft" sounds like football; zh-tw: 顏色加「隊」：紅隊、藍隊 |
| squad | squad | Squad | 小隊 | |
| field | campo | Spielfeld, Feld | 場地 | zh-tw: 生存遊戲場 |
| game (one round) | jogo | Spiel, Runde | 一場遊戲、對局 | zh-tw: 「這場遊戲」；標題用「遊戲」 |
| game mode | modo de jogo | Spielmodus | 遊戲模式 | |
| mode (short) | modo | Modus | 模式 | plural Modi |
| scenario | cenário | Szenario | 劇本 | zh-tw: milsim 活動的「劇本」 *(check)* |
| objective | objetivo | Ziel | 任務目標、目標 | the scenario's objectives: "Szenario-Ziele" |
| target (to shoot) | alvo | Zielscheibe, Ziel | 標靶 | |
| zone | zona | Zone | 據點 | zh-tw: 佔點模式的「據點」 |
| capture | capturar | einnehmen | 佔領 | "Zone einnehmen"; zh-tw: 「佔領據點」 |
| neutral (zone nobody holds) | LIVRE | FREI | 中立 | zh-tw: 盒子畫面：中立 |
| held (a zone) | ocupada | gehalten | 已佔領 | |
| bomb | bomba | Bombe | 炸彈 | |
| arm / armed | armar / armada | scharf machen, schärfen / SCHARF | 啟動 / 已啟動 | "einen Zünder schärfen" is the military term; zh-tw: 玩家口語「下包」不用 *(check)* |
| defuse / defused | desarmar / desarmada | entschärfen / ENTSCHÄRFT | 拆除 / 已拆除 | zh-tw: 「拆彈」 |
| explode | explodir | explodieren, hochgehen | 爆炸 | |
| respawn | respawn, reentrada | Respawn | 復活 | "zum Respawn gehen"; zh-tw: 「回復活區」 |
| lives | vidas | Leben | 命數 | |
| medic | medic | Medic | 醫護兵 | |
| bandage | ligadura | Verband | 繃帶 | |
| hit | baixa, toque | Treffer | 中彈 | "Treffer!" is what players call; zh-tw: 玩家也喊「Hit」 |
| kill confirmed (the tag) | baixa confirmada | Kill bestätigt | 擊殺確認 | |
| check-in | registo de presença, check-in | Check-in | 報到 | |
| chrono (power check) | cronografagem, cronógrafo | Chrono, chronen | 測速 | "Chrono-Wert", "gechront"; zh-tw: 「過測速」「測速值」 |
| replica | réplica | Replik | 槍、生存槍 | *(check: many players just say "Airsoft" or "Waffe")*; zh-tw: *(check)* |
| joule limit | limite em joules | Joule-Limit | 焦耳限制 | |
| game prop | dispositivo de jogo | Spielprop, Prop | 遊戲道具 | *(check)* |
| Field Box | Field Box, caixa | Field Box, Box | Field Box、盒子 | product name kept; zh-tw: 產品名不譯 |
| box (any game device) | caixa | Box | 盒子 | |
| field controller | controlador de campo | Feld-Controller | 場地控制器 | |
| GM console | consola do GM | GM-Konsole | GM 控制台 | |
| site server | servidor do site | Site-Server | 場地伺服器 | |
| player app | app | App | App | "die App" |
| mode editor | editor de modos | Modus-Editor | 模式編輯器 | |
| radio | rádio | Funk | 無線電 | LoRa radio: "LoRa-Funk"; zh-tw: LoRa 無線電 |
| channel | canal | Kanal | 頻道 | |
| join (a game) | juntar, entrar | beitreten | 加入 | |
| invite (a box) | convidar | einladen | 邀請 | |
| adopt (a box into a field) | adotar | aufnehmen | 綁定 | the box becomes the field's; zh-tw: 盒子成為這個場地的 *(check)* |
| pair | emparelhar | koppeln | 配對 | |
| firmware update | atualização de firmware | Firmware-Update | 韌體更新 | zh-tw: 台灣用「韌體」 |
| admin PIN | PIN de administração | Admin-PIN | 管理 PIN 碼 | |
| scoreboard | marcador | Anzeigetafel, Scoreboard | 記分板 | |
| score / points | pontuação / pontos | Punktestand / Punkte | 分數 / 分 | |
| pause / paused | pausa / em pausa | Pause / PAUSIERT | 暫停 / 已暫停 | |
| game over | fim do jogo | SPIEL VORBEI | 遊戲結束 | never "Spielende", which reads as "the players" (P5H-10) |
| waiting | à espera | WARTEN | 等待中 | |
| ready | pronta | BEREIT | 就緒 | |
| settings | definições | Einstellungen | 設定 | |
| signed package | pacote assinado | signiertes Paket | 已簽署的套件 | |
| mode key / manifest / sign | chave de modos / manifesto / assinar | Modus-Schlüssel / Manifest / signieren | 模式金鑰 / 清單 / 簽署 | the editor's *Make the package* (P5I-1 to P5I-6) |
| registry | registo | Registry | 模式登錄庫 | |
| licence | licença | Lizenz | 授權條款 | |
| Wi-Fi | Wi-Fi | WLAN | Wi-Fi | |
| phone | telemóvel | Handy | 手機 | |
| keypad | teclado | Tastenfeld | 按鍵 | zh-tw: 數字按鍵 |
| NFC tag | etiqueta NFC | Tag | NFC 標籤 | |
| join card / key / code | cartão / chave / código de entrada | Beitrittskarte / -schlüssel / -code | 加入卡 / 加入金鑰 / 加入代碼 | |
| field card | cartão de campo | Feldkarte | 場地卡 | |
| standby controller | controlador de reserva | Bereitschafts-Controller | 備援控制器 | |
| airtime | tempo de emissão | Sendezeit | 發射時間 | "Duty Cycle" kept; zh-tw: Duty Cycle 照用 |
| map features | marcações no mapa | Kartenelemente | 地圖標記 | Safe Zone, HQ kept in English; zh-tw: Safe Zone、HQ 照用英文 |
| floor plan / level | planta / piso | Grundriss / Ebene | 平面圖 / 樓層 | |
| map grid / grid square ("C4") | quadrícula / quadrícula C4 | Gitter / Planquadrat C4 | 方格 / 方格 C4 | rows are letters (zh-tw: 列), columns numbers (欄); "grelha" stays the boxes' plain placeholder grid (MF-91) |
| crest | emblema | Wappen | 隊徽 | |
| federation number | número de federado | Verbandsnummer | 協會會員編號 | |
| callsign | alcunha | Callsign | 呼號 | |
| spot check | verificação aleatória (check) | Stichprobe | 抽查 | |
| bolt action | ferrolho | Repetierer | 手拉 | Sniper, Shotgun kept; zh-tw: 「手拉狙」；Sniper、Shotgun 照用 |
| bomb site | local da bomba | Bombenplatz | 炸彈點 | |
| reveal (an objective) | revelar | aufdecken | 揭露 | |
| remote GM | GM remoto | Remote-Spielleitung | 遠端 GM | |
| field owners | donos de campo | Feldbetreibende | 場主 | |
| modifier / role package | modificador / pacote de papel | Modifikator / Rollenpaket | 附加規則 / 角色套件 | |
| event (in a script) | evento | Ereignis | 事件 | |
| build guide | guia de montagem | Bauanleitung | 組裝指南 | the project page's `/montagem/`, `/de/bauen/` (P5J-11) |
| Satellite (the box) | caixa satélite, satélite | Satellit, Satelliten-Box | 衛星盒 | |
| I/O pod | módulo de E/S | I/O-Pod | I/O 模組 | |
| target addon | módulo de alvo | Ziel-Addon | 標靶擴充模組 | *(check)*; zh-tw: *(check)* |
| enclosure switch (tamper) | interruptor da caixa | Gehäuseschalter | 外殼開關 | the alert: "violação" / "Manipulationsalarm" *(check)*; zh-tw: 警報：「防拆警報」 |
| Li-ion cell | célula (de iões de lítio) | Zelle, Akku | 鋰電池芯、電芯 | "pilha" is a disposable battery |
| resettable fuse (PTC) | fusível rearmável | rückstellbare Sicherung | 可自恢復保險絲 | the target addon's port (P5J-16) *(check)* |
| pull-up resistor | resistência de pull-up | Pull-up-Widerstand | 上拉電阻 | I2C; "pull-up" stays English in pt and de |
| interrupt line | linha de interrupção | Interrupt-Leitung | 中斷線 | |
| heal (at a medic kit) | tratamento | Behandlung | 治療、次 | the kit's charges: *Verbände* ("Noch 4 Verbände"); zh-tw: 「還剩 4 次」 (P5H-12) |
| puzzle (Hacking Terminal) | enigma | Rätsel | 謎題 | zh-tw: a code guess as Taiwan's 1A2B game writes it (「2A2B」) *(check)* |
| wire (to cut) | fio | Draht (kappen) | 電線（剪斷） | *(check)* |
| factory / bank (Money Factory) | fábrica / banco | Fabrik / Bank | 印鈔廠 / 銀行 | collect / bank: *abholen* / *einzahlen*; zh-tw: 領錢 / 存入 |
| payload | carga | Payload | 護送目標 | |
| extraction zone | zona de extração | Extraktionszone, Extraktion | 撤離區 | |
| checkpoint (VIP) | ponto de controlo | Checkpoint | 檢查點 | |
| session (signed in) | sessão | Sitzung | 工作階段 | the site server's staff pages *(check)* |

## Mode names

German players use most English mode names as they are; the German name is what the GM
console and the app show from the mode's `mode.yaml` (`i18n.de`, P5H-12). The Chinese names are
what Taiwan's players would call these games (`i18n.zh-tw`, P5K-13). Both drafted by an AI model,
not yet reviewed.

| English | Portuguese (pt-PT) | German (de) | Traditional Chinese (zh-tw) |
|---|---|---|---|
| Domination | Domínio | Domination | 佔點 |
| Hold-All Domination | Domínio Total | Hold-All Domination | 全佔點 |
| Bomb / Rush | Bomba / Rush | Bombe / Rush | 炸彈 / Rush |
| Last Stand | Último Elemento | Last Stand | 最後一人 |
| Kill Confirmed | Baixa Confirmada | Kill Confirmed | 擊殺確認 |
| Respawn and Lives | Reentradas e Vidas | Respawn und Leben | 復活與命數 |
| Player Check-in | Registo de Presença | Check-in | 玩家報到 |
| Codes | Códigos | Codes | 密碼 |
| Medic Kit | Ligaduras | Medic-Kit | 醫護包 |
| Master and Satellites | Mestre e Satélites | Master und Satelliten | 主站與衛星 |
| Target Windows | Janelas de Alvo | Zielfenster | 標靶時窗 |
| VIP / Payload | VIP / Carga | VIP / Payload | VIP / 護送 |
| Hacking Terminal | Hackeia o terminal | Hacking-Terminal | 駭客終端 |
| Objectives | Objetivos | Ziele | 任務目標 |
| Money Factory | Fábrica de Dinheiro | Money Factory | 印鈔廠 *(check)* |
