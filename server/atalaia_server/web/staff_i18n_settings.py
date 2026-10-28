# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The texts of the staff page for a field's settings (decisions FS-*), merged into ``staff_i18n.STRINGS``.

Same rules as ``staff_i18n.py``: pt-PT inclusive and impersonal, German with "du" and neutral nouns, Traditional Chinese
(Taiwan) with 你, full-width punctuation after Han and a half-width space between Han and Latin letters or digits.
German and Traditional Chinese were drafted by an AI model (Claude) on 2026-10-28 and are not yet reviewed by a
native-speaking player.

Membership texts that name the body ("APD" in Portugal, "association" elsewhere, decision MEM-4) have a ``_m`` twin: the
page's script swaps them with the field's country, and again when the country is changed on the page
(``static/staff/staff.js``, ``membershipWording``). ``MEMBERSHIP_TWINS`` names them.
"""

from __future__ import annotations

# The texts with a ``_m`` twin below (the page's script has the same list in staff.js).
MEMBERSHIP_TWINS = ("fs_member_title", "fs_member_intro", "fs_member_any", "fs_member_only", "fs_member_custom_title",
                    "fs_member_custom_intro")

PT: dict[str, str] = {
    "nav_fsettings": "Definições",
    "fs_title": "Definições do campo",
    "fs_intro": "Tudo o que a administração do campo regula, sem passar pela API: página pública, regras de check-in, "
                "filiação, partilha de cronos, país e conservação de dados. Cada secção guarda-se à parte.",
    "fs_controllers_note": "O que muda nas regras de check-in, na etiqueta de filiação, na filiação, no país e na "
                           "conservação de dados chega logo aos controladores do campo: o servidor envia-lhes o "
                           "aviso field.changed.",
    "fs_saved_controllers": "Guardado. Os controladores recebem a alteração de imediato.",
    "fs_public_title": "Página pública",
    "fs_public_intro": "O que a página pública do campo e os seus feeds mostram. Desligada, o campo não tem página "
                       "pública.",
    "fs_public_page": "Mostrar a página pública e os feeds do campo",
    "fs_description": "Descrição",
    "fs_description_hint": "Texto livre; as quebras de linha mantêm-se. Vazio: sem descrição.",
    "fs_address": "Morada",
    "fs_address_hint": "Uma só linha. Uma morada nova atualiza os jogos publicados que a mostram.",
    "fs_fed_label": "Etiqueta do número de federação",
    "fs_fed_label_hint": "Uma só linha, curta. Vazio: a etiqueta habitual. Chega logo aos controladores.",
    "fs_checkin_title": "Regras de check-in",
    "fs_checkin_intro": "As réplicas que cada pessoa pode declarar e o modelo de limites de que vêm as classes.",
    "fs_limit_template": "Modelo de limites",
    "fs_max_replicas": "Máximo de réplicas por pessoa",
    "fs_member_title": "Filiação numa APD",
    "fs_member_title_m": "Filiação numa associação",
    "fs_member_intro": "Que APD o campo aceita e quando exige filiação. O servidor nunca a verifica: a pessoa "
                       "declara-a e a regra diz o que é preciso.",
    "fs_member_intro_m": "Que associações o campo aceita e quando exige filiação. O servidor nunca a verifica: a "
                         "pessoa declara-a e a regra diz o que é preciso.",
    "fs_member_any": "Qualquer APD",
    "fs_member_any_m": "Qualquer associação",
    "fs_member_only": "Só as APD marcadas",
    "fs_member_only_m": "Só as associações marcadas",
    "fs_member_offered": "Oferecidas para o país {country}, e as próprias do campo",
    "fs_member_no_country": "Sem país definido, só se oferecem as entradas próprias do campo.",
    "fs_member_no_shipped": "A lista do projeto não tem entradas para este país.",
    "fs_member_register": "Exigir filiação válida na inscrição",
    "fs_member_checkin": "Verificar a filiação no check-in",
    "fs_member_expiry": "Exigir e verificar a data de validade",
    "fs_member_custom_title": "APD próprias do campo",
    "fs_member_custom_title_m": "Associações próprias do campo",
    "fs_member_custom_intro": "Entradas só deste campo, que se juntam às da lista do projeto. Alterações só contam "
                              "depois de guardar a filiação.",
    "fs_member_custom_intro_m": "Entradas só deste campo, que se juntam às da lista do projeto. Alterações só contam "
                                "depois de guardar a filiação.",
    "fs_member_custom_none": "Nenhuma entrada própria.",
    "fs_member_custom_id": "Id (começa por x-)",
    "fs_member_custom_name": "Nome",
    "fs_member_custom_short": "Nome curto",
    "fs_member_custom_website": "Sítio web (https://…), opcional",
    "fs_member_custom_add": "Juntar entrada",
    "fs_remove": "Remover",
    "fs_chrono_title": "Partilha de cronos",
    "fs_chrono_intro": "Os campos que a ativam partilham entre si registos de cronometragem, só das pessoas que deram "
                       "o consentimento.",
    "fs_chrono_enabled": "Partilhar registos de cronometragem com outros campos que também partilham",
    "fs_country_title": "País",
    "fs_country_intro": "O país escolhe as palavras da filiação (APD em Portugal, associação nos outros países) e a "
                        "lista oferecida acima.",
    "fs_country": "País (código de duas letras, por exemplo PT)",
    "fs_country_hint": "Vazio: sem país. Ao guardar, as palavras e a lista da filiação mudam logo nesta página.",
    "e_address_text_invalid": "Morada inválida: uma só linha, sem carateres de controlo, até 512 carateres.",
    "e_federation_label_invalid": "Etiqueta inválida: uma só linha, até 16 carateres.",
    "e_limit_template_invalid": "Modelo de limites desconhecido.",
    "e_max_replicas_invalid": "Máximo de réplicas inválido (um número inteiro, de 1 ao máximo do servidor).",
    "e_http_422": "Algum valor tem a forma errada (por exemplo, um texto demasiado longo).",
    "fs_retention_title": "Conservação de dados",
    "fs_retention_intro": "Durante quantos dias os controladores do campo guardam os registos de cronometragem e os "
                          "dados de cada jogo terminado, e este servidor o seu registo de cronometragem.",
    "fs_chrono_days": "Registos de cronometragem: dias guardados",
    "fs_game_days": "Dados dos jogos (eventos, pontuações, nós): dias guardados depois de o jogo terminar",
    "fs_retention_hint": "De 30 a 3653 dias; 365 por defeito. Um controlador ligado a este servidor nunca apaga um "
                         "jogo antes de o servidor o ter recebido por inteiro. O historial de jogos deste servidor "
                         "tem o seu próprio prazo, na página do historial. Chega logo aos controladores.",
    "e_chrono_retention_days_invalid": "Prazo dos registos de cronometragem inválido (um número inteiro de dias, "
                                       "de 30 a 3653).",
    "e_game_retention_days_invalid": "Prazo dos dados dos jogos inválido (um número inteiro de dias, de 30 a 3653).",
}

EN: dict[str, str] = {
    "nav_fsettings": "Settings",
    "fs_title": "Field settings",
    "fs_intro": "Everything the field's admin sets, without the API: public page, check-in rules, membership, chrono "
                "sharing, country and data retention. Each section is saved on its own.",
    "fs_controllers_note": "A change to the check-in rules, the federation label, the membership, the country or "
                           "the data retention reaches the field's controllers at once: the server sends them the "
                           "field.changed note.",
    "fs_saved_controllers": "Saved. The controllers get the change at once.",
    "fs_public_title": "Public page",
    "fs_public_intro": "What the field's public page and its feeds show. Off, the field has no public page.",
    "fs_public_page": "Show the field's public page and feeds",
    "fs_description": "Description",
    "fs_description_hint": "Free text; line breaks are kept. Empty: no description.",
    "fs_address": "Address",
    "fs_address_hint": "One line. A new address updates the published games that show it.",
    "fs_fed_label": "Federation number label",
    "fs_fed_label_hint": "One short line. Empty: the usual label. The controllers get it at once.",
    "fs_checkin_title": "Check-in rules",
    "fs_checkin_intro": "The replicas each person may declare and the limit template their classes come from.",
    "fs_limit_template": "Limit template",
    "fs_max_replicas": "Most replicas per person",
    "fs_member_title": "APD membership",
    "fs_member_title_m": "Association membership",
    "fs_member_intro": "Which APDs the field accepts and when it asks for membership. The server never verifies "
                       "it: the person declares it and the rule says what is needed.",
    "fs_member_intro_m": "Which associations the field accepts and when it asks for membership. The server never "
                         "verifies it: the person declares it and the rule says what is needed.",
    "fs_member_any": "Any APD",
    "fs_member_any_m": "Any association",
    "fs_member_only": "Only the ticked APDs",
    "fs_member_only_m": "Only the ticked associations",
    "fs_member_offered": "Offered for the country {country}, and the field's own",
    "fs_member_no_country": "With no country set, only the field's own entries are offered.",
    "fs_member_no_shipped": "The project's list has no entries for this country.",
    "fs_member_register": "Require valid membership to register",
    "fs_member_checkin": "Check membership at check-in",
    "fs_member_expiry": "Require and check the expiry date",
    "fs_member_custom_title": "The field's own APDs",
    "fs_member_custom_title_m": "The field's own associations",
    "fs_member_custom_intro": "Entries for this field only, added to the project's list. Changes count only after "
                              "the membership is saved.",
    "fs_member_custom_intro_m": "Entries for this field only, added to the project's list. Changes count only after "
                                "the membership is saved.",
    "fs_member_custom_none": "No own entries.",
    "fs_member_custom_id": "Id (starts with x-)",
    "fs_member_custom_name": "Name",
    "fs_member_custom_short": "Short name",
    "fs_member_custom_website": "Website (https://…), optional",
    "fs_member_custom_add": "Add entry",
    "fs_remove": "Remove",
    "fs_chrono_title": "Chrono sharing",
    "fs_chrono_intro": "Fields that turn it on share chrono records with each other, only for the people who "
                       "consented.",
    "fs_chrono_enabled": "Share chrono records with other fields that also share",
    "fs_country_title": "Country",
    "fs_country_intro": "The country picks the membership words (APD in Portugal, association elsewhere) and the "
                        "list offered above.",
    "fs_country": "Country (two-letter code, for example PT)",
    "fs_country_hint": "Empty: no country. On saving, the membership words and list change on this page at once.",
    "e_address_text_invalid": "Invalid address: one line, no control characters, at most 512 characters.",
    "e_federation_label_invalid": "Invalid label: one line, at most 16 characters.",
    "e_limit_template_invalid": "Unknown limit template.",
    "e_max_replicas_invalid": "Invalid most-replicas value (a whole number, from 1 to the server's maximum).",
    "e_http_422": "A value has the wrong form (for example, a text that is too long).",
    "fs_retention_title": "Data retention",
    "fs_retention_intro": "How many days the field's controllers keep chrono records and the data of each ended game, "
                          "and this server its chrono registry.",
    "fs_chrono_days": "Chrono records: days kept",
    "fs_game_days": "Game data (events, scores, nodes): days kept after the game ends",
    "fs_retention_hint": "30 to 3653 days; 365 by default. A controller connected to this server never deletes a game "
                         "before the server has all of it. This server's game history has its own period, on the "
                         "history page. The controllers get the change at once.",
    "e_chrono_retention_days_invalid": "Invalid chrono retention (a whole number of days, from 30 to 3653).",
    "e_game_retention_days_invalid": "Invalid game data retention (a whole number of days, from 30 to 3653).",
}

DE: dict[str, str] = {
    "nav_fsettings": "Einstellungen",
    "fs_title": "Einstellungen des Spielfelds",
    "fs_intro": "Alles, was die Orga des Spielfelds festlegt, ohne die API: öffentliche Seite, Check-in-Regeln, "
                "Mitgliedschaft, Chrono-Freigabe, Land und Datenaufbewahrung. Jeder Abschnitt wird einzeln gespeichert.",
    "fs_controllers_note": "Eine Änderung der Check-in-Regeln, der Verbandsnummer-Bezeichnung, der Mitgliedschaft, "
                           "des Landes oder der Datenaufbewahrung erreicht die Controller des Spielfelds sofort: Der Server "
                           "schickt ihnen den Hinweis field.changed.",
    "fs_saved_controllers": "Gespeichert. Die Controller erhalten die Änderung sofort.",
    "fs_public_title": "Öffentliche Seite",
    "fs_public_intro": "Was die öffentliche Seite des Spielfelds und ihre Feeds zeigen. Ausgeschaltet hat das "
                       "Spielfeld keine öffentliche Seite.",
    "fs_public_page": "Öffentliche Seite und Feeds des Spielfelds zeigen",
    "fs_description": "Beschreibung",
    "fs_description_hint": "Freitext; Zeilenumbrüche bleiben erhalten. Leer: keine Beschreibung.",
    "fs_address": "Adresse",
    "fs_address_hint": "Eine Zeile. Eine neue Adresse aktualisiert die veröffentlichten Spiele, die sie zeigen.",
    "fs_fed_label": "Bezeichnung der Verbandsnummer",
    "fs_fed_label_hint": "Eine kurze Zeile. Leer: die übliche Bezeichnung. Die Controller erhalten sie sofort.",
    "fs_checkin_title": "Check-in-Regeln",
    "fs_checkin_intro": "Die Repliken, die jede Person angeben darf, und die Limit-Vorlage, aus der ihre Klassen "
                        "stammen.",
    "fs_limit_template": "Limit-Vorlage",
    "fs_max_replicas": "Höchstzahl Repliken pro Person",
    "fs_member_title": "APD-Mitgliedschaft",
    "fs_member_title_m": "Verbandsmitgliedschaft",
    "fs_member_intro": "Welche APDs das Spielfeld akzeptiert und wann es eine Mitgliedschaft verlangt. Der Server "
                       "prüft sie nie: Die Person gibt sie an, und die Regel sagt, was nötig ist.",
    "fs_member_intro_m": "Welche Verbände das Spielfeld akzeptiert und wann es eine Mitgliedschaft verlangt. Der "
                         "Server prüft sie nie: Die Person gibt sie an, und die Regel sagt, was nötig ist.",
    "fs_member_any": "Jede APD",
    "fs_member_any_m": "Jeder Verband",
    "fs_member_only": "Nur die angehakten APDs",
    "fs_member_only_m": "Nur die angehakten Verbände",
    "fs_member_offered": "Angeboten für das Land {country} und die eigenen des Spielfelds",
    "fs_member_no_country": "Ohne Land werden nur die eigenen Einträge des Spielfelds angeboten.",
    "fs_member_no_shipped": "Die Liste des Projekts hat keine Einträge für dieses Land.",
    "fs_member_register": "Gültige Mitgliedschaft bei der Anmeldung verlangen",
    "fs_member_checkin": "Mitgliedschaft beim Check-in prüfen",
    "fs_member_expiry": "Ablaufdatum verlangen und prüfen",
    "fs_member_custom_title": "Eigene APDs des Spielfelds",
    "fs_member_custom_title_m": "Eigene Verbände des Spielfelds",
    "fs_member_custom_intro": "Einträge nur für dieses Spielfeld, zusätzlich zur Liste des Projekts. Änderungen "
                              "gelten erst, wenn die Mitgliedschaft gespeichert ist.",
    "fs_member_custom_intro_m": "Einträge nur für dieses Spielfeld, zusätzlich zur Liste des Projekts. Änderungen "
                                "gelten erst, wenn die Mitgliedschaft gespeichert ist.",
    "fs_member_custom_none": "Keine eigenen Einträge.",
    "fs_member_custom_id": "ID (beginnt mit x-)",
    "fs_member_custom_name": "Name",
    "fs_member_custom_short": "Kurzname",
    "fs_member_custom_website": "Website (https://…), optional",
    "fs_member_custom_add": "Eintrag hinzufügen",
    "fs_remove": "Entfernen",
    "fs_chrono_title": "Chrono-Freigabe",
    "fs_chrono_intro": "Spielfelder, die sie einschalten, teilen Chrono-Aufzeichnungen untereinander, nur von den "
                       "Personen, die zugestimmt haben.",
    "fs_chrono_enabled": "Chrono-Aufzeichnungen mit anderen Spielfeldern teilen, die auch teilen",
    "fs_country_title": "Land",
    "fs_country_intro": "Das Land bestimmt die Wörter der Mitgliedschaft (APD in Portugal, Verband anderswo) und die "
                        "oben angebotene Liste.",
    "fs_country": "Land (zweistelliger Code, zum Beispiel PT)",
    "fs_country_hint": "Leer: kein Land. Beim Speichern ändern sich die Wörter und die Liste der Mitgliedschaft auf "
                       "dieser Seite sofort.",
    "e_address_text_invalid": "Ungültige Adresse: eine Zeile, keine Steuerzeichen, höchstens 512 Zeichen.",
    "e_federation_label_invalid": "Ungültige Bezeichnung: eine Zeile, höchstens 16 Zeichen.",
    "e_limit_template_invalid": "Unbekannte Limit-Vorlage.",
    "e_max_replicas_invalid": "Ungültige Höchstzahl Repliken (eine ganze Zahl von 1 bis zum Maximum des Servers).",
    "e_http_422": "Ein Wert hat die falsche Form (zum Beispiel ein zu langer Text).",
    "fs_retention_title": "Aufbewahrung von Daten",
    "fs_retention_intro": "Wie viele Tage die Controller des Spielfelds Chrono-Aufzeichnungen und die Daten jedes "
                          "beendeten Spiels aufbewahren, und dieser Server sein Chrono-Register.",
    "fs_chrono_days": "Chrono-Aufzeichnungen: Tage aufbewahrt",
    "fs_game_days": "Spieldaten (Ereignisse, Punkte, Knoten): Tage aufbewahrt nach dem Spielende",
    "fs_retention_hint": "30 bis 3653 Tage; standardmäßig 365. Ein Controller, der mit diesem Server verbunden ist, "
                         "löscht ein Spiel nie, bevor der Server alles davon hat. Der Spielverlauf dieses Servers "
                         "hat eine eigene Frist, auf der Verlaufsseite. Die Controller erhalten die Änderung sofort.",
    "e_chrono_retention_days_invalid": "Ungültige Aufbewahrung der Chrono-Aufzeichnungen (eine ganze Zahl Tage, von "
                                       "30 bis 3653).",
    "e_game_retention_days_invalid": "Ungültige Aufbewahrung der Spieldaten (eine ganze Zahl Tage, von 30 bis 3653).",
}

ZH_TW: dict[str, str] = {
    "nav_fsettings": "設定",
    "fs_title": "場地設定",
    "fs_intro": "場地管理員要設定的一切，不必經過 API：公開頁面、報到規則、會員資格、計時分享、國家與資料保存。每個區塊各自儲存。",
    "fs_controllers_note": "報到規則、聯盟編號標籤、會員資格、國家或資料保存的變更會立刻送到場地的控制器：伺服器會傳給它們 "
                           "field.changed 通知。",
    "fs_saved_controllers": "已儲存。控制器會立刻收到變更。",
    "fs_public_title": "公開頁面",
    "fs_public_intro": "場地的公開頁面與訂閱源顯示的內容。關閉時，場地沒有公開頁面。",
    "fs_public_page": "顯示場地的公開頁面與訂閱源",
    "fs_description": "說明",
    "fs_description_hint": "自由文字，會保留換行。留空則沒有說明。",
    "fs_address": "地址",
    "fs_address_hint": "限一行。新地址會更新顯示它的已發布遊戲。",
    "fs_fed_label": "聯盟編號的標籤",
    "fs_fed_label_hint": "一行短文字。留空則使用預設標籤。控制器會立刻收到。",
    "fs_checkin_title": "報到規則",
    "fs_checkin_intro": "每個人可申報的複製槍數量，以及其等級所屬的限制範本。",
    "fs_limit_template": "限制範本",
    "fs_max_replicas": "每人複製槍數量上限",
    "fs_member_title": "APD 會員資格",
    "fs_member_title_m": "協會會員資格",
    "fs_member_intro": "場地接受哪些 APD，以及何時要求會員資格。伺服器從不查核：由本人申報，規則決定需要什麼。",
    "fs_member_intro_m": "場地接受哪些協會，以及何時要求會員資格。伺服器從不查核：由本人申報，規則決定需要什麼。",
    "fs_member_any": "任何 APD",
    "fs_member_any_m": "任何協會",
    "fs_member_only": "只接受勾選的 APD",
    "fs_member_only_m": "只接受勾選的協會",
    "fs_member_offered": "提供給國家 {country} 的項目，以及場地自己的",
    "fs_member_no_country": "未設定國家時，只提供場地自己的項目。",
    "fs_member_no_shipped": "專案的清單中沒有這個國家的項目。",
    "fs_member_register": "報名時要求有效的會員資格",
    "fs_member_checkin": "報到時檢查會員資格",
    "fs_member_expiry": "要求並檢查到期日",
    "fs_member_custom_title": "場地自己的 APD",
    "fs_member_custom_title_m": "場地自己的協會",
    "fs_member_custom_intro": "只屬於這個場地的項目，會加進專案的清單。變更要在儲存會員資格後才生效。",
    "fs_member_custom_intro_m": "只屬於這個場地的項目，會加進專案的清單。變更要在儲存會員資格後才生效。",
    "fs_member_custom_none": "沒有自己的項目。",
    "fs_member_custom_id": "ID（以 x- 開頭）",
    "fs_member_custom_name": "名稱",
    "fs_member_custom_short": "簡稱",
    "fs_member_custom_website": "網站（https://…），選填",
    "fs_member_custom_add": "加入項目",
    "fs_remove": "移除",
    "fs_chrono_title": "計時分享",
    "fs_chrono_intro": "開啟的場地之間會互相分享計時紀錄，只限已同意的人。",
    "fs_chrono_enabled": "與其他也分享的場地分享計時紀錄",
    "fs_country_title": "國家",
    "fs_country_intro": "國家決定會員資格的用語（葡萄牙用 APD，其他地方用協會）以及上方提供的清單。",
    "fs_country": "國家（兩個字母的代碼，例如 PT）",
    "fs_country_hint": "留空則沒有國家。儲存後，這個頁面的會員資格用語與清單會立刻改變。",
    "e_address_text_invalid": "地址無效：限一行，不可有控制字元，最多 512 個字元。",
    "e_federation_label_invalid": "標籤無效：限一行，最多 16 個字元。",
    "e_limit_template_invalid": "不明的限制範本。",
    "e_max_replicas_invalid": "複製槍數量上限無效（整數，從 1 到伺服器的上限）。",
    "e_http_422": "某個值的格式不對（例如文字太長）。",
    "fs_retention_title": "資料保存",
    "fs_retention_intro": "場地的控制器保存計時紀錄與每場已結束遊戲資料的天數，以及這台伺服器保存計時登錄資料的天數。",
    "fs_chrono_days": "計時紀錄：保存天數",
    "fs_game_days": "遊戲資料（事件、分數、節點）：遊戲結束後的保存天數",
    "fs_retention_hint": "30 至 3653 天；預設 365。連上這台伺服器的控制器，在伺服器收到完整資料之前絕不會刪除遊戲。"
                         "這台伺服器的遊戲歷史有自己的期限，在歷史頁面。控制器會立刻收到變更。",
    "e_chrono_retention_days_invalid": "計時紀錄的保存天數無效（30 至 3653 的整數）。",
    "e_game_retention_days_invalid": "遊戲資料的保存天數無效（30 至 3653 的整數）。",
}

BY_LANGUAGE: dict[str, dict[str, str]] = {"pt": PT, "en": EN, "de": DE, "zh-tw": ZH_TW}
