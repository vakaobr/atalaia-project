# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field pages' texts in pt-PT, English, German and Traditional Chinese (Taiwan), the language choice
and dates in the field's zone.

Portuguese is pt-PT, inclusive and impersonal (the project's rule: "marshal" with one L,
"squad" untranslated, team = "equipa"); dates are written out by hand (no locale database in
the image), lower-case months and weekdays as pt-PT writes them.

German (``de``) and Traditional Chinese as written in Taiwan (``zh-tw``; the pages say ``zh-Hant-TW``)
were drafted by an AI model (Claude) on 2026-10-23 and are not yet reviewed by a native-speaking player
(``docs/translations/status.yaml``); their words are those of ``docs/translations/glossary.md``. German
says "du" and names people neutrally (Spielende, Orga, Spielleitung); zh-tw says 你, writes full-width
punctuation after Han and a half-width space between Han and Latin letters or digits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

LANGUAGES = ("pt", "en", "de", "zh-tw")
DEFAULT = "pt"

STRINGS: dict[str, dict[str, str]] = {
    "pt": {
        "upcoming": "Próximos jogos",
        "no_games": "Ainda não há jogos marcados.",
        "cancelled": "Cancelado",
        "cancelled_notice": "Este jogo foi cancelado.",
        "reason": "Motivo",
        "when": "Quando",
        "where": "Onde",
        "mode": "Modo",
        "mode_later": "a anunciar",
        "teams": "Equipas",
        "places": "Lugares",
        "places_open": "sem limite",
        "registration": "Inscrições",
        "reg_not_yet": "abrem a {opens}",
        "reg_open": "abertas até {closes}",
        "reg_closed": "fechadas",
        "federation": "Número de federado",
        "fed_required": "obrigatório",
        "fed_optional": "opcional",
        "apd": "Filiação numa APD",
        "apd_register": "exigido na inscrição",
        "apd_checkin": "cartão verificado na receção",
        "apd_expiry": "com validade em dia",
        "apd_any": "qualquer APD",
        "apd_only": "aceites: {names}",
        "apd_m": "Filiação numa associação",  # a field outside Portugal (decision MEM-4)
        "apd_any_m": "qualquer associação",
        "local_time": "hora local, {zone}",
        "calendar": "Calendário",
        "feeds_text": "Os jogos deste campo para calendários e outros sites:",
        "feed_ics": "iCalendar (.ics)",
        "feed_json": "dados (JSON)",
        "add_to_calendar": "Adicionar ao calendário (.ics)",
        "back": "Todos os jogos de {field}",
        "not_found_title": "Página não encontrada",
        "not_found": "Esta página não existe ou não é pública.",
        "language": "Idioma",
        "footer": "Página pública do campo, feita pelo servidor Atalaia. Não mostra quem se inscreveu.",
        "past": "Já terminou.",
        "full": "esgotados",
        "register": "Fazer a inscrição",
        "register_title": "Inscrição: {game}",
        "back_game": "Voltar a {game}",
        "reg_intro": "A inscrição faz-se com uma conta neste site, na app Atalaia.",
        "reg_step_account": "É preciso uma conta neste site. A app e esta página ainda não a criam: pedir à "
                            "organização do campo ou a quem administra o site. Quem já tem conta entra com ela.",
        "reg_step_app": "Na app Atalaia, abrir este jogo com o botão abaixo (ou colar o endereço desta página em "
                        "Participante › Inscrições online), entrar com a conta e fazer a inscrição, com as réplicas "
                        "que vão ser usadas, se o jogo as pedir.",
        "reg_open_app": "Abrir na app Atalaia",
        "reg_address": "Endereço desta página, para colar na app:",
        "reg_step_ticket": "A app guarda o bilhete de check-in e usa-o no dia, no campo. Sem a app, o bilhete "
                           "pode ser impresso e mostrado a um marshal.",
        "reg_data": "O campo recebe o nome escolhido para o jogo, a preferência de equipa, o número de federado "
                    "(se o jogo o pedir) e as réplicas declaradas, e apaga-os 30 dias depois do jogo.",
        "reg_unavailable": "As inscrições para este jogo não estão abertas, ou já não há lugares.",
        # Club pages (plan phase 18)
        "club_footer": "Página pública do clube, feita pelo servidor Atalaia.",
        "club_logo": "Logótipo de {club}",
        "club_crest": "Emblema de {club}",
        "club_fields": "Joga nos campos",
        "report": "Denunciar esta página",
        "report_title": "Denunciar: {club}",
        "report_intro": "Se esta página usa imagens ou nomes sem autorização, é ofensiva ou se faz passar por outra "
                        "pessoa ou clube, avise a administração deste servidor, que pode escondê-la.",
        "report_reason": "Motivo",
        "reason_rights": "Imagens ou nomes usados sem autorização",
        "reason_offensive": "Conteúdo ofensivo",
        "reason_impersonation": "Faz-se passar por outra pessoa ou clube",
        "reason_other": "Outro motivo",
        "report_text": "Detalhes (opcional, até 1000 caracteres)",
        "report_send": "Enviar a denúncia",
        "report_privacy": "O endereço de quem denuncia não é guardado.",
        "report_done": "A denúncia foi enviada à administração do servidor. Agradecemos o aviso.",
        "report_invalid": "A denúncia não foi aceite: escolha um motivo e escreva até 1000 caracteres.",
        "report_too_many": "Demasiadas denúncias a partir deste endereço. Tente mais tarde.",
        "back_club": "Voltar a {club}",
    },
    "en": {
        "upcoming": "Upcoming games",
        "no_games": "No games scheduled yet.",
        "cancelled": "Cancelled",
        "cancelled_notice": "This game has been cancelled.",
        "reason": "Reason",
        "when": "When",
        "where": "Where",
        "mode": "Mode",
        "mode_later": "to be announced",
        "teams": "Teams",
        "places": "Places",
        "places_open": "no limit",
        "registration": "Registration",
        "reg_not_yet": "opens {opens}",
        "reg_open": "open until {closes}",
        "reg_closed": "closed",
        "federation": "Federation number",
        "fed_required": "required",
        "fed_optional": "optional",
        "apd": "APD membership",
        "apd_register": "required to register",
        "apd_checkin": "card checked at check-in",
        "apd_expiry": "must be unexpired",
        "apd_any": "any APD",
        "apd_only": "accepted: {names}",
        "apd_m": "Association membership",  # a field outside Portugal (decision MEM-4)
        "apd_any_m": "any association",
        "local_time": "local time, {zone}",
        "calendar": "Calendar",
        "feeds_text": "This field's games for calendars and other sites:",
        "feed_ics": "iCalendar (.ics)",
        "feed_json": "data (JSON)",
        "add_to_calendar": "Add to calendar (.ics)",
        "back": "All games at {field}",
        "not_found_title": "Page not found",
        "not_found": "This page does not exist or is not public.",
        "language": "Language",
        "footer": "The field's public page, made by the Atalaia server. It never shows who registered.",
        "past": "It has ended.",
        "full": "full",
        "register": "Register",
        "register_title": "Register: {game}",
        "back_game": "Back to {game}",
        "reg_intro": "You register with an account on this site, in the Atalaia app.",
        "reg_step_account": "You need an account on this site. The app and this page cannot make one yet: ask the "
                            "field's organisers or the site's administrator. If you already have one, log in with it.",
        "reg_step_app": "In the Atalaia app, open this game with the button below (or paste this page's address in "
                        "Player › Online registration), log in with your account and register, with the replicas you "
                        "will use, if the game asks for them.",
        "reg_open_app": "Open in the Atalaia app",
        "reg_address": "This page's address, to paste in the app:",
        "reg_step_ticket": "The app keeps the check-in ticket and uses it on the day, at the field. Without the app, "
                           "print the ticket and show it to a marshal.",
        "reg_data": "The field gets the name you choose for the game, your team preference, your federation number "
                    "(if the game asks for one) and the declared replicas, and erases them 30 days after the game.",
        "reg_unavailable": "Registration for this game is not open, or there are no places left.",
        # Club pages (plan phase 18)
        "club_footer": "The club's public page, made by the Atalaia server.",
        "club_logo": "{club}'s logo",
        "club_crest": "{club}'s crest",
        "club_fields": "Plays at these fields",
        "report": "Report this page",
        "report_title": "Report: {club}",
        "report_intro": "If this page uses images or names without permission, is offensive or impersonates another "
                        "person or club, tell this server's administrators, who can hide it.",
        "report_reason": "Reason",
        "reason_rights": "Images or names used without permission",
        "reason_offensive": "Offensive content",
        "reason_impersonation": "Impersonates another person or club",
        "reason_other": "Another reason",
        "report_text": "Details (optional, up to 1000 characters)",
        "report_send": "Send the report",
        "report_privacy": "The reporter's address is not kept.",
        "report_done": "The report went to the server's administrators. Thank you for telling us.",
        "report_invalid": "The report was not accepted: choose a reason and write up to 1000 characters.",
        "report_too_many": "Too many reports from this address. Try again later.",
        "back_club": "Back to {club}",
    },
    "de": {
        "upcoming": "Nächste Spiele",
        "no_games": "Noch keine Spiele geplant.",
        "cancelled": "Abgesagt",
        "cancelled_notice": "Dieses Spiel wurde abgesagt.",
        "reason": "Grund",
        "when": "Wann",
        "where": "Wo",
        "mode": "Modus",
        "mode_later": "wird noch bekannt gegeben",
        "teams": "Teams",
        "places": "Plätze",
        "places_open": "unbegrenzt",
        "registration": "Anmeldung",
        "reg_not_yet": "öffnet am {opens}",
        "reg_open": "offen bis {closes}",
        "reg_closed": "geschlossen",
        "federation": "Verbandsnummer",
        "fed_required": "erforderlich",
        "fed_optional": "optional",
        "apd": "APD-Mitgliedschaft",
        "apd_register": "bei der Anmeldung erforderlich",
        "apd_checkin": "Ausweis wird beim Check-in geprüft",
        "apd_expiry": "muss gültig sein",
        "apd_any": "jede APD",
        "apd_only": "akzeptiert: {names}",
        "apd_m": "Verbandsmitgliedschaft",  # a field outside Portugal (decision MEM-4)
        "apd_any_m": "jeder Verband",
        "local_time": "Ortszeit, {zone}",
        "calendar": "Kalender",
        "feeds_text": "Die Spiele dieses Spielfelds für Kalender und andere Websites:",
        "feed_ics": "iCalendar (.ics)",
        "feed_json": "Daten (JSON)",
        "add_to_calendar": "Zum Kalender hinzufügen (.ics)",
        "back": "Alle Spiele auf {field}",
        "not_found_title": "Seite nicht gefunden",
        "not_found": "Diese Seite gibt es nicht, oder sie ist nicht öffentlich.",
        "language": "Sprache",
        "footer": "Die öffentliche Seite des Spielfelds, erstellt vom Atalaia-Server. Sie zeigt nie, wer sich "
                  "angemeldet hat.",
        "past": "Schon vorbei.",
        "full": "ausgebucht",
        "register": "Anmelden",
        "register_title": "Anmeldung: {game}",
        "back_game": "Zurück zu {game}",
        "reg_intro": "Du meldest dich mit einem Konto auf dieser Website an, in der Atalaia-App.",
        "reg_step_account": "Du brauchst ein Konto auf dieser Website. Die App und diese Seite können noch keins "
                            "anlegen: Frag die Orga des Spielfelds oder die Administration der Website. Hast du "
                            "schon eins, logg dich damit ein.",
        "reg_step_app": "Öffne dieses Spiel in der Atalaia-App mit dem Button unten (oder füge die Adresse dieser "
                        "Seite unter Spielen › Online-Anmeldung ein), logge dich mit deinem Konto ein und melde dich "
                        "für das Spiel an, mit den Repliken, die du nutzen wirst, falls das Spiel danach fragt.",
        "reg_open_app": "In der Atalaia-App öffnen",
        "reg_address": "Die Adresse dieser Seite, zum Einfügen in der App:",
        "reg_step_ticket": "Die App speichert das Check-in-Ticket und nutzt es am Spieltag auf dem Spielfeld. Ohne "
                           "die App druckst du das Ticket aus und zeigst es einem Marshal.",
        "reg_data": "Das Spielfeld bekommt den Namen, den du für das Spiel wählst, deinen Team-Wunsch, deine "
                    "Verbandsnummer (falls das Spiel danach fragt) und die angegebenen Repliken, und löscht sie "
                    "30 Tage nach dem Spiel.",
        "reg_unavailable": "Die Anmeldung für dieses Spiel ist nicht offen, oder es sind keine Plätze mehr frei.",
        # Club pages (plan phase 18)
        "club_footer": "Die öffentliche Seite des Clubs, erstellt vom Atalaia-Server.",
        "club_logo": "Logo von {club}",
        "club_crest": "Wappen von {club}",
        "club_fields": "Spielt auf diesen Spielfeldern",
        "report": "Diese Seite melden",
        "report_title": "Melden: {club}",
        "report_intro": "Wenn diese Seite Bilder oder Namen ohne Erlaubnis verwendet, beleidigend ist oder sich als "
                        "eine andere Person oder ein anderer Club ausgibt, sag der Administration dieses Servers "
                        "Bescheid: Sie kann die Seite ausblenden.",
        "report_reason": "Grund",
        "reason_rights": "Bilder oder Namen ohne Erlaubnis verwendet",
        "reason_offensive": "Beleidigender Inhalt",
        "reason_impersonation": "Gibt sich als andere Person oder anderer Club aus",
        "reason_other": "Anderer Grund",
        "report_text": "Details (optional, bis zu 1000 Zeichen)",
        "report_send": "Meldung senden",
        "report_privacy": "Die Adresse der meldenden Person wird nicht gespeichert.",
        "report_done": "Die Meldung ging an die Administration des Servers. Danke für den Hinweis.",
        "report_invalid": "Die Meldung wurde nicht angenommen: Wähle einen Grund und schreib bis zu 1000 Zeichen.",
        "report_too_many": "Zu viele Meldungen von dieser Adresse. Versuch es später noch einmal.",
        "back_club": "Zurück zu {club}",
    },
    "zh-tw": {
        "upcoming": "近期遊戲",
        "no_games": "目前還沒有排定的遊戲。",
        "cancelled": "已取消",
        "cancelled_notice": "這場遊戲已取消。",
        "reason": "原因",
        "when": "時間",
        "where": "地點",
        "mode": "模式",
        "mode_later": "待公布",
        "teams": "隊伍",
        "places": "名額",
        "places_open": "不限",
        "registration": "報名",
        "reg_not_yet": "{opens} 開放",
        "reg_open": "開放至 {closes}",
        "reg_closed": "已截止",
        "federation": "協會會員編號",
        "fed_required": "必填",
        "fed_optional": "選填",
        "apd": "APD 會員資格",
        "apd_register": "報名時必須提供",
        "apd_checkin": "報到時查驗會員卡",
        "apd_expiry": "需在有效期內",
        "apd_any": "任何 APD",
        "apd_only": "接受：{names}",
        "apd_m": "協會會員資格",  # a field outside Portugal (decision MEM-4)
        "apd_any_m": "任何協會",
        "local_time": "當地時間，{zone}",
        "calendar": "行事曆",
        "feeds_text": "這個場地的遊戲，提供給行事曆和其他網站：",
        "feed_ics": "iCalendar（.ics）",
        "feed_json": "資料（JSON）",
        "add_to_calendar": "加入行事曆（.ics）",
        "back": "{field} 的所有遊戲",
        "not_found_title": "找不到頁面",
        "not_found": "這個頁面不存在，或沒有公開。",
        "language": "語言",
        "footer": "場地的公開頁面，由 Atalaia 伺服器產生。不會顯示有誰報名。",
        "past": "已結束。",
        "full": "額滿",
        "register": "報名",
        "register_title": "報名：{game}",
        "back_game": "回到 {game}",
        "reg_intro": "報名要用這個網站的帳號，在 Atalaia App 中完成。",
        "reg_step_account": "你需要這個網站的帳號。App 和這個頁面目前還不能建立帳號：請向場地主辦或網站管理員索取。"
                            "如果你已經有帳號，就用它登入。",
        "reg_step_app": "在 Atalaia App 中，用下方的按鈕開啟這場遊戲（或把這個頁面的網址貼到「玩家 › 線上報名」），"
                        "用你的帳號登入並報名；如果這場遊戲有要求，也要登記你會使用的槍。",
        "reg_open_app": "在 Atalaia App 中開啟",
        "reg_address": "這個頁面的網址，用來貼到 App 中：",
        "reg_step_ticket": "App 會保存報到票券，當天在場地使用。沒有 App 的話，可以把票券印出來給裁判看。",
        "reg_data": "場地會收到你為這場遊戲取的名字、你想加入的隊伍、你的協會會員編號（如果遊戲有要求）以及你登記的槍，"
                    "並在遊戲結束 30 天後刪除。",
        "reg_unavailable": "這場遊戲目前沒有開放報名，或已經額滿。",
        # Club pages (plan phase 18)
        "club_footer": "社團的公開頁面，由 Atalaia 伺服器產生。",
        "club_logo": "{club} 的標誌",
        "club_crest": "{club} 的隊徽",
        "club_fields": "活動場地",
        "report": "檢舉這個頁面",
        "report_title": "檢舉：{club}",
        "report_intro": "如果這個頁面未經授權使用圖片或名稱、內容冒犯他人，或冒充其他人或社團，請通知這台伺服器的管理員，"
                        "管理員可以把它隱藏。",
        "report_reason": "原因",
        "reason_rights": "未經授權使用圖片或名稱",
        "reason_offensive": "冒犯性內容",
        "reason_impersonation": "冒充其他人或社團",
        "reason_other": "其他原因",
        "report_text": "詳細說明（選填，最多 1000 個字元）",
        "report_send": "送出檢舉",
        "report_privacy": "不會保存檢舉者的位址。",
        "report_done": "檢舉已送給伺服器的管理員。謝謝你告訴我們。",
        "report_invalid": "檢舉未被接受：請選擇一個原因，並寫最多 1000 個字元。",
        "report_too_many": "這個位址的檢舉次數太多，請稍後再試。",
        "back_club": "回到 {club}",
    },
}
LANGUAGE_NAMES = {"pt": "Português", "en": "English", "de": "Deutsch", "zh-tw": "繁體中文（台灣）"}
# Each language's BCP 47 tag, for <html lang>, the switcher's lang and hreflang and Content-Language; the
# ``?lang=`` value stays the project's code (zh-tw), as everywhere else in Atalaia.
TAGS = {"pt": "pt", "en": "en", "de": "de", "zh-tw": "zh-Hant-TW"}

_WEEKDAYS = {
    "pt": ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "de": ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"),
    "zh-tw": ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"),
}
_MONTHS = {
    "pt": ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
           "novembro", "dezembro"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
    "de": ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
           "November", "Dezember"),
    "zh-tw": tuple(f"{n} 月" for n in range(1, 13)),
}
# Chinese tags that mean Traditional characters: the script subtag Hant, or, with no script subtag, a
# region that writes them (Taiwan, Hong Kong, Macau). Plain zh, zh-CN, zh-SG and any Hans tag are Simplified,
# which none of these pages is in.
_TRADITIONAL_REGIONS = {"tw", "hk", "mo"}


def _language(tag: str) -> Optional[str]:
    """The page language an ``Accept-Language`` tag asks for (case-insensitive), or None."""
    subtags = tag.strip().lower().split("-")
    if subtags[0] == "zh":
        rest = subtags[1:]
        if "hant" in rest:
            return "zh-tw"
        if "hans" in rest:
            return None
        return "zh-tw" if any(s in _TRADITIONAL_REGIONS for s in rest) else None
    return subtags[0] if subtags[0] in LANGUAGES else None


def choose(query: Optional[str], accept_language: Optional[str]) -> tuple[str, bool]:
    """The page's language and whether it was asked for explicitly (``?lang=``): ``?lang=pt|en|de|zh-tw``,
    else the best of ``Accept-Language`` (RFC 9110 section 12.5.4, by q-value then order), else pt.
    ``de`` and ``de-*`` are German; ``zh-TW``, ``zh-Hant(-*)``, ``zh-HK`` and ``zh-MO`` are zh-tw, while
    Simplified Chinese (``zh``, ``zh-CN``, ``zh-Hans(-*)``, ``zh-SG``) is skipped like any other language."""
    if query in LANGUAGES:
        return query, True
    best: tuple[float, int, str] = (0.0, 0, DEFAULT)
    for index, item in enumerate((accept_language or "").split(",")):
        tag, _, params = item.strip().partition(";")
        language = _language(tag)
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if language is not None and q > 0 and (q, -index) > (best[0], best[1]):
            best = (q, -index, language)
    return best[2], False


COOKIE = "lang"
COOKIE_MAX_AGE = 365 * 24 * 3600


def for_request(request: Any, languages: tuple[str, ...] = LANGUAGES,
                auto: Optional[Any] = None) -> tuple[str, bool, bool]:
    """The language of this request, whether it was asked for (so links keep ``?lang=``) and whether to remember it
    in the ``lang`` cookie. With ``ATALAIA_LANG_FROM_BROWSER`` on (the default) it is ``auto`` (``choose``: ``?lang=``,
    else ``Accept-Language``, else pt) and nothing is remembered. Off, only an explicit choice counts: ``?lang=``
    (remembered, so the language switcher is used once), else the cookie, else ``ATALAIA_DEFAULT_LANG``."""
    settings = request.app.state.settings
    query = request.query_params.get("lang")
    if settings.lang_from_browser:
        lang, explicit = (auto or choose)(query, request.headers.get("accept-language"))
        return lang, explicit, False
    if query in languages:
        return query, True, True
    cookie = request.cookies.get(COOKIE)
    if cookie in languages:
        return cookie, True, False
    return (settings.default_lang if settings.default_lang in languages else languages[0]), False, False


def remember(response: Any, lang: str) -> None:
    """The ``lang`` cookie: the language alone, a year, same-site, secure; nothing identifies anyone."""
    response.set_cookie(COOKIE, lang, max_age=COOKIE_MAX_AGE, path="/", secure=True, samesite="lax", httponly=True)


def date(value: datetime, zone: str, lang: str) -> str:
    """``sábado, 8 de novembro de 2026`` / ``Saturday 8 November 2026`` / ``Samstag, 8. November 2026`` /
    ``2026 年 11 月 8 日（星期六）``, in the field's zone."""
    local = value.astimezone(ZoneInfo(zone))
    weekday, month = _WEEKDAYS[lang][local.weekday()], _MONTHS[lang][local.month - 1]
    if lang == "pt":
        return f"{weekday}, {local.day} de {month} de {local.year}"
    if lang == "de":
        return f"{weekday}, {local.day}. {month} {local.year}"
    if lang == "zh-tw":
        return f"{local.year} 年 {month} {local.day} 日（{weekday}）"
    return f"{weekday} {local.day} {month} {local.year}"


def time(value: datetime, zone: str) -> str:
    return value.astimezone(ZoneInfo(zone)).strftime("%H:%M")


def moment(value: datetime, zone: str, lang: str) -> str:
    """A date and a time: ``sábado, 8 de novembro de 2026, 09:00``; ``2026 年 11 月 8 日（星期六）09:00``
    (no comma after the full-width bracket)."""
    sep = "" if lang == "zh-tw" else ", "
    return f"{date(value, zone, lang)}{sep}{time(value, zone)}"


def span(starts: datetime, ends: datetime, zone: str, lang: str) -> str:
    """When a game is: one date with two times, or two moments when it ends on another day."""
    tz = ZoneInfo(zone)
    if starts.astimezone(tz).date() == ends.astimezone(tz).date():
        return f"{moment(starts, zone, lang)}–{time(ends, zone)}"
    to = " 至 " if lang == "zh-tw" else " – "
    return f"{moment(starts, zone, lang)}{to}{moment(ends, zone, lang)}"


def paren(text: str, lang: str) -> str:
    """A remark after a word: `` (text)``, or ``（text）`` in Chinese (full-width, no space before it)."""
    return f"（{text}）" if lang == "zh-tw" else f" ({text})"


def join(items: list[str], lang: str) -> str:
    """A list: ``a, b``, or ``a、b`` in Chinese."""
    return ("、" if lang == "zh-tw" else ", ").join(items)
