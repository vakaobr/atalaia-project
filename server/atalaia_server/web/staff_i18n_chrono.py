# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The texts of the staff page for a field's chrono violations and the rules on them (PRIV-2), merged into
``staff_i18n.STRINGS``.

Same rules as ``staff_i18n.py``: pt-PT inclusive and impersonal, German with "du" and neutral nouns, Traditional Chinese
(Taiwan) with 你, full-width punctuation after Han and a half-width space between Han and Latin letters or digits.
German and Traditional Chinese were drafted by an AI model (Claude) on 2026-10-30 and are not yet reviewed by a
native-speaking player. The "repeat" label is worded as an advisory for the person who decides, never as a finding
about the player (GDPR Art. 22: the server decides nothing; the field's staff do).
"""

from __future__ import annotations

PT: dict[str, str] = {
    "chrono_warn_fixed": "Regra fixa, aprovada com o parecer jurídico: uma advertência isolada nunca conta como violação anterior. Uma proibição de jogar dura 12 meses, salvo se o campo definir menos, e nunca mais do que o campo guarda os registos.",
    "nav_chrono": "Cronografagem",
    "chrono_title": "Cronografagem: violações e regras",
    "chrono_intro": "As verificações aleatórias que ficaram acima do limite ou da tolerância e o que a organização "
                    "decidiu. O servidor não decide nada: regista o que o controlador mediu e o que a organização "
                    "escolhe aqui.",
    "chrono_rules_title": "Regras do campo",
    "chrono_rules_intro": "A regra que a organização define e que fica à vista de quem a aplica.",
    "chrono_ban_days": "Duração de uma proibição de jogar (dias)",
    "chrono_ban_hint": "Vazio: 12 meses. Nunca passa o tempo que o campo guarda os registos de cronografagem: a violação "
                       "e a proibição apagam-se juntas. O servidor não avisa ninguém: quem regista a proibição "
                       "diz à pessoa quando termina.",
    "chrono_rules_save": "Guardar as regras",
    "chrono_rules_saved": "Regras guardadas.",
    "chrono_viol_title": "Violações",
    "chrono_viol_none": "Nenhuma violação registada.",
    "chrono_col_time": "Quando",
    "chrono_col_player": "Quem joga",
    "chrono_col_type": "Tipo",
    "chrono_col_energy": "Energia (J)",
    "chrono_col_over": "Acima do limite (J)",
    "chrono_col_flag": "Aviso",
    "chrono_col_outcome": "Decisão",
    "chrono_col_ban": "Proibição",
    "chrono_type_over_limit": "acima do limite",
    "chrono_type_over_tolerance": "dentro da tolerância (aviso)",
    "chrono_flag_repeat": "Já houve uma violação anterior",
    "chrono_flag_repeat_note": "Aviso para quem decide, não uma decisão sobre esta pessoa.",
    "chrono_outcome_open": "por decidir",
    "chrono_outcome_warning": "advertência",
    "chrono_outcome_pulled": "réplica retirada do jogo",
    "chrono_outcome_ban": "proibição de jogar",
    "chrono_choose": "Decisão",
    "chrono_record": "Registar",
    "chrono_recorded": "Decisão registada.",
    "chrono_ban_until": "até {when}",
    "chrono_ban_ended": "terminou em {when}",
    "chrono_advisory": "A marca «Já houve uma violação anterior» é só um aviso calculado pelo servidor a partir dos "
                       "registos deste campo (advertências isoladas nunca contam). Não prova nada e "
                       "nenhuma decisão assenta só nela: quem decide é a organização, vendo o registo.",
    "chrono_contest_title": "Quem quiser contestar",
    "chrono_contest": "Não há aqui um processo de recurso. Quem quiser contestar um registo fala com o campo, pelo "
                      "contacto indicado na página do campo, e pode usar os direitos que o aviso de privacidade "
                      "descreve (acesso, retificação, apagamento) e opor-se ao tratamento (art. 21.º do RGPD). A organização do campo decide e pode corrigir ou "
                      "apagar o registo.",
    "e_chrono_ban_days_invalid": "A duração tem de ser de 1 dia até ao tempo que o campo guarda os registos de "
                                 "cronografagem.",
}

EN: dict[str, str] = {
    "chrono_warn_fixed": "A fixed rule, approved with the legal brief: a plain warning never counts as an earlier violation. A ban lasts 12 months unless the field sets less, and never longer than the field keeps chrono records.",
    "nav_chrono": "Chrono",
    "chrono_title": "Chrono: violations and rules",
    "chrono_intro": "The spot checks that went over the limit or the tolerance, and what the organisers decided. The "
                    "server decides nothing: it records what the controller measured and what the organisers choose "
                    "here.",
    "chrono_rules_title": "The field's rules",
    "chrono_rules_intro": "The rule the organisers set, in plain view of whoever applies it.",
    "chrono_ban_days": "How long a ban lasts (days)",
    "chrono_ban_hint": "Empty: 12 months. It never lasts longer than the field keeps chrono records: the violation and "
                       "the ban are deleted together. The server tells no one: whoever records a ban tells the "
                       "person when it ends.",
    "chrono_rules_save": "Save the rules",
    "chrono_rules_saved": "Rules saved.",
    "chrono_viol_title": "Violations",
    "chrono_viol_none": "No violations recorded.",
    "chrono_col_time": "When",
    "chrono_col_player": "Player",
    "chrono_col_type": "Type",
    "chrono_col_energy": "Energy (J)",
    "chrono_col_over": "Over the limit (J)",
    "chrono_col_flag": "Notice",
    "chrono_col_outcome": "Decision",
    "chrono_col_ban": "Ban",
    "chrono_type_over_limit": "over the limit",
    "chrono_type_over_tolerance": "within tolerance (warning)",
    "chrono_flag_repeat": "There was an earlier violation",
    "chrono_flag_repeat_note": "A notice for whoever decides, not a decision about this person.",
    "chrono_outcome_open": "undecided",
    "chrono_outcome_warning": "warning",
    "chrono_outcome_pulled": "replica pulled from the game",
    "chrono_outcome_ban": "ban",
    "chrono_choose": "Decision",
    "chrono_record": "Record",
    "chrono_recorded": "Decision recorded.",
    "chrono_ban_until": "until {when}",
    "chrono_ban_ended": "ended {when}",
    "chrono_advisory": "The \"There was an earlier violation\" mark is only a notice the server works out from this "
                       "field's records (a warning alone never counts). It proves nothing and no "
                       "decision rests on it alone: the organisers decide, looking at the record.",
    "chrono_contest_title": "Anyone who wants to contest",
    "chrono_contest": "There is no appeal process here. Anyone who wants to contest a record talks to the field, "
                      "through the contact given on the field's page, and can use the rights the privacy notice "
                      "describes (access, rectification, erasure) and to object (Art. 21 GDPR). The field's organisers decide and can correct or "
                      "delete the record.",
    "e_chrono_ban_days_invalid": "The length must be from 1 day up to how long the field keeps chrono records.",
}

DE: dict[str, str] = {
    "chrono_warn_fixed": "Eine feste Regel, mit dem juristischen Gutachten bestätigt: Eine bloße Verwarnung zählt nie als früherer Verstoß. Ein Spielverbot dauert 12 Monate, wenn das Spielfeld nichts Kürzeres festlegt, und nie länger, als das Spielfeld Chrono-Aufzeichnungen aufbewahrt.",
    "nav_chrono": "Chrono",
    "chrono_title": "Chrono: Verstöße und Regeln",
    "chrono_intro": "Die Stichproben, die über dem Limit oder der Toleranz lagen, und was die Spielleitung "
                    "entschieden hat. Der Server entscheidet nichts: Er hält fest, was der Controller gemessen hat "
                    "und was die Spielleitung hier wählt.",
    "chrono_rules_title": "Regeln des Spielfelds",
    "chrono_rules_intro": "Die Regel, die die Spielleitung festlegt und die für alle sichtbar ist, die sie "
                          "anwenden.",
    "chrono_ban_days": "Wie lange ein Spielverbot gilt (Tage)",
    "chrono_ban_hint": "Leer: 12 Monate. Länger als die Aufbewahrungszeit der Chrono-Aufzeichnungen geht es nie: Verstoß "
                       "und Verbot werden zusammen gelöscht. Der Server benachrichtigt niemanden: Wer ein Verbot "
                       "festhält, sagt der Person, wann es endet.",
    "chrono_rules_save": "Regeln speichern",
    "chrono_rules_saved": "Regeln gespeichert.",
    "chrono_viol_title": "Verstöße",
    "chrono_viol_none": "Keine Verstöße erfasst.",
    "chrono_col_time": "Wann",
    "chrono_col_player": "Spielende",
    "chrono_col_type": "Art",
    "chrono_col_energy": "Energie (J)",
    "chrono_col_over": "Über dem Limit (J)",
    "chrono_col_flag": "Hinweis",
    "chrono_col_outcome": "Entscheidung",
    "chrono_col_ban": "Verbot",
    "chrono_type_over_limit": "über dem Limit",
    "chrono_type_over_tolerance": "innerhalb der Toleranz (Warnung)",
    "chrono_flag_repeat": "Es gab schon einen früheren Verstoß",
    "chrono_flag_repeat_note": "Ein Hinweis für die Entscheidenden, keine Entscheidung über diese Person.",
    "chrono_outcome_open": "offen",
    "chrono_outcome_warning": "Verwarnung",
    "chrono_outcome_pulled": "Replik aus dem Spiel genommen",
    "chrono_outcome_ban": "Spielverbot",
    "chrono_choose": "Entscheidung",
    "chrono_record": "Festhalten",
    "chrono_recorded": "Entscheidung festgehalten.",
    "chrono_ban_until": "bis {when}",
    "chrono_ban_ended": "endete {when}",
    "chrono_advisory": "Die Markierung „Es gab schon einen früheren Verstoß“ ist nur ein Hinweis, den der Server aus "
                       "den Aufzeichnungen dieses Spielfelds errechnet (eine bloße Verwarnung zählt nie). Sie beweist nichts, und keine Entscheidung stützt sich allein darauf: Die "
                       "Spielleitung entscheidet und sieht sich die Aufzeichnung an.",
    "chrono_contest_title": "Wer widersprechen möchte",
    "chrono_contest": "Hier gibt es kein Einspruchsverfahren. Wer einen Eintrag anfechten möchte, wendet sich an das "
                      "Spielfeld, über den Kontakt auf der Seite des Spielfelds, und kann die Rechte nutzen, die die "
                      "Datenschutzerklärung beschreibt (Auskunft, Berichtigung, Löschung) und Widerspruch (Art. 21 DSGVO). Die Spielleitung des "
                      "Spielfelds entscheidet und kann den Eintrag korrigieren oder löschen.",
    "e_chrono_ban_days_invalid": "Die Dauer muss von 1 Tag bis zur Aufbewahrungszeit der Chrono-Aufzeichnungen des "
                                 "Spielfelds reichen.",
}

ZH_TW: dict[str, str] = {
    "chrono_warn_fixed": "固定規則，已隨法律意見書核可：僅警告絕不算作前次違規。禁賽持續 12 個月，除非場地設定更短，且絕不超過場地保存測速紀錄的期間。",
    "nav_chrono": "測速",
    "chrono_title": "測速：違規與規則",
    "chrono_intro": "抽查時超過上限或容許範圍的紀錄，以及主辦的處理。伺服器不做任何決定，只記錄控制器量到的數值和主辦在這裡的選擇。",
    "chrono_rules_title": "場地規則",
    "chrono_rules_intro": "主辦自訂的規則，使用規則的人都看得到。",
    "chrono_ban_days": "禁賽持續天數",
    "chrono_ban_hint": "留空：12 個月。禁賽不會比場地保存測速紀錄的期間更久，違規紀錄與禁賽會一起刪除。伺服器不會通知任何人：記錄禁賽的人要告訴當事人何時結束。",
    "chrono_rules_save": "儲存規則",
    "chrono_rules_saved": "規則已儲存。",
    "chrono_viol_title": "違規紀錄",
    "chrono_viol_none": "沒有違規紀錄。",
    "chrono_col_time": "時間",
    "chrono_col_player": "玩家",
    "chrono_col_type": "類型",
    "chrono_col_energy": "能量 (J)",
    "chrono_col_over": "超出上限 (J)",
    "chrono_col_flag": "提示",
    "chrono_col_outcome": "處理",
    "chrono_col_ban": "禁賽",
    "chrono_type_over_limit": "超過上限",
    "chrono_type_over_tolerance": "容許範圍內（警告）",
    "chrono_flag_repeat": "先前已有違規紀錄",
    "chrono_flag_repeat_note": "這只是給決定者的提示，不是對這個人的判定。",
    "chrono_outcome_open": "待處理",
    "chrono_outcome_warning": "警告",
    "chrono_outcome_pulled": "槍枝退場",
    "chrono_outcome_ban": "禁賽",
    "chrono_choose": "處理",
    "chrono_record": "記錄",
    "chrono_recorded": "處理已記錄。",
    "chrono_ban_until": "至 {when}",
    "chrono_ban_ended": "已於 {when} 結束",
    "chrono_advisory": "「先前已有違規紀錄」的標記，只是伺服器依這個場地的紀錄算出的提示（僅警告絕不計入）。它不能證明什麼，也沒有任何決定單憑它做出：由主辦查看紀錄後決定。",
    "chrono_contest_title": "想提出異議的人",
    "chrono_contest": "這裡沒有申訴流程。想對某筆紀錄提出異議的人，請透過場地頁面上的聯絡方式與場地聯絡，也可以行使隱私權聲明所列的權利（查閱、更正、刪除）與反對權（GDPR 第 21 條）。由場地主辦決定，並可更正或刪除該筆紀錄。",
    "e_chrono_ban_days_invalid": "天數必須從 1 天起，最長為場地保存測速紀錄的期間。",
}

BY_LANGUAGE: dict[str, dict[str, str]] = {"pt": PT, "en": EN, "de": DE, "zh-tw": ZH_TW}
