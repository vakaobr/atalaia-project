# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The texts of the staff page for the hub link code (``/staff/account/hub-share``; decisions HLC-*), merged into
``staff_i18n.STRINGS``: making a link code at one field of a hosted hub, entering it at another, which fields the
person is linked at, the consent that chrono sharing needs at this field, and unlinking.

Same rules as ``staff_i18n.py``: pt-PT inclusive and impersonal, German with "du", Traditional Chinese (Taiwan) with
你, full-width punctuation after Han and a half-width space between Han and Latin letters or digits. The words follow
the app's screen for the same link (``hub.*`` in ``app/lib/l10n``) and ``docs/translations/glossary.md``. German and
Traditional Chinese were drafted by an AI model (Claude) on 2026-10-31 and are not yet reviewed by a native-speaking
player. The server gives one answer (``invalid_code``) for a code that is wrong, expired or used, on purpose (no
oracle for guessing), so the text names the three together.
"""

from __future__ import annotations

PT: dict[str, str] = {
    "hub_link": "Cronografagem entre campos",
    "hub_link_hint": "Ligar esta conta às contas de outros campos deste servidor, com um código de ligação.",
    "hub_title": "Cronografagem entre campos",
    "hub_intro": "Quem joga em vários campos deste servidor pode ligar as suas contas, para que cada campo veja as "
                 "cronografagens passadas noutro (só de leitura). A ligação faz-se com um código de ligação: gera-se "
                 "num campo e escreve-se noutro. Nada é ligado por nome ou por e-mail.",
    "hub_back": "Voltar à conta",
    "hub_not_hosted": "Este servidor tem um só campo: não há contas de outros campos para ligar.",
    "hub_state_title": "Estado",
    "hub_state_field": "Este campo: {field}.",
    "hub_state_linked": "Esta conta está ligada desde {when}.",
    "hub_state_unlinked": "Esta conta ainda não está ligada às contas de outros campos.",
    "hub_sharing_on": "A partilhar: os outros campos ligados, com a partilha ligada, veem as cronografagens deste campo.",
    "hub_sharing_off": "Ainda não se partilha nada: falta o consentimento neste campo, ou o campo tem a partilha "
                       "desligada ou não aceitou os termos atuais.",
    "hub_consent_title": "Consentimento neste campo",
    "hub_consent_text": "A partilha precisa do consentimento em cada campo e do interruptor do próprio campo. Com o "
                        "consentimento, os registos de cronografagem assinados dos identificadores de jogo que esta "
                        "conta tem neste campo podem ser vistos, só de leitura, pelos outros campos ligados em que "
                        "também há consentimento e a partilha está ligada, e os deles por este campo. Mais nada passa "
                        "de um campo para o outro. O consentimento pode ser retirado em qualquer altura: as cópias "
                        "publicadas saem logo.",
    "hub_consent_other": "O consentimento no outro campo dá-se na página da conta desse campo.",
    "hub_consent_notice": "Ler o aviso de privacidade",
    "hub_consent_tick": "Consinto que os registos de cronografagem assinados que este campo tem de mim possam ser "
                        "vistos pelos outros campos que ligar e em que também consinta, e os deles por este.",
    "hub_consent_give": "Dar o consentimento",
    "hub_consent_given": "Consentimento dado neste campo.",
    "hub_consent_none": "Ainda não há consentimento neste campo.",
    "hub_consent_tick_needed": "Marcar a caixa para dar o consentimento.",
    "hub_consent_saved": "Consentimento registado.",
    "hub_consent_withdraw": "Retirar o consentimento",
    "hub_consent_withdraw_confirm": "Retirar o consentimento neste campo? As cronografagens deste campo saem logo da "
                                    "vista dos outros campos.",
    "hub_consent_withdrawn": "Consentimento retirado.",
    "hub_field_off": "Este campo tem a partilha desligada ou não aceitou os termos atuais: nada é partilhado até "
                     "isso mudar, mesmo com consentimento. Só a organização do campo o muda.",
    "hub_make_title": "Gerar um código",
    "hub_make_text": "Gerar um código aqui e escrevê-lo na conta do outro campo.",
    "hub_make": "Gerar código",
    "hub_code_note": "Vale {minutes} minutos e só pode ser usado uma vez. Não volta a ser mostrado.",
    "hub_code_gone": "O código expirou e foi escondido. Gerar outro.",
    "hub_copy": "Copiar",
    "hub_copied": "Código copiado.",
    "hub_enter_title": "Escrever o código de outro campo",
    "hub_enter_text": "Gerar um código na conta do outro campo e escrevê-lo aqui.",
    "hub_enter_label": "Código do outro campo",
    "hub_enter_hint": "Letras e algarismos; os hífenes e os espaços não contam. Um código gerado neste campo não "
                      "serve aqui.",
    "hub_enter_button": "Ligar",
    "hub_code_needed": "Escrever o código.",
    "hub_linked_ok": "Contas ligadas.",
    "hub_others_title": "Contas ligadas",
    "hub_others_this": "Esta conta, neste campo: {field}",
    "hub_others_none": "Nenhum outro campo ligado.",
    "hub_other_on": "partilha ligada",
    "hub_other_off": "ainda sem partilha",
    "hub_other_since": "desde {when}",
    "hub_unlink_title": "Desligar",
    "hub_unlink_text": "Desligar tira as cronografagens deste campo da vista dos outros campos e apaga os códigos "
                       "ainda por usar. As contas dos outros campos continuam ligadas entre si.",
    "hub_unlink": "Desligar esta conta",
    "hub_unlink_confirm": "Desligar esta conta das contas de outros campos? Os outros campos deixam de ver as "
                          "cronografagens deste campo.",
    "hub_unlinked_ok": "Conta desligada.",
    "hub_e_invalid_code": "O código não é válido: está errado, já expirou ou já foi usado. Um código gerado neste "
                          "campo também não serve aqui. Gerar um novo no outro campo.",
    "hub_e_already_linked": "Esta conta já está ligada a outra pessoa. Desligá-la primeiro.",
    "hub_e_person_already_linked_here": "Essa pessoa já tem uma conta ligada neste campo.",
    "hub_e_not_linked": "Esta conta não está ligada.",
    "hub_e_not_hosted": "Este servidor tem um só campo.",
    "hub_e_field_not_found": "O servidor não encontrou o campo.",
    "hub_e_consent_not_found": "Não havia consentimento a retirar neste campo.",
}

EN: dict[str, str] = {
    "hub_link": "Chrono sharing between fields",
    "hub_link_hint": "Link this account to your accounts at other fields of this server with a link code.",
    "hub_title": "Chrono sharing between fields",
    "hub_intro": "If you play at several fields of this server, you can link your accounts so that each field sees "
                 "the chrono checks you passed at another (read only). The link is made with a link code: you make it "
                 "at one field and enter it at another. Nothing is linked by name or e-mail address.",
    "hub_back": "Back to the account",
    "hub_not_hosted": "This server has a single field: there are no accounts at other fields to link.",
    "hub_state_title": "State",
    "hub_state_field": "This field: {field}.",
    "hub_state_linked": "This account has been linked since {when}.",
    "hub_state_unlinked": "This account is not linked to your accounts at other fields yet.",
    "hub_sharing_on": "Sharing: the other linked fields that have sharing on see this field's chrono checks.",
    "hub_sharing_off": "Nothing is shared yet: your consent at this field is missing, or the field has sharing "
                       "off or has not accepted the current terms.",
    "hub_consent_title": "Consent at this field",
    "hub_consent_text": "Sharing needs your consent at each field and the field's own switch. With your consent, the "
                        "signed chrono records of the player ids this account holds at this field may be seen, read "
                        "only, by the other linked fields where you also consented and sharing is on, and theirs by "
                        "this one. Nothing else crosses from one field to another. You can withdraw the consent at "
                        "any time: the published copies go at once.",
    "hub_consent_other": "Your consent at the other field is given on the account page of that field.",
    "hub_consent_notice": "Read the privacy notice",
    "hub_consent_tick": "I consent that the signed chrono records this field holds of me may be shown to the other "
                        "fields I link and also consent at, and theirs to this one.",
    "hub_consent_give": "Give consent",
    "hub_consent_given": "Consent given at this field.",
    "hub_consent_none": "No consent given at this field yet.",
    "hub_consent_tick_needed": "Tick the box to give consent.",
    "hub_consent_saved": "Consent recorded.",
    "hub_consent_withdraw": "Withdraw consent",
    "hub_consent_withdraw_confirm": "Withdraw your consent at this field? This field's chrono records leave the other "
                                    "fields' view at once.",
    "hub_consent_withdrawn": "Consent withdrawn.",
    "hub_field_off": "This field has sharing off or has not accepted the current terms: nothing is shared until that "
                     "changes, even with your consent. Only the field's organisers can change it.",
    "hub_make_title": "Make a code",
    "hub_make_text": "Make a code here and enter it in your account at the other field.",
    "hub_make": "Make a code",
    "hub_code_note": "Valid for {minutes} minutes and can be used once. It is not shown again.",
    "hub_code_gone": "The code expired and was hidden. Make a new one.",
    "hub_copy": "Copy",
    "hub_copied": "Code copied.",
    "hub_enter_title": "Enter another field's code",
    "hub_enter_text": "Make a code in your account at the other field and enter it here.",
    "hub_enter_label": "Code from the other field",
    "hub_enter_hint": "Letters and digits; dashes and spaces do not matter. A code made at this field does not work "
                      "here.",
    "hub_enter_button": "Link",
    "hub_code_needed": "Enter the code.",
    "hub_linked_ok": "Accounts linked.",
    "hub_others_title": "Linked accounts",
    "hub_others_this": "This account, at this field: {field}",
    "hub_others_none": "No other field linked.",
    "hub_other_on": "sharing on",
    "hub_other_off": "not sharing yet",
    "hub_other_since": "since {when}",
    "hub_unlink_title": "Unlink",
    "hub_unlink_text": "Unlinking takes this field's chrono records out of the other fields' view and deletes codes "
                       "not yet used. Your accounts at the other fields stay linked to each other.",
    "hub_unlink": "Unlink this account",
    "hub_unlink_confirm": "Unlink this account from your accounts at other fields? The other fields no longer see "
                          "this field's chrono records.",
    "hub_unlinked_ok": "Account unlinked.",
    "hub_e_invalid_code": "The code is not valid: it is wrong, has expired or was already used. A code made at this "
                          "field does not work here either. Make a new one at the other field.",
    "hub_e_already_linked": "This account is already linked to another person. Unlink it first.",
    "hub_e_person_already_linked_here": "That person already has an account linked at this field.",
    "hub_e_not_linked": "This account is not linked.",
    "hub_e_not_hosted": "This server has a single field.",
    "hub_e_field_not_found": "The server could not find the field.",
    "hub_e_consent_not_found": "There was no consent to withdraw at this field.",
}

DE: dict[str, str] = {
    "hub_link": "Chrono-Freigabe zwischen Spielfeldern",
    "hub_link_hint": "Verknüpfe dieses Konto mit deinen Konten auf anderen Spielfeldern dieses Servers, mit einem "
                     "Verknüpfungscode.",
    "hub_title": "Chrono-Freigabe zwischen Spielfeldern",
    "hub_intro": "Wenn du auf mehreren Spielfeldern dieses Servers spielst, kannst du deine Konten verknüpfen, damit "
                 "jedes Feld die Chrono-Prüfungen sieht, die du auf einem anderen bestanden hast (nur lesend). Die "
                 "Verknüpfung entsteht mit einem Verknüpfungscode: Du erzeugst ihn auf einem Feld und gibst ihn auf "
                 "einem anderen ein. Nichts wird über Namen oder E-Mail-Adresse verknüpft.",
    "hub_back": "Zurück zum Konto",
    "hub_not_hosted": "Dieser Server hat nur ein Spielfeld: Es gibt keine Konten auf anderen Feldern zu verknüpfen.",
    "hub_state_title": "Stand",
    "hub_state_field": "Dieses Feld: {field}.",
    "hub_state_linked": "Dieses Konto ist seit {when} verknüpft.",
    "hub_state_unlinked": "Dieses Konto ist noch nicht mit deinen Konten auf anderen Feldern verknüpft.",
    "hub_sharing_on": "Freigabe aktiv: Die anderen verknüpften Felder, bei denen die Freigabe an ist, sehen die "
                      "Chrono-Prüfungen dieses Feldes.",
    "hub_sharing_off": "Noch wird nichts geteilt: Deine Zustimmung auf diesem Feld fehlt, oder das Feld hat die "
                       "Freigabe ausgeschaltet oder die aktuellen Bedingungen nicht angenommen.",
    "hub_consent_title": "Zustimmung auf diesem Feld",
    "hub_consent_text": "Die Freigabe braucht deine Zustimmung auf jedem Feld und den Schalter des Feldes selbst. Mit "
                        "deiner Zustimmung dürfen die signierten Chrono-Aufzeichnungen der Spiel-IDs, die dieses "
                        "Konto auf diesem Feld hat, von den anderen verknüpften Feldern gesehen werden (nur lesend), "
                        "auf denen du ebenfalls zugestimmt hast und die Freigabe an ist, und dieses Feld deren Aufzeichnungen sehen darf. "
                        "Sonst geht nichts von einem Feld zum anderen. Du kannst die Zustimmung jederzeit "
                        "widerrufen: Die veröffentlichten Kopien verschwinden sofort.",
    "hub_consent_other": "Deine Zustimmung auf dem anderen Feld gibst du auf der Kontoseite dieses Feldes.",
    "hub_consent_notice": "Datenschutzhinweis lesen",
    "hub_consent_tick": "Ich stimme zu, dass die signierten Chrono-Aufzeichnungen, die dieses Feld von mir hat, den "
                        "anderen Feldern gezeigt werden dürfen, die ich verknüpfe und auf denen ich ebenfalls "
                        "zustimme, und dass dieses Feld deren Aufzeichnungen sehen darf.",
    "hub_consent_give": "Zustimmen",
    "hub_consent_given": "Zustimmung auf diesem Feld gegeben.",
    "hub_consent_none": "Auf diesem Feld gibt es noch keine Zustimmung.",
    "hub_consent_tick_needed": "Setze das Häkchen, um zuzustimmen.",
    "hub_consent_saved": "Zustimmung gespeichert.",
    "hub_consent_withdraw": "Zustimmung widerrufen",
    "hub_consent_withdraw_confirm": "Zustimmung auf diesem Feld widerrufen? Die Chrono-Aufzeichnungen dieses Feldes "
                                    "sind für die anderen Felder sofort nicht mehr sichtbar.",
    "hub_consent_withdrawn": "Zustimmung widerrufen.",
    "hub_field_off": "Dieses Feld hat die Freigabe ausgeschaltet oder die aktuellen Bedingungen nicht angenommen: "
                     "Es wird nichts geteilt, bis sich das ändert, auch mit deiner Zustimmung. Das ändert nur die "
                     "Orga des Feldes.",
    "hub_make_title": "Code erzeugen",
    "hub_make_text": "Erzeuge hier einen Code und gib ihn in deinem Konto auf dem anderen Feld ein.",
    "hub_make": "Code erzeugen",
    "hub_code_note": "Gilt {minutes} Minuten und kann einmal benutzt werden. Er wird nicht noch einmal angezeigt.",
    "hub_code_gone": "Der Code ist abgelaufen und wurde ausgeblendet. Erzeuge einen neuen.",
    "hub_copy": "Kopieren",
    "hub_copied": "Code kopiert.",
    "hub_enter_title": "Code eines anderen Feldes eingeben",
    "hub_enter_text": "Erzeuge einen Code in deinem Konto auf dem anderen Feld und gib ihn hier ein.",
    "hub_enter_label": "Code vom anderen Feld",
    "hub_enter_hint": "Buchstaben und Ziffern; Bindestriche und Leerzeichen zählen nicht. Ein Code, der auf diesem "
                      "Feld erzeugt wurde, gilt hier nicht.",
    "hub_enter_button": "Verknüpfen",
    "hub_code_needed": "Gib den Code ein.",
    "hub_linked_ok": "Konten verknüpft.",
    "hub_others_title": "Verknüpfte Konten",
    "hub_others_this": "Dieses Konto, auf diesem Feld: {field}",
    "hub_others_none": "Kein anderes Feld verknüpft.",
    "hub_other_on": "Freigabe an",
    "hub_other_off": "noch keine Freigabe",
    "hub_other_since": "seit {when}",
    "hub_unlink_title": "Verknüpfung lösen",
    "hub_unlink_text": "Beim Lösen sind die Chrono-Aufzeichnungen dieses Feldes für die anderen Felder nicht mehr "
                       "sichtbar, und noch nicht benutzte Codes werden gelöscht. Deine Konten auf den anderen "
                       "Feldern bleiben untereinander verknüpft.",
    "hub_unlink": "Dieses Konto lösen",
    "hub_unlink_confirm": "Dieses Konto von deinen Konten auf anderen Feldern lösen? Die anderen Felder sehen die "
                          "Chrono-Aufzeichnungen dieses Feldes dann nicht mehr.",
    "hub_unlinked_ok": "Verknüpfung gelöst.",
    "hub_e_invalid_code": "Der Code ist ungültig: falsch, abgelaufen oder schon benutzt. Ein Code, der auf diesem "
                          "Feld erzeugt wurde, gilt hier auch nicht. Erzeuge auf dem anderen Feld einen neuen.",
    "hub_e_already_linked": "Dieses Konto ist schon mit einer anderen Person verknüpft. Löse die Verknüpfung zuerst.",
    "hub_e_person_already_linked_here": "Diese Person hat auf diesem Feld schon ein verknüpftes Konto.",
    "hub_e_not_linked": "Dieses Konto ist nicht verknüpft.",
    "hub_e_not_hosted": "Dieser Server hat nur ein Spielfeld.",
    "hub_e_field_not_found": "Der Server hat das Feld nicht gefunden.",
    "hub_e_consent_not_found": "Auf diesem Feld gab es keine Zustimmung zu widerrufen.",
}

ZH_TW: dict[str, str] = {
    "hub_link": "場地之間的測速分享",
    "hub_link_hint": "用連結代碼，把這個帳號和你在這台伺服器其他場地的帳號連結起來。",
    "hub_title": "場地之間的測速分享",
    "hub_intro": "如果你在這台伺服器的多個場地玩，可以連結你的帳號，讓每個場地看到你在其他場地通過的測速（唯讀）。"
                 "連結要用連結代碼：在一個場地產生，再到另一個場地輸入。不會用名稱或電子郵件自動連結。",
    "hub_back": "回到帳號",
    "hub_not_hosted": "這台伺服器只有一個場地：沒有其他場地的帳號可以連結。",
    "hub_state_title": "狀態",
    "hub_state_field": "這個場地：{field}。",
    "hub_state_linked": "這個帳號已連結，自 {when} 起。",
    "hub_state_unlinked": "這個帳號還沒有和你在其他場地的帳號連結。",
    "hub_sharing_on": "分享中：已開啟分享的其他連結場地，看得到這個場地的測速。",
    "hub_sharing_off": "目前沒有分享任何東西：你在這個場地還沒有同意，或是場地把分享關掉了，或尚未接受目前的條款。",
    "hub_consent_title": "在這個場地的同意",
    "hub_consent_text": "分享需要你在每個場地的同意，以及場地自己的開關。你同意後，這個帳號在這個場地的玩家編號所留下、"
                        "已簽章的測速紀錄，可以讓你也同意、且已開啟分享的其他連結場地唯讀查看，這個場地也能看到它們的。"
                        "除此之外，沒有任何資料會在場地之間流通。你隨時可以撤回同意：已公開的副本會立刻移除。",
    "hub_consent_other": "你在另一個場地的同意，要在那個場地的帳號頁面給。",
    "hub_consent_notice": "閱讀隱私權聲明",
    "hub_consent_tick": "我同意這個場地保存的我的已簽章測速紀錄，可以給我所連結且也同意的其他場地看到，"
                        "也同意這個場地看到它們的。",
    "hub_consent_give": "給予同意",
    "hub_consent_given": "已在這個場地同意。",
    "hub_consent_none": "你在這個場地還沒有同意。",
    "hub_consent_tick_needed": "請勾選方塊以給予同意。",
    "hub_consent_saved": "已記錄同意。",
    "hub_consent_withdraw": "撤回同意",
    "hub_consent_withdraw_confirm": "要撤回你在這個場地的同意嗎？這個場地的測速紀錄會立刻從其他場地的畫面中消失。",
    "hub_consent_withdrawn": "已撤回同意。",
    "hub_field_off": "這個場地把分享關掉了，或尚未接受目前的條款：在改變之前不會分享任何東西，即使你已同意。"
                     "只有場地的主辦單位能改。",
    "hub_make_title": "產生代碼",
    "hub_make_text": "在這裡產生一組代碼，再到你在另一個場地的帳號輸入。",
    "hub_make": "產生代碼",
    "hub_code_note": "{minutes} 分鐘內有效，只能使用一次，不會再次顯示。",
    "hub_code_gone": "代碼已過期並已隱藏。請再產生一組。",
    "hub_copy": "複製",
    "hub_copied": "已複製代碼。",
    "hub_enter_title": "輸入另一個場地的代碼",
    "hub_enter_text": "先在你於另一個場地的帳號產生代碼，再到這裡輸入。",
    "hub_enter_label": "另一個場地的代碼",
    "hub_enter_hint": "字母和數字；連字號和空格不算。在這個場地產生的代碼，在這裡不能用。",
    "hub_enter_button": "連結",
    "hub_code_needed": "請輸入代碼。",
    "hub_linked_ok": "帳號已連結。",
    "hub_others_title": "已連結的帳號",
    "hub_others_this": "這個帳號，在這個場地：{field}",
    "hub_others_none": "沒有連結其他場地。",
    "hub_other_on": "已開啟分享",
    "hub_other_off": "尚未分享",
    "hub_other_since": "自 {when} 起",
    "hub_unlink_title": "取消連結",
    "hub_unlink_text": "取消連結後，其他場地就看不到這個場地的測速紀錄，尚未使用的代碼也會刪除。你在其他場地的帳號彼此仍然連結。",
    "hub_unlink": "取消這個帳號的連結",
    "hub_unlink_confirm": "要取消這個帳號和你其他場地帳號的連結嗎？其他場地將看不到這個場地的測速紀錄。",
    "hub_unlinked_ok": "已取消這個帳號的連結。",
    "hub_e_invalid_code": "代碼無效：打錯了、已過期或已經使用過。在這個場地產生的代碼，在這裡也不能用。請到另一個場地再產生一組。",
    "hub_e_already_linked": "這個帳號已經連結到另一個人。請先取消連結。",
    "hub_e_person_already_linked_here": "這個人在這個場地已經有連結的帳號。",
    "hub_e_not_linked": "這個帳號沒有連結。",
    "hub_e_not_hosted": "這台伺服器只有一個場地。",
    "hub_e_field_not_found": "伺服器找不到這個場地。",
    "hub_e_consent_not_found": "你在這個場地沒有可以撤回的同意。",
}

STAFF: dict[str, dict[str, str]] = {"pt": PT, "en": EN, "de": DE, "zh-tw": ZH_TW}
