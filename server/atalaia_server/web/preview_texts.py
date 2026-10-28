# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The preview deployment's texts (decisions PV-*): the banner, the landing page and the feedback form, in
pt-PT, English, German and Traditional Chinese (Taiwan).

German and Traditional Chinese are drafts made by an AI model and **not yet reviewed by a native-speaking
player** (the same status as the project page's, ``docs/translations/status.yaml``); Portuguese is pt-PT,
impersonal and inclusive. The field pages, the scoreboard, the club pages and the staff pages have the same four
languages (P5H-16); the banner on them is in the page's own.
"""

from __future__ import annotations

import html
import re
from typing import Any, Optional
from urllib.parse import quote

LANGUAGES = ("pt", "en", "de", "zh-tw")
DEFAULT = "pt"
LANGUAGE_NAMES = {"pt": "Português", "en": "English", "de": "Deutsch", "zh-tw": "繁體中文"}
# The field, club, scoreboard and staff pages' languages (P5H-16): the same four.
PAGE_LANGUAGES = LANGUAGES
HTML_LANG = {"pt": "pt-PT", "en": "en", "de": "de", "zh-tw": "zh-TW"}

STRINGS: dict[str, dict[str, str]] = {
    "pt": {
        "language": "Idioma",
        "footer": "Servidor de pré-visualização do Atalaia. Os dados são fictícios.",
        "banner_text": "Pré-visualização, não serve para jogos a sério. Os dados são fictícios e são repostos de "
                       "vez em quando. Opiniões são bem-vindas.",
        "banner_link": "Deixar opinião",
        "landing_title": "Atalaia: servidor de pré-visualização",
        "landing_intro": "Esta é a versão inicial do servidor do Atalaia (o servidor opcional de um campo com "
                         "internet), posta aqui para ser vista e criticada antes de ser usada a sério. Há um campo, "
                         "clubes, jogos marcados e um jogo terminado, tudo inventado.",
        "what_title": "O que ver",
        "li_field": "A página pública do campo",
        "li_field_d": "Os próximos jogos, o endereço, o calendário (.ics) e os dados (JSON); cada jogo tem a sua "
                      "página e o modo de fazer a inscrição.",
        "li_scoreboard": "O marcador",
        "li_scoreboard_d": "As pontuações do último jogo, como as veria quem está de fora do campo.",
        "li_club": "A página de um clube",
        "li_club_d": "Nome, brasão, cores e descrição, com o botão para denunciar a página.",
        "li_staff": "As páginas da organização do campo",
        "li_staff_d": "Histórico de jogos, cenários, dispositivos e GM remoto. Precisam de conta com código TOTP: "
                      "quem quiser vê-las pede uma conta de teste a quem enviou o convite.",
        "li_feedback": "Dar a sua opinião",
        "li_feedback_d": "O que está bem, o que é difícil de usar, o que devia mudar. Não é preciso conta.",
        "not_here_title": "O que não está aqui",
        "not_here_text": "A consola do GM, o simulador e o editor de modos correm no computador do campo e no "
                         "browser, não neste servidor; a app para Android também não. O projeto: ",
        "demo_note": "Nomes, locais e pontuações são inventados; qualquer semelhança é coincidência.",
        "fb_title": "A sua opinião",
        "fb_intro": "Diga-nos o que viu: o que está bem, o que foi difícil de perceber ou de usar, o que devia "
                    "mudar. Não é preciso conta nem nome.",
        "fb_kind": "Sobre o quê?",
        "kind_good": "O que está bem",
        "kind_usability": "Utilização: o que foi difícil ou confuso",
        "kind_change": "O que devia mudar",
        "kind_bug": "Algo não funciona",
        "kind_other": "Outra coisa",
        "fb_who": "Como vê o Atalaia? (opcional)",
        "who_none": "Prefiro não dizer",
        "who_player": "Jogo (jogador/a)",
        "who_organiser": "Organizo jogos ou gero um campo",
        "who_staff": "Sou da organização (GM, marshal)",
        "who_other": "Outro",
        "fb_message": "A sua mensagem",
        "fb_message_hint": "Até {max} caracteres. Não escreva palavras-passe nem dados de outras pessoas.",
        "fb_contact": "Como responder (opcional)",
        "fb_contact_hint": "Um email ou outro contacto, só se quiser resposta. É apagado ao fim de {days} dias.",
        "fb_send": "Enviar",
        "fb_done": "Obrigado! A sua opinião foi guardada.",
        "fb_again": "Enviar outra",
        "fb_invalid": "A mensagem não foi enviada: escolha o assunto e escreva uma mensagem (até {max} "
                      "caracteres, sem carateres de controlo).",
        "fb_too_many": "Demasiadas mensagens deste endereço. Tente de novo mais tarde.",
        "fb_expired": "O formulário expirou ou foi aberto há poucos instantes. Envie de novo.",
        "fb_refused": "O pedido foi recusado: o formulário tem de ser enviado a partir desta página.",
        "fb_privacy": "Guardamos só o que escrever aqui, com a página de onde veio e o idioma: nenhum endereço, "
                      "nenhuma conta e nenhum cookie. Quem administra este servidor lê as mensagens.",
        "fb_back": "Voltar",
        "fb_honeypot": "Deixe este campo vazio",
        "fb_chars": "caracteres",
        "li_demo": "Experimente a demonstração ao vivo",
        "li_demo_d": "Um campo simulado joga um jogo atrás do outro: a consola do GM em modo de leitura, o marcador e a "
                     "vista de quem joga. Só se pode ver, não mudar nada.",
        "li_live": "A página do campo da demonstração ao vivo",
        "li_live_d": "Os jogos que o campo simulado joga, enviados para este servidor como faria um campo a sério.",
        "not_here_text_demo": "O simulador e o editor de modos correm no computador do campo e no browser, não neste "
                              "servidor; a app para Android também não. A consola do GM só existe aqui na demonstração "
                              "ao vivo, em modo de leitura. O projeto: ",
    },
    "en": {
        "language": "Language",
        "footer": "The Atalaia preview server. The data is fictional.",
        "banner_text": "Preview, not for real games. The data is fictional and is reset from time to time. "
                       "Feedback welcome.",
        "banner_link": "Leave feedback",
        "landing_title": "Atalaia: preview server",
        "landing_intro": "This is the first version of the Atalaia site server (the optional server for a field "
                         "with internet), put here to be looked at and criticised before anyone relies on it. It "
                         "has one field, clubs, scheduled games and a finished game, all made up.",
        "what_title": "What to look at",
        "li_field": "The field's public page",
        "li_field_d": "Upcoming games, the address, the calendar (.ics) and the data (JSON); every game has its "
                      "own page and how to register.",
        "li_scoreboard": "The scoreboard",
        "li_scoreboard_d": "The last game's scores, as someone outside the field would see them.",
        "li_club": "A club's page",
        "li_club_d": "Name, crest, colours and description, with the button to report the page.",
        "li_staff": "The field staff's pages",
        "li_staff_d": "Game history, scenarios, devices and the remote GM. They need an account with a TOTP "
                      "code: ask whoever invited you for a test account.",
        "li_feedback": "Leave your feedback",
        "li_feedback_d": "What looks good, what is hard to use, what should change. No account needed.",
        "not_here_title": "What is not here",
        "not_here_text": "The GM console, the simulator and the mode editor run on the field's own computer and "
                         "in the browser, not on this server; neither does the Android app. The project: ",
        "demo_note": "Names, places and scores are made up; any resemblance is a coincidence.",
        "fb_title": "Your feedback",
        "fb_intro": "Tell us what you saw: what looks good, what was hard to understand or use, what should "
                    "change. No account and no name needed.",
        "fb_kind": "About what?",
        "kind_good": "What looks good",
        "kind_usability": "Usability: what was hard or confusing",
        "kind_change": "What should change",
        "kind_bug": "Something is broken",
        "kind_other": "Something else",
        "fb_who": "How do you see Atalaia? (optional)",
        "who_none": "I would rather not say",
        "who_player": "I play",
        "who_organiser": "I organise games or run a field",
        "who_staff": "I am field staff (GM, marshal)",
        "who_other": "Other",
        "fb_message": "Your message",
        "fb_message_hint": "Up to {max} characters. Do not write passwords or other people's details.",
        "fb_contact": "How to answer (optional)",
        "fb_contact_hint": "An email or another contact, only if you want an answer. It is erased after {days} days.",
        "fb_send": "Send",
        "fb_done": "Thank you! Your feedback was saved.",
        "fb_again": "Send another",
        "fb_invalid": "The message was not sent: choose what it is about and write a message (up to {max} "
                      "characters, no control characters).",
        "fb_too_many": "Too many messages from this address. Try again later.",
        "fb_expired": "The form expired or was opened a moment ago. Please send it again.",
        "fb_refused": "The request was refused: the form has to be sent from this page.",
        "fb_privacy": "We keep only what you write here, with the page you came from and the language: no "
                      "address, no account and no cookie. This server's administrators read the messages.",
        "fb_back": "Back",
        "fb_honeypot": "Leave this field empty",
        "fb_chars": "characters",
        "li_demo": "Try the live demo",
        "li_demo_d": "A simulated field plays one game after another: the GM console in read-only mode, the "
                     "scoreboard and the player's view. You can look; nothing can be changed.",
        "li_live": "The live demo field's page",
        "li_live_d": "The games the simulated field plays, sent to this server as a real field would.",
        "not_here_text_demo": "The simulator and the mode editor run on the field's own computer and in the browser, "
                              "not on this server; neither does the Android app. The GM console is here only in the "
                              "live demo, read-only. The project: ",
    },
    "de": {
        "language": "Sprache",
        "footer": "Der Atalaia-Vorschauserver. Die Daten sind erfunden.",
        "banner_text": "Vorschau, nicht für echte Spiele. Die Daten sind erfunden und werden von Zeit zu Zeit "
                       "zurückgesetzt. Rückmeldungen sind willkommen.",
        "banner_link": "Rückmeldung geben",
        "landing_title": "Atalaia: Vorschauserver",
        "landing_intro": "Das ist die erste Version des Atalaia-Servers (der optionale Server für ein Gelände "
                         "mit Internet). Er steht hier, damit man ihn ansehen und kritisieren kann, bevor sich "
                         "jemand darauf verlässt. Es gibt ein Gelände, Vereine, geplante Spiele und ein beendetes "
                         "Spiel, alles erfunden.",
        "what_title": "Was man ansehen kann",
        "li_field": "Die öffentliche Seite des Geländes",
        "li_field_d": "Kommende Spiele, die Adresse, der Kalender (.ics) und die Daten (JSON); jedes Spiel hat "
                      "eine eigene Seite und zeigt, wie man sich anmeldet.",
        "li_scoreboard": "Die Anzeigetafel",
        "li_scoreboard_d": "Die Punkte des letzten Spiels, so wie sie jemand außerhalb des Geländes sähe.",
        "li_club": "Die Seite eines Vereins",
        "li_club_d": "Name, Wappen, Farben und Beschreibung, mit dem Knopf zum Melden der Seite.",
        "li_staff": "Die Seiten der Spielleitung",
        "li_staff_d": "Spielverlauf, Szenarien, Geräte und der Fern-GM. Sie brauchen ein Konto mit TOTP-Code: "
                      "Wer sie sehen möchte, fragt bei der einladenden Person nach einem Testkonto.",
        "li_feedback": "Rückmeldung geben",
        "li_feedback_d": "Was gut aussieht, was schwer zu bedienen ist, was sich ändern sollte. Kein Konto nötig.",
        "not_here_title": "Was hier nicht läuft",
        "not_here_text": "Die GM-Konsole, der Simulator und der Modus-Editor laufen auf dem Rechner des Geländes "
                         "und im Browser, nicht auf diesem Server; die Android-App ebenso nicht. Das Projekt: ",
        "demo_note": "Namen, Orte und Punkte sind erfunden; Ähnlichkeiten sind Zufall.",
        "fb_title": "Ihre Rückmeldung",
        "fb_intro": "Sagen Sie uns, was Sie gesehen haben: was gut aussieht, was schwer zu verstehen oder zu "
                    "bedienen war, was sich ändern sollte. Kein Konto und kein Name nötig.",
        "fb_kind": "Worum geht es?",
        "kind_good": "Was gut aussieht",
        "kind_usability": "Bedienung: was war schwierig oder verwirrend",
        "kind_change": "Was sich ändern sollte",
        "kind_bug": "Etwas funktioniert nicht",
        "kind_other": "Etwas anderes",
        "fb_who": "Wie sehen Sie Atalaia? (freiwillig)",
        "who_none": "Möchte ich nicht sagen",
        "who_player": "Ich spiele",
        "who_organiser": "Ich organisiere Spiele oder leite ein Gelände",
        "who_staff": "Ich gehöre zur Spielleitung (GM, Marshal)",
        "who_other": "Sonstiges",
        "fb_message": "Ihre Nachricht",
        "fb_message_hint": "Bis zu {max} Zeichen. Bitte keine Passwörter und keine Daten anderer Personen.",
        "fb_contact": "Wie wir antworten können (freiwillig)",
        "fb_contact_hint": "Eine E-Mail-Adresse oder ein anderer Kontakt, nur wenn Sie eine Antwort möchten. "
                           "Er wird nach {days} Tagen gelöscht.",
        "fb_send": "Senden",
        "fb_done": "Danke! Ihre Rückmeldung wurde gespeichert.",
        "fb_again": "Noch eine senden",
        "fb_invalid": "Die Nachricht wurde nicht gesendet: Wählen Sie, worum es geht, und schreiben Sie eine "
                      "Nachricht (bis zu {max} Zeichen, keine Steuerzeichen).",
        "fb_too_many": "Zu viele Nachrichten von dieser Adresse. Versuchen Sie es später noch einmal.",
        "fb_expired": "Das Formular ist abgelaufen oder wurde gerade erst geöffnet. Bitte senden Sie es noch "
                      "einmal.",
        "fb_refused": "Die Anfrage wurde abgelehnt: Das Formular muss von dieser Seite aus gesendet werden.",
        "fb_privacy": "Wir speichern nur, was Sie hier schreiben, mit der Seite, von der Sie kamen, und der "
                      "Sprache: keine Adresse, kein Konto und kein Cookie. Die Administration dieses Servers "
                      "liest die Nachrichten.",
        "fb_back": "Zurück",
        "fb_honeypot": "Dieses Feld leer lassen",
        "fb_chars": "Zeichen",
        "li_demo": "Live-Demo ausprobieren",
        "li_demo_d": "Ein simuliertes Gelände spielt ein Spiel nach dem anderen: die GM-Konsole nur lesend, die "
                     "Anzeigetafel und die Sicht der Spielenden. Man kann nur zusehen, nichts ändern.",
        "li_live": "Die Seite des Live-Demo-Geländes",
        "li_live_d": "Die Spiele, die das simulierte Gelände spielt, an diesen Server gesendet, wie es ein echtes "
                     "Gelände täte.",
        "not_here_text_demo": "Der Simulator und der Modus-Editor laufen auf dem Rechner des Geländes und im Browser, "
                              "nicht auf diesem Server; die Android-App ebenso nicht. Die GM-Konsole gibt es hier nur "
                              "in der Live-Demo, nur lesend. Das Projekt: ",
    },
    "zh-tw": {
        "language": "語言",
        "footer": "Atalaia 預覽伺服器。資料皆為虛構。",
        "banner_text": "預覽版，請勿用於正式遊戲。資料皆為虛構，並會不定時重設。歡迎提供意見。",
        "banner_link": "留下意見",
        "landing_title": "Atalaia：預覽伺服器",
        "landing_intro": "這是 Atalaia 場地伺服器（有網路的場地可選用的伺服器）的初版，放在這裡供大家先看、先批評，"
                         "再正式使用。這裡有一個場地、幾個社團、已排定的比賽和一場已結束的比賽，全部都是虛構的。",
        "what_title": "可以看什麼",
        "li_field": "場地的公開頁面",
        "li_field_d": "即將舉行的比賽、地址、行事曆（.ics）和資料（JSON）；每場比賽都有自己的頁面和報名方式。",
        "li_scoreboard": "計分板",
        "li_scoreboard_d": "最近一場比賽的分數，就是場外的人會看到的樣子。",
        "li_club": "社團頁面",
        "li_club_d": "名稱、徽章、顏色和簡介，以及檢舉此頁面的按鈕。",
        "li_staff": "場地工作人員的頁面",
        "li_staff_d": "比賽紀錄、情境、裝置和遠端 GM。需要有 TOTP 驗證碼的帳號，想看的人請向邀請您的人索取測試帳號。",
        "li_feedback": "留下您的意見",
        "li_feedback_d": "哪裡不錯、哪裡難用、哪裡該改。不需要帳號。",
        "not_here_title": "這裡沒有的東西",
        "not_here_text": "GM 控制台、模擬器和模式編輯器是在場地自己的電腦和瀏覽器上執行，不在這台伺服器上；"
                         "Android App 也不在。專案網站：",
        "demo_note": "名稱、地點和分數都是虛構的，如有雷同純屬巧合。",
        "fb_title": "您的意見",
        "fb_intro": "請告訴我們您看到了什麼：哪裡不錯、哪裡難懂或難用、哪裡該改。不需要帳號，也不需要姓名。",
        "fb_kind": "是關於什麼？",
        "kind_good": "哪裡不錯",
        "kind_usability": "易用性：哪裡難用或讓人困惑",
        "kind_change": "哪裡該改",
        "kind_bug": "有東西壞了",
        "kind_other": "其他",
        "fb_who": "您是以什麼身分在看 Atalaia？（選填）",
        "who_none": "不想說",
        "who_player": "我是玩家",
        "who_organiser": "我辦比賽或經營場地",
        "who_staff": "我是場地工作人員（GM、裁判）",
        "who_other": "其他",
        "fb_message": "您的訊息",
        "fb_message_hint": "最多 {max} 個字元。請不要寫密碼或他人的個人資料。",
        "fb_contact": "如何回覆您（選填）",
        "fb_contact_hint": "電子郵件或其他聯絡方式，只有您想收到回覆時才需要。{days} 天後會刪除。",
        "fb_send": "送出",
        "fb_done": "謝謝！您的意見已儲存。",
        "fb_again": "再送一則",
        "fb_invalid": "訊息未送出：請選擇主題並寫下訊息（最多 {max} 個字元，不可含控制字元）。",
        "fb_too_many": "此位址送出的訊息太多，請稍後再試。",
        "fb_expired": "表單已過期，或剛剛才開啟。請再送出一次。",
        "fb_refused": "請求被拒絕：表單必須從此頁面送出。",
        "fb_privacy": "我們只儲存您在這裡寫的內容、來源頁面和語言：不記錄位址、不建立帳號、不使用 cookie。"
                      "本伺服器的管理員會閱讀這些訊息。",
        "fb_back": "返回",
        "fb_honeypot": "請讓此欄保持空白",
        "fb_chars": "字元",
        "li_demo": "試用即時示範",
        "li_demo_d": "一個模擬場地會一場接著一場進行遊戲：唯讀的 GM 控制台、計分板和玩家視角。只能觀看，無法更動。",
        "li_live": "即時示範場地的頁面",
        "li_live_d": "模擬場地所進行的遊戲，會像真實場地一樣傳送到這台伺服器。",
        "not_here_text_demo": "模擬器和模式編輯器是在場地自己的電腦和瀏覽器上執行，不在這台伺服器上；Android App 也不在。"
                              "GM 控制台只在即時示範中提供，且為唯讀。專案網站：",
    },
}

_TAGS = {"pt": "pt", "en": "en", "de": "de", "zh": "zh-tw"}


def choose(query: Optional[str], accept_language: Optional[str]) -> tuple[str, bool]:
    """The page's language and whether it was asked for (``?lang=``): ``?lang=pt|en|de|zh-tw``, else the best
    of ``Accept-Language`` (by q-value, then order; every ``zh`` is Traditional, Taiwan's), else pt."""
    if query in LANGUAGES:
        return query, True
    best: tuple[float, int, str] = (0.0, 0, DEFAULT)
    for index, item in enumerate((accept_language or "").split(",")):
        tag, _, params = item.strip().partition(";")
        lang = _TAGS.get(tag.strip().lower().split("-")[0])
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if lang is not None and q > 0 and (q, -index) > (best[0], best[1]):
            best = (q, -index, lang)
    return best[2], False


def page_language(lang: str) -> str:
    """The language of the pages that have only pt-PT and English: what the others are sent to."""
    return lang if lang in PAGE_LANGUAGES else "en"


FROM_PATH = re.compile(r"/(?:[A-Za-z0-9_.\-][A-Za-z0-9/_.\-]{0,125})?")


def banner(request: Any, lang: str) -> str:
    """The "Preview, not for real games" banner as HTML (every text escaped), or "" unless the server is a
    preview (``ATALAIA_PREVIEW=on``). It links to the feedback form, remembering this page."""
    state = getattr(getattr(request, "app", None), "state", None)
    if state is None or not state.settings.preview:
        return ""
    lang = lang if lang in STRINGS else "en"
    t = STRINGS[lang]
    path = request.url.path
    came_from = f"&from={quote(path, safe='/')}" if FROM_PATH.fullmatch(path) and path != "/feedback" else ""
    href = html.escape(f"/feedback?lang={lang}{came_from}", quote=True)
    return (f'<div class="preview-banner" role="note"><strong>{html.escape(t["banner_text"])}</strong> '
            f'<a href="{href}">{html.escape(t["banner_link"])}</a></div>\n')


def inject_banner(request: Any, body: str, lang: str) -> str:
    """``body`` (a whole page) with the banner right after its ``<body>`` tag; unchanged for a normal server."""
    text = banner(request, lang)
    if not text:
        return body
    return re.sub(r"(<body[^>]*>\n?)", lambda m: m.group(1) + text, body, count=1)
