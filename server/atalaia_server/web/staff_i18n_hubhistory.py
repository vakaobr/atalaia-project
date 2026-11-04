# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The texts of the staff page for the game history shared between the fields of a hosted hub
(``/staff/fields/<field>/hub-history``; decisions HUBH-*), merged into ``staff_i18n.STRINGS``: the field's opt-in
switch (off by default), what is shared and what never is, and the games of the other fields that share.

Same rules as ``staff_i18n.py``: pt-PT inclusive and impersonal, German with "du", Traditional Chinese (Taiwan) with
你, full-width punctuation after Han and a half-width space between Han and Latin letters or digits. German and
Traditional Chinese were drafted by an AI model (Claude) on 2026-11-04 and are not yet reviewed by a native-speaking
player.
"""

from __future__ import annotations

PT: dict[str, str] = {
    "nav_hubhistory": "Jogos entre campos",
    "hh_title": "Histórico de jogos entre campos",
    "hh_not_hosted": "Este servidor tem um só campo: não há outros campos com quem partilhar jogos.",
    "hh_intro": "Os campos deste servidor podem partilhar o seu histórico de jogos uns com os outros. É uma escolha de "
                "cada campo, desligada por omissão. Um campo só vê os jogos dos outros se partilhar os seus.",
    "hh_switch_title": "A partilha deste campo",
    "hh_state_on": "Este campo partilha o seu histórico de jogos desde {since}: {n} jogos partilhados.",
    "hh_state_on_one": "Este campo partilha o seu histórico de jogos desde {since}: {n} jogo partilhado.",
    "hh_state_off": "Este campo não partilha o seu histórico de jogos.",
    "hh_what": "O que é partilhado:",
    "hh_what_yes": "De cada jogo terminado: o modo, a data e a hora de início e de fim, a pontuação final de cada "
                   "equipa, a equipa que venceu e o nome do campo.",
    "hh_what_no": "Nunca: quem jogou (identificadores de jogo, nomes, contas), os eventos do jogo, as listas de "
                  "membros, os squads, nem os nomes escritos pelo campo para o jogo ou para as equipas.",
    "hh_what_keep": "Um jogo partilhado sai da partilha quando o campo deixa de o guardar: no máximo 365 dias depois de "
                    "terminar.",
    "hh_what_off": "Desligar a partilha retira logo todos os jogos que este campo partilhou, e o campo deixa de ver "
                   "os jogos dos outros.",
    "hh_enabled": "Partilhar o histórico de jogos deste campo com os outros campos deste servidor que também "
                  "partilham",
    "hh_save": "Guardar",
    "hh_admin_only": "Só a administração do campo liga ou desliga a partilha.",
    "hh_unchanged": "Nada mudou.",
    "hh_off_confirm": "Desligar a partilha? Todos os jogos que este campo partilhou são retirados já, e o campo deixa "
                      "de ver os jogos dos outros campos.",
    "hh_saved_on": "Partilha ligada: os jogos terminados deste campo estão partilhados.",
    "hh_saved_off": "Partilha desligada: os jogos deste campo foram retirados.",
    "hh_list_title": "Jogos partilhados",
    "hh_reciprocity": "Só os campos que partilham os seus jogos veem os dos outros. Com a partilha deste campo "
                      "desligada, não se mostra nada aqui.",
    "hh_fields_intro": "Campos que partilham:",
    "hh_field_own": "{field} (este campo)",
    "hh_field_line": "desde {since}, {n} jogos",
    "hh_field_line_one": "desde {since}, {n} jogo",
    "hh_empty": "Ainda não há jogos partilhados.",
    "hh_col_field": "Campo",
    "hh_col_ended": "Fim",
    "hh_own": "(este campo)",
    "hh_no_winner": "empate",
    "hh_more": "Mais jogos",
    "hh_e_history_sharing_off": "Este campo não partilha os seus jogos, por isso não vê os dos outros.",
    "hh_e_not_hosted": "Este servidor tem um só campo.",
    "hh_e_field_not_found": "O servidor não encontra este campo.",
}

EN: dict[str, str] = {
    "nav_hubhistory": "Games across fields",
    "hh_title": "Game history across fields",
    "hh_not_hosted": "This server has a single field: there are no other fields to share games with.",
    "hh_intro": "The fields of this server can share their game history with each other. Each field chooses; it is "
                "off by default. A field sees the other fields' games only if it shares its own.",
    "hh_switch_title": "This field's sharing",
    "hh_state_on": "This field has shared its game history since {since}: {n} games shared.",
    "hh_state_on_one": "This field has shared its game history since {since}: {n} game shared.",
    "hh_state_off": "This field does not share its game history.",
    "hh_what": "What is shared:",
    "hh_what_yes": "For each ended game: the mode, the date and time it started and ended, each team's final score, "
                   "the team that won and the field's name.",
    "hh_what_no": "Never: who played (player ids, names, accounts), the game's events, member lists, squads, or the "
                  "names the field typed for the game or its teams.",
    "hh_what_keep": "A shared game leaves the sharing when the field no longer keeps it: at most 365 days after it "
                    "ended.",
    "hh_what_off": "Turning sharing off withdraws every game this field shared at once, and the field no longer sees "
                   "the others' games.",
    "hh_enabled": "Share this field's game history with the other fields of this server that share theirs",
    "hh_save": "Save",
    "hh_admin_only": "Only the field's admin turns sharing on or off.",
    "hh_unchanged": "Nothing changed.",
    "hh_off_confirm": "Turn sharing off? Every game this field shared is withdrawn now, and the field no longer sees "
                      "the other fields' games.",
    "hh_saved_on": "Sharing on: this field's ended games are shared.",
    "hh_saved_off": "Sharing off: this field's games were withdrawn.",
    "hh_list_title": "Shared games",
    "hh_reciprocity": "Only fields that share their games see the others'. With this field's sharing off, nothing is "
                      "shown here.",
    "hh_fields_intro": "Fields that share:",
    "hh_field_own": "{field} (this field)",
    "hh_field_line": "since {since}, {n} games",
    "hh_field_line_one": "since {since}, {n} game",
    "hh_empty": "No shared games yet.",
    "hh_col_field": "Field",
    "hh_col_ended": "Ended",
    "hh_own": "(this field)",
    "hh_no_winner": "draw",
    "hh_more": "More games",
    "hh_e_history_sharing_off": "This field does not share its games, so it does not see the others'.",
    "hh_e_not_hosted": "This server has a single field.",
    "hh_e_field_not_found": "The server cannot find this field.",
}

DE: dict[str, str] = {
    "nav_hubhistory": "Spiele aller Spielfelder",
    "hh_title": "Spielverlauf zwischen Spielfeldern",
    "hh_not_hosted": "Dieser Server hat nur ein Spielfeld: Es gibt keine anderen Spielfelder, mit denen Spiele geteilt "
                     "werden könnten.",
    "hh_intro": "Die Spielfelder dieses Servers können ihren Spielverlauf miteinander teilen. Jedes Spielfeld "
                "entscheidet selbst; standardmäßig ist es aus. Ein Spielfeld sieht die Spiele der anderen nur, wenn "
                "es seine eigenen teilt.",
    "hh_switch_title": "Freigabe dieses Spielfelds",
    "hh_state_on": "Dieses Spielfeld teilt seinen Spielverlauf seit {since}: {n} Spiele geteilt.",
    "hh_state_on_one": "Dieses Spielfeld teilt seinen Spielverlauf seit {since}: {n} Spiel geteilt.",
    "hh_state_off": "Dieses Spielfeld teilt seinen Spielverlauf nicht.",
    "hh_what": "Was geteilt wird:",
    "hh_what_yes": "Für jedes beendete Spiel: der Modus, Datum und Uhrzeit von Beginn und Ende, der Endstand jedes "
                   "Teams, das Siegerteam und der Name des Spielfelds.",
    "hh_what_no": "Nie: wer gespielt hat (Spieler-IDs, Namen, Konten), die Ereignisse des Spiels, Mitgliederlisten, "
                  "Squads oder die Namen, die das Spielfeld für das Spiel oder seine Teams eingegeben hat.",
    "hh_what_keep": "Ein geteiltes Spiel verschwindet aus der Freigabe, sobald das Spielfeld es nicht mehr aufbewahrt: "
                    "spätestens 365 Tage nach seinem Ende.",
    "hh_what_off": "Schaltest du die Freigabe aus, werden alle Spiele, die dieses Spielfeld geteilt hat, sofort "
                   "zurückgezogen, und das Spielfeld sieht die Spiele der anderen nicht mehr.",
    "hh_enabled": "Den Spielverlauf dieses Spielfelds mit den anderen Spielfeldern dieses Servers teilen, die ihren "
                  "teilen",
    "hh_save": "Speichern",
    "hh_admin_only": "Nur die Administration des Spielfelds schaltet die Freigabe ein oder aus.",
    "hh_unchanged": "Nichts geändert.",
    "hh_off_confirm": "Freigabe ausschalten? Alle Spiele, die dieses Spielfeld geteilt hat, werden sofort "
                      "zurückgezogen, und das Spielfeld sieht die Spiele der anderen Spielfelder nicht mehr.",
    "hh_saved_on": "Freigabe an: Die beendeten Spiele dieses Spielfelds sind geteilt.",
    "hh_saved_off": "Freigabe aus: Die Spiele dieses Spielfelds wurden zurückgezogen.",
    "hh_list_title": "Geteilte Spiele",
    "hh_reciprocity": "Nur Spielfelder, die ihre Spiele teilen, sehen die der anderen. Solange die Freigabe dieses "
                      "Spielfelds aus ist, wird hier nichts angezeigt.",
    "hh_fields_intro": "Spielfelder, die teilen:",
    "hh_field_own": "{field} (dieses Spielfeld)",
    "hh_field_line": "seit {since}, {n} Spiele",
    "hh_field_line_one": "seit {since}, {n} Spiel",
    "hh_empty": "Noch keine geteilten Spiele.",
    "hh_col_field": "Spielfeld",
    "hh_col_ended": "Ende",
    "hh_own": "(dieses Spielfeld)",
    "hh_no_winner": "unentschieden",
    "hh_more": "Weitere Spiele",
    "hh_e_history_sharing_off": "Dieses Spielfeld teilt seine Spiele nicht und sieht deshalb die der anderen nicht.",
    "hh_e_not_hosted": "Dieser Server hat nur ein Spielfeld.",
    "hh_e_field_not_found": "Der Server findet dieses Spielfeld nicht.",
}

ZH_TW: dict[str, str] = {
    "nav_hubhistory": "跨場地的遊戲",
    "hh_title": "跨場地的遊戲紀錄",
    "hh_not_hosted": "這台伺服器只有一個場地：沒有其他場地可以分享遊戲。",
    "hh_intro": "這台伺服器上的場地可以互相分享遊戲紀錄。由各場地自行選擇，預設為關閉。場地必須分享自己的遊戲，才能看到其他場地的遊戲。",
    "hh_switch_title": "這個場地的分享",
    "hh_state_on": "這個場地自 {since} 起分享遊戲紀錄：已分享 {n} 場遊戲。",
    "hh_state_off": "這個場地沒有分享遊戲紀錄。",
    "hh_what": "分享的內容：",
    "hh_what_yes": "每場已結束的遊戲：模式、開始與結束的日期和時間、各隊伍的最終分數、獲勝的隊伍，以及場地名稱。",
    "hh_what_no": "絕不分享：誰參加了遊戲（玩家 ID、姓名、帳號）、遊戲事件、成員名單、小隊，以及場地為遊戲或隊伍輸入的名稱。",
    "hh_what_keep": "場地不再保存某場遊戲時，該遊戲就會從分享中移除：最晚在遊戲結束後 365 天。",
    "hh_what_off": "關閉分享後，這個場地分享過的所有遊戲會立即撤回，場地也不再看到其他場地的遊戲。",
    "hh_enabled": "與這台伺服器上同樣分享遊戲紀錄的其他場地，分享這個場地的遊戲紀錄",
    "hh_save": "儲存",
    "hh_admin_only": "只有場地的管理者可以開啟或關閉分享。",
    "hh_unchanged": "沒有變更。",
    "hh_off_confirm": "要關閉分享嗎？這個場地分享過的所有遊戲會立即撤回，場地也不再看到其他場地的遊戲。",
    "hh_saved_on": "已開啟分享：這個場地已結束的遊戲已分享。",
    "hh_saved_off": "已關閉分享：這個場地的遊戲已撤回。",
    "hh_list_title": "分享的遊戲",
    "hh_reciprocity": "只有分享自己遊戲的場地，才能看到其他場地的遊戲。這個場地的分享關閉時，這裡不會顯示任何內容。",
    "hh_fields_intro": "正在分享的場地：",
    "hh_field_own": "{field}（這個場地）",
    "hh_field_line": "自 {since} 起，{n} 場遊戲",
    "hh_empty": "還沒有分享的遊戲。",
    "hh_col_field": "場地",
    "hh_col_ended": "結束",
    "hh_own": "（這個場地）",
    "hh_no_winner": "平手",
    "hh_more": "更多遊戲",
    "hh_e_history_sharing_off": "這個場地沒有分享自己的遊戲，所以看不到其他場地的遊戲。",
    "hh_e_not_hosted": "這台伺服器只有一個場地。",
    "hh_e_field_not_found": "伺服器找不到這個場地。",
}

STAFF: dict[str, dict[str, str]] = {"pt": PT, "en": EN, "de": DE, "zh-tw": ZH_TW}
