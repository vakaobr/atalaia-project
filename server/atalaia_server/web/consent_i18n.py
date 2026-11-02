# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The texts of the privacy notice page (``/privacy``) and of the staff pages' "notice shown again" panel (CONS-*, LEG-*), in
pt-PT, English, German and Traditional Chinese (Taiwan). Not the notice itself: that is the operator's file
(``privacy_notice.py``).

Same rules as ``i18n.py`` and ``staff_i18n.py``: pt-PT inclusive and impersonal, German with "du", Traditional Chinese
(Taiwan) with 你, full-width punctuation after Han and a half-width space between Han and Latin letters or digits.
German and Traditional Chinese were drafted by an AI model (Claude) on 2026-10-28 and are not yet reviewed by a
native-speaking player. ``PUBLIC`` is for the public page, ``STAFF`` is merged into ``staff_i18n.STRINGS``.
"""

from __future__ import annotations

PUBLIC: dict[str, dict[str, str]] = {
    "pt": {
        "privacy_title": "Aviso de privacidade",
        "privacy_version": "Versão {version}",
        "privacy_lang_fallback": "Este aviso não existe em {requested}: mostra-se em {shown}.",
        "privacy_none_title": "Aviso de privacidade não publicado",
        "privacy_none": "Este servidor ainda não publicou um aviso de privacidade. Perguntar à organização do campo.",
        "privacy_footer": "O texto deste aviso é da entidade responsável pelo campo; o servidor Atalaia apenas o mostra.",
    },
    "en": {
        "privacy_title": "Privacy notice",
        "privacy_version": "Version {version}",
        "privacy_lang_fallback": "This notice does not exist in {requested}: it is shown in {shown}.",
        "privacy_none_title": "Privacy notice not published",
        "privacy_none": "This server has not published a privacy notice yet. Ask the field's organisers.",
        "privacy_footer": "The text of this notice is the field operator's; the Atalaia server only shows it.",
    },
    "de": {
        "privacy_title": "Datenschutzhinweis",
        "privacy_version": "Version {version}",
        "privacy_lang_fallback": "Diesen Hinweis gibt es nicht auf {requested}: er wird auf {shown} angezeigt.",
        "privacy_none_title": "Datenschutzhinweis nicht veröffentlicht",
        "privacy_none": "Dieser Server hat noch keinen Datenschutzhinweis veröffentlicht. Frag die Orga des Spielfelds.",
        "privacy_footer": "Der Text dieses Hinweises stammt vom Betreiber des Spielfelds; der Atalaia-Server zeigt ihn "
                          "nur an.",
    },
    "zh-tw": {
        "privacy_title": "隱私權聲明",
        "privacy_version": "版本 {version}",
        "privacy_lang_fallback": "這份聲明沒有 {requested} 版本，改以 {shown} 顯示。",
        "privacy_none_title": "尚未公布隱私權聲明",
        "privacy_none": "這台伺服器還沒有公布隱私權聲明。請詢問場地的主辦單位。",
        "privacy_footer": "這份聲明的內容由場地營運者負責；Atalaia 伺服器只負責顯示。",
    },
}

STAFF: dict[str, dict[str, str]] = {
    "pt": {
        "notice_title": "Aviso de privacidade",
        "notice_intro_outdated": "O aviso de privacidade mudou desde a última versão mostrada a esta conta (versão "
                                 "{old}, agora {version}). Ler o aviso e confirmar que foi visto. A conta continua a "
                                 "funcionar como está.",
        "notice_intro_missing": "Não há registo de que esta conta tenha visto o aviso de privacidade (versão "
                                "{version}). Ler o aviso e confirmar que foi visto.",
        "notice_read": "Ler o aviso de privacidade",
        "notice_no_notice": "O servidor ainda não publicou o texto do aviso: perguntar à organização do campo.",
        "notice_accept": "Li o aviso de privacidade.",
        "notice_button": "Confirmar",
        "notice_tick": "Marcar primeiro que se leu o aviso.",
        "notice_done": "Registado: o aviso foi visto.",
        "e_notice_version_changed": "O aviso mudou entretanto. Recarregar a página e ler a nova versão.",
        "e_privacy_notice_unpublished": "Este servidor ainda não publicou o seu aviso de privacidade, por isso não cria contas novas. Quem já tem conta entra como sempre. Avisar quem gere o servidor.",
    },
    "en": {
        "notice_title": "Privacy notice",
        "notice_intro_outdated": "The privacy notice has changed since the last version shown to this account "
                                 "(version {old}, now {version}). Read the notice and confirm you have seen it. The "
                                 "account keeps working as it is.",
        "notice_intro_missing": "There is no record that this account has seen the privacy notice (version {version}). "
                                "Read the notice and confirm you have seen it.",
        "notice_read": "Read the privacy notice",
        "notice_no_notice": "The server has not published the notice's text yet: ask the field's organisers.",
        "notice_accept": "I have read the privacy notice.",
        "notice_button": "Confirm",
        "notice_tick": "Tick first that you have read the notice.",
        "notice_done": "Recorded: the notice was seen.",
        "e_notice_version_changed": "The notice has changed in the meantime. Reload the page and read the new version.",
        "e_privacy_notice_unpublished": "This server has not published its privacy notice yet, so it is not making new accounts. Existing accounts log in as always. Tell whoever runs the server.",
    },
    "de": {
        "notice_title": "Datenschutzhinweis",
        "notice_intro_outdated": "Der Datenschutzhinweis hat sich seit der letzten Version geändert, die diesem Konto "
                                 "gezeigt wurde (Version {old}, jetzt {version}). Lies den Hinweis und bestätige, "
                                 "dass du ihn gesehen hast. Das Konto funktioniert weiter wie bisher.",
        "notice_intro_missing": "Es ist nicht vermerkt, dass dieses Konto den Datenschutzhinweis (Version {version}) "
                                "gesehen hat. Lies den Hinweis und bestätige, dass du ihn gesehen hast.",
        "notice_read": "Datenschutzhinweis lesen",
        "notice_no_notice": "Der Server hat den Text des Hinweises noch nicht veröffentlicht: Frag die Orga des "
                            "Spielfelds.",
        "notice_accept": "Ich habe den Datenschutzhinweis gelesen.",
        "notice_button": "Bestätigen",
        "notice_tick": "Setze zuerst das Häkchen, dass du den Hinweis gelesen hast.",
        "notice_done": "Vermerkt: Der Hinweis wurde gesehen.",
        "e_notice_version_changed": "Der Hinweis hat sich inzwischen geändert. Lade die Seite neu und lies die neue "
                                    "Version.",
        "e_privacy_notice_unpublished": "Dieser Server hat seine Datenschutzerklärung noch nicht veröffentlicht und legt deshalb keine neuen Konten an. Bestehende Konten melden sich wie gewohnt an. Sag es den Betreibenden des Servers.",
    },
    "zh-tw": {
        "notice_title": "隱私權聲明",
        "notice_intro_outdated": "自從上次向這個帳號顯示的版本之後，隱私權聲明已經更新（版本 {old}，現在是 "
                                 "{version}）。請閱讀聲明並確認你已看過。帳號照常運作。",
        "notice_intro_missing": "沒有紀錄顯示這個帳號看過隱私權聲明（版本 {version}）。請閱讀聲明並確認你已看過。",
        "notice_read": "閱讀隱私權聲明",
        "notice_no_notice": "伺服器還沒有公布聲明的內容：請詢問場地的主辦單位。",
        "notice_accept": "我已閱讀隱私權聲明。",
        "notice_button": "確認",
        "notice_tick": "請先勾選你已閱讀聲明。",
        "notice_done": "已記錄：聲明已看過。",
        "e_notice_version_changed": "聲明在這段時間內已經更新。請重新載入頁面並閱讀新版本。",
        "e_privacy_notice_unpublished": "這台伺服器尚未公布隱私權聲明，因此暫不建立新帳號。已有帳號仍可登入。請通知管理這台伺服器的人。",
    },
}
