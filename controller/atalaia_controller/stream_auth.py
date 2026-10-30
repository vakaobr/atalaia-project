# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How a client gives its token to ``WS /api/v1/stream``, and keeping tokens out of logs (LIVE2-1).

A browser cannot put an ``Authorization`` header on a WebSocket, and the first version of the
stream took the token in the address (``?token=``), where uvicorn's access log, a proxy's log and
the browser's history all keep it. The GM token is the field's master key.

The token now travels in the ``Sec-WebSocket-Protocol`` header, as a second offered subprotocol:

    new WebSocket(url, ["atalaia.v1", "atalaia.token." + base64url(token)])

The server picks ``atalaia.v1`` (what it answers with) and never echoes the token. The token is
base64url-encoded (UTF-8 bytes, no padding) because a subprotocol must be an HTTP token and a
configured token can be any text. Header values are in no access log.

Order of precedence: ``Authorization: Bearer``, the subprotocol, then ``?token=``. The query form is
**deprecated**: it still works so a console or an app installed before this change keeps its stream
until it updates, and the controller logs a warning once per run when it is used. Remove it two
releases after the console and the app both use the subprotocol.

``RedactTokens`` is the defence in depth: a logging filter that blanks the value of ``token=`` (and
other credential-like query keys) and a ``Bearer`` value in any log line, for uvicorn's access log
on the Pi controller and on the site server.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from typing import Any, Optional, Sequence
from urllib.parse import parse_qs

SUBPROTOCOL = "atalaia.v1"
TOKEN_PREFIX = "atalaia.token."

log = logging.getLogger("atalaia")
_warned = False


def encode_subprotocol(token: str) -> str:
    """The subprotocol a client offers to carry ``token``."""
    return TOKEN_PREFIX + base64.urlsafe_b64encode(token.encode("utf-8")).rstrip(b"=").decode("ascii")


def subprotocol_token(offered: Sequence[str]) -> Optional[str]:
    """The token in the offered subprotocols, if one is there and well formed."""
    for item in offered:
        if item.startswith(TOKEN_PREFIX):
            text = item[len(TOKEN_PREFIX):]
            try:
                return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("utf-8") or None
            except (binascii.Error, UnicodeDecodeError, ValueError):
                return None
    return None


def stream_token(scope: dict[str, Any]) -> Optional[str]:
    """The token of a WebSocket scope: the Authorization header, the subprotocol, or (deprecated) ``?token=``."""
    global _warned
    headers = dict(scope.get("headers") or [])
    header = headers.get(b"authorization", b"").decode("latin-1")
    if header.lower().startswith("bearer ") and header[7:].strip():
        return header[7:].strip()
    token = subprotocol_token(scope.get("subprotocols") or [])
    if token:
        return token
    query = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("token") or [None]
    if query[0]:
        if not _warned:
            _warned = True
            log.warning("a client sent its token in the stream's address (?token=): deprecated, it is "
                        "kept in access logs of proxies; clients use the Sec-WebSocket-Protocol header now")
        return query[0]
    return None


def accepted_subprotocol(scope: dict[str, Any]) -> Optional[str]:
    """What the server answers in ``Sec-WebSocket-Protocol``: ``atalaia.v1`` when it was offered, never the token."""
    return SUBPROTOCOL if SUBPROTOCOL in (scope.get("subprotocols") or []) else None


# The query keys whose values are credentials, in the address of any request.
_QUERY = re.compile(r"(?i)([?&;](?:token|access_token|id_token|refresh_token|api_key|apikey|key|secret|password|code|"
                    r"state|ticket|sig|signature)=)[^&\s\"']*")
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")
_FRAGMENT_TOKEN = re.compile(r"(?i)(#token=)[^&\s\"']*")
REDACTED = "REDACTED"


def redact(text: str) -> str:
    """``text`` with credential-like query values, ``#token=`` fragments and Bearer values blanked."""
    text = _QUERY.sub(lambda m: m.group(1) + REDACTED, text)
    text = _FRAGMENT_TOKEN.sub(lambda m: m.group(1) + REDACTED, text)
    return _BEARER.sub(lambda m: m.group(1) + REDACTED, text)


class RedactTokens(logging.Filter):
    """Blanks credentials in a log record's message and arguments (uvicorn's access log passes the
    request line as an argument)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True


def install_redaction() -> None:
    """On the loggers uvicorn writes request lines to. Idempotent."""
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactTokens) for f in logger.filters):
            logger.addFilter(RedactTokens())
