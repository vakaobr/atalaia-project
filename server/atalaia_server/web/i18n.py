# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field pages' texts in pt-PT and English, the language choice and dates in the field's zone.

Portuguese is pt-PT, inclusive and impersonal (the project's rule: "marshal" with one L,
"squad" untranslated, team = "equipa"); dates are written out by hand (no locale database in
the image), lower-case months and weekdays as pt-PT writes them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

LANGUAGES = ("pt", "en")
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
        "reg_step_account": "Criar uma conta neste site (ou entrar com a que já existe).",
        "reg_step_app": "Na app Atalaia, abrir este campo e este jogo e fazer a inscrição, com as réplicas "
                        "que vão ser usadas, se o jogo as pedir.",
        "reg_step_ticket": "A app guarda o bilhete de check-in e usa-o no dia, no campo. Sem a app, o bilhete "
                           "pode ser impresso e mostrado a um marshal.",
        "reg_data": "O campo recebe o nome escolhido para o jogo, a preferência de equipa, o número de federado "
                    "(se o jogo o pedir) e as réplicas declaradas, e apaga-os 30 dias depois do jogo.",
        "reg_unavailable": "As inscrições para este jogo não estão abertas, ou já não há lugares.",
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
        "reg_step_account": "Make an account on this site (or log in with the one you have).",
        "reg_step_app": "In the Atalaia app, open this field and this game and register, with the replicas you "
                        "will use, if the game asks for them.",
        "reg_step_ticket": "The app keeps the check-in ticket and uses it on the day, at the field. Without the app, "
                           "print the ticket and show it to a marshal.",
        "reg_data": "The field gets the name you choose for the game, your team preference, your federation number "
                    "(if the game asks for one) and the declared replicas, and erases them 30 days after the game.",
        "reg_unavailable": "Registration for this game is not open, or there are no places left.",
    },
}
LANGUAGE_NAMES = {"pt": "Português", "en": "English"}

_WEEKDAYS = {
    "pt": ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}
_MONTHS = {
    "pt": ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
           "novembro", "dezembro"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
}


def choose(query: Optional[str], accept_language: Optional[str]) -> tuple[str, bool]:
    """The page's language and whether it was asked for explicitly (``?lang=``): ``?lang=pt|en``,
    else the best of ``Accept-Language`` (RFC 9110 section 12.5.4, by q-value then order), else pt."""
    if query in LANGUAGES:
        return query, True
    best: tuple[float, int, str] = (0.0, 0, DEFAULT)
    for index, item in enumerate((accept_language or "").split(",")):
        tag, _, params = item.strip().partition(";")
        primary = tag.strip().lower().split("-")[0]
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if primary in LANGUAGES and q > 0 and (q, -index) > (best[0], best[1]):
            best = (q, -index, primary)
    return best[2], False


def date(value: datetime, zone: str, lang: str) -> str:
    """``sábado, 8 de novembro de 2026`` / ``Saturday 8 November 2026``, in the field's zone."""
    local = value.astimezone(ZoneInfo(zone))
    weekday, month = _WEEKDAYS[lang][local.weekday()], _MONTHS[lang][local.month - 1]
    if lang == "pt":
        return f"{weekday}, {local.day} de {month} de {local.year}"
    return f"{weekday} {local.day} {month} {local.year}"


def time(value: datetime, zone: str) -> str:
    return value.astimezone(ZoneInfo(zone)).strftime("%H:%M")


def moment(value: datetime, zone: str, lang: str) -> str:
    """A date and a time: ``sábado, 8 de novembro de 2026, 09:00``."""
    return f"{date(value, zone, lang)}, {time(value, zone)}"


def span(starts: datetime, ends: datetime, zone: str, lang: str) -> str:
    """When a game is: one date with two times, or two moments when it ends on another day."""
    tz = ZoneInfo(zone)
    if starts.astimezone(tz).date() == ends.astimezone(tz).date():
        return f"{date(starts, zone, lang)}, {time(starts, zone)}–{time(ends, zone)}"
    return f"{moment(starts, zone, lang)} – {moment(ends, zone, lang)}"
