# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The texts of the privacy notice page (``/privacy``) and of the staff pages' "consent again" panel (CONS-*), in
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
        "consent_title": "Confirmar o aviso de privacidade",
        "consent_intro_outdated": "O aviso de privacidade mudou desde o último consentimento desta conta (versão "
                                  "{old}, agora {version}). Ler o aviso e confirmar de novo.",
        "consent_intro_missing": "Esta conta não tem consentimento registado para o aviso de privacidade (versão "
                                 "{version}). Ler o aviso e confirmar.",
        "consent_read": "Ler o aviso de privacidade",
        "consent_no_notice": "O servidor ainda não publicou o texto do aviso: perguntar à organização do campo.",
        "consent_accept": "Li o aviso de privacidade e estou de acordo.",
        "consent_button": "Confirmar",
        "consent_tick": "Marcar primeiro que se leu o aviso e se está de acordo.",
        "consent_done": "Consentimento registado.",
        "e_notice_version_changed": "O aviso mudou entretanto. Recarregar a página e ler a nova versão.",
    },
    "en": {
        "consent_title": "Confirm the privacy notice",
        "consent_intro_outdated": "The privacy notice has changed since this account last consented (version {old}, "
                                  "now {version}). Read the notice and confirm again.",
        "consent_intro_missing": "This account has no consent recorded for the privacy notice (version {version}). "
                                 "Read the notice and confirm.",
        "consent_read": "Read the privacy notice",
        "consent_no_notice": "The server has not published the notice's text yet: ask the field's organisers.",
        "consent_accept": "I have read the privacy notice and I agree.",
        "consent_button": "Confirm",
        "consent_tick": "Tick first that you have read the notice and agree.",
        "consent_done": "Consent recorded.",
        "e_notice_version_changed": "The notice has changed in the meantime. Reload the page and read the new version.",
    },
    "de": {
        "consent_title": "Datenschutzhinweis bestätigen",
        "consent_intro_outdated": "Der Datenschutzhinweis hat sich seit der letzten Zustimmung dieses Kontos geändert "
                                  "(Version {old}, jetzt {version}). Lies den Hinweis und bestätige erneut.",
        "consent_intro_missing": "Für dieses Konto ist keine Zustimmung zum Datenschutzhinweis gespeichert (Version "
                                 "{version}). Lies den Hinweis und bestätige.",
        "consent_read": "Datenschutzhinweis lesen",
        "consent_no_notice": "Der Server hat den Text des Hinweises noch nicht veröffentlicht: Frag die Orga des "
                             "Spielfelds.",
        "consent_accept": "Ich habe den Datenschutzhinweis gelesen und stimme zu.",
        "consent_button": "Bestätigen",
        "consent_tick": "Setze zuerst das Häkchen, dass du den Hinweis gelesen hast und zustimmst.",
        "consent_done": "Zustimmung gespeichert.",
        "e_notice_version_changed": "Der Hinweis hat sich inzwischen geändert. Lade die Seite neu und lies die neue "
                                    "Version.",
    },
    "zh-tw": {
        "consent_title": "確認隱私權聲明",
        "consent_intro_outdated": "自從這個帳號上次同意之後，隱私權聲明已經更新（版本 {old}，現在是 {version}）。"
                                  "請閱讀聲明並重新確認。",
        "consent_intro_missing": "這個帳號沒有對隱私權聲明（版本 {version}）留下同意紀錄。請閱讀聲明並確認。",
        "consent_read": "閱讀隱私權聲明",
        "consent_no_notice": "伺服器還沒有公布聲明的內容：請詢問場地的主辦單位。",
        "consent_accept": "我已閱讀隱私權聲明並且同意。",
        "consent_button": "確認",
        "consent_tick": "請先勾選你已閱讀聲明並且同意。",
        "consent_done": "已記錄同意。",
        "e_notice_version_changed": "聲明在這段時間內已經更新。請重新載入頁面並閱讀新版本。",
    },
}
