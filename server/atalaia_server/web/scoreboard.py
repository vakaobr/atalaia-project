# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's public scoreboard (plan phase 20; ADR-P4-1's ``fields.public_scoreboard``, off by default).

    GET /f/<slug>/scoreboard        the field's live game (or the last one, for 12 hours after it ended):
                                    its name, mode, state and each team's score, refreshed every 30 s
    GET /f/<slug>/scoreboard.json   the same as JSON (``atalaia.scoreboard`` version 1)

Only for a field whose admin turned it on (``PUT /api/v1/fields/{id}/history/settings``); any other slug is a
404 like a page that never existed. A live game's scores are the field's ``spectator_delay_s`` behind (60 s by
default), so a scoreboard on a phone gives no live intelligence; nothing else of the game is shown: no
events, no players, no parameters, no nodes (decision S20-5). Rendered like the field pages (``string.Template``,
every value escaped, no JavaScript: the page reloads itself with ``<meta http-equiv="refresh">``), pt-PT or
English.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.fields import SLUG
from ..db import get_session
from ..models import Field
from ..services import history
from . import i18n
from .field_pages import GET_HEAD, Page, _load, answer, esc, no_feed

router = APIRouter(include_in_schema=False)

TEMPLATE = _load("scoreboard.html")
CACHE = "public, max-age=15"
REFRESH_S = 30
FORMAT = "atalaia.scoreboard"

STRINGS = {
    "pt": {"title": "Marcador: {field}", "none": "Não há nenhum jogo a decorrer.", "team": "Equipa",
           "score": "Pontos", "state_ready": "a preparar", "state_running": "a decorrer", "state_paused": "em pausa",
           "state_ended": "terminado", "winner": "vence", "draw": "empate",
           "delayed": "Pontuação com {delay} s de atraso. Atualiza a cada {refresh} s.",
           "refresh": "Atualiza a cada {refresh} s.",
           "footer": "Marcador público do campo, feito pelo servidor Atalaia. Não mostra jogadores."},
    "en": {"title": "Scoreboard: {field}", "none": "No game is running.", "team": "Team", "score": "Points",
           "state_ready": "getting ready", "state_running": "running", "state_paused": "paused",
           "state_ended": "ended", "winner": "wins", "draw": "draw",
           "delayed": "Scores {delay} s behind. Refreshes every {refresh} s.",
           "refresh": "Refreshes every {refresh} s.",
           "footer": "The field's public scoreboard, made by the Atalaia site server. It shows no players."},
}
assert set(STRINGS) == set(i18n.LANGUAGES)


async def _state(db: AsyncSession, field: Field, now: datetime) -> dict[str, Any]:
    """What the scoreboard shows: the game (or None) with its delayed scores."""
    delay = (await history.settings(db, field.id))["spectator_delay_s"]
    game = await history.public_game(db, field.id, now)
    if game is None:
        return {"format": FORMAT, "version": 1, "field": field.name, "game": None, "delay_s": delay}
    cut = history.cutoff(game, delay, staff=False, now=now)
    summary = history.game_summary(game, await history.totals_until(db, game, cut))
    summary.pop("id")
    return {"format": FORMAT, "version": 1, "field": field.name, "game": summary,
            "delay_s": delay if cut is not None else 0}


async def _field(db: AsyncSession, slug: str) -> Optional[Field]:
    return await history.public_field(db, slug) if SLUG.fullmatch(slug) else None


@router.api_route("/f/{slug}/scoreboard.json", methods=GET_HEAD)
async def scoreboard_json(slug: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    field = await _field(db, slug)
    if field is None:
        return no_feed()
    now = datetime.now(timezone.utc)
    body = json.dumps(await _state(db, field, now), ensure_ascii=False, sort_keys=True)
    return answer(request, body, "application/json", now, CACHE, extra={"Access-Control-Allow-Origin": "*"})


def _table(t: dict[str, str], game: dict[str, Any]) -> str:
    rows = []
    for team in game["teams"]:
        name = team["display_name"] or team["team"]
        won = game["winner"] == team["team"]
        mark = f' <span class="badge">{esc(t["winner"])}</span>' if won else ""
        css = ' class="winner"' if won else ""
        rows.append(f'<tr{css}><th scope="row">{esc(name)}{mark}</th>'
                    f'<td class="score">{esc(team["score"])}</td></tr>\n')
    return (f'<table class="scores">\n<thead><tr><th scope="col">{esc(t["team"])}</th>'
            f'<th scope="col">{esc(t["score"])}</th></tr></thead>\n<tbody>\n{"".join(rows)}</tbody>\n</table>\n')


@router.api_route("/f/{slug}/scoreboard", methods=GET_HEAD)
async def scoreboard_page(slug: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    page = Page(request)
    field = await _field(db, slug)
    if field is None:
        return page.not_found(request)
    now = datetime.now(timezone.utc)
    state = await _state(db, field, now)
    t = STRINGS[page.lang]
    game = state["game"]
    if game is None:
        body = f"<p>{esc(t['none'])}</p>\n"
        note = t["refresh"].format(refresh=REFRESH_S)
    else:
        status = t[f"state_{game['state']}"]
        if game["state"] == "ended" and game["winner"] is None:
            status += f" ({t['draw']})"
        body = (f'<h2>{esc(game["name"])}</h2>\n<p class="when"><code>{esc(game["mode_id"])}</code> · '
                f"{esc(status)}</p>\n" + _table(t, game))
        note = (t["delayed"].format(delay=state["delay_s"], refresh=REFRESH_S) if state["delay_s"]
                else t["refresh"].format(refresh=REFRESH_S))
    title = t["title"].format(field=field.name)
    content = TEMPLATE.substitute(heading=esc(title), body=body, note=esc(note))
    head = f'<meta http-equiv="refresh" content="{REFRESH_S}">\n'
    response = page.render(request, title, content, now, head=head, footer=t["footer"])
    response.headers["Cache-Control"] = CACHE
    return response
