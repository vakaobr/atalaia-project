# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""LIVE2-1: the stream's token travels in a header, and credentials stay out of logs."""

from __future__ import annotations

import io
import logging
import unittest

import support  # noqa: F401  (puts the packages on the path)
from atalaia_controller import stream_auth as sa


def scope(headers=None, subprotocols=None, query=b""):
    return {"headers": headers or [], "subprotocols": subprotocols or [], "query_string": query}


class StreamToken(unittest.TestCase):
    def test_the_subprotocol_round_trips_any_text(self):
        for token in ("gm-secret", "a.b_c-d", "with space & ünï/+=", "x" * 200):
            self.assertEqual(sa.subprotocol_token(["atalaia.v1", sa.encode_subprotocol(token)]), token)
        # a subprotocol is an HTTP token: nothing else may appear in what we send
        self.assertRegex(sa.encode_subprotocol("with space & ünï/+="), r"^[A-Za-z0-9._-]+$")

    def test_a_damaged_or_missing_carrier_gives_no_token(self):
        self.assertIsNone(sa.subprotocol_token(["atalaia.v1"]))
        self.assertIsNone(sa.subprotocol_token(["atalaia.token.***"]))
        self.assertIsNone(sa.subprotocol_token(["atalaia.token."]))
        self.assertIsNone(sa.subprotocol_token(["atalaia.token.gA"]))  # not UTF-8

    def test_precedence_header_then_subprotocol_then_query(self):
        both = scope([(b"authorization", b"Bearer from-header")], ["atalaia.v1", sa.encode_subprotocol("from-sub")],
                     b"token=from-query")
        self.assertEqual(sa.stream_token(both), "from-header")
        both["headers"] = []
        self.assertEqual(sa.stream_token(both), "from-sub")
        both["subprotocols"] = ["atalaia.v1"]
        sa._warned = False
        with self.assertLogs("atalaia", level="WARNING"):
            self.assertEqual(sa.stream_token(both), "from-query")  # deprecated, still works
        self.assertIsNone(sa.stream_token(scope()))

    def test_the_answer_never_echoes_the_token(self):
        offered = scope(subprotocols=["atalaia.v1", sa.encode_subprotocol("gm-secret")])
        self.assertEqual(sa.accepted_subprotocol(offered), "atalaia.v1")
        self.assertIsNone(sa.accepted_subprotocol(scope(subprotocols=[sa.encode_subprotocol("gm-secret")])))
        self.assertIsNone(sa.accepted_subprotocol(scope()))


class Redaction(unittest.TestCase):
    def test_credential_like_values_are_blanked(self):
        for text in ('GET /api/v1/stream?token=SECRETVALUE HTTP/1.1',
                     'GET /x?a=1&token=SECRETVALUE&b=2 HTTP/1.1',
                     'GET /x?access_token=SECRETVALUE HTTP/1.1',
                     'GET /cb?code=SECRETVALUE&state=SECRETVALUE HTTP/1.1',
                     'GET /x?API_KEY=SECRETVALUE HTTP/1.1',
                     'Authorization: Bearer SECRETVALUE',
                     'https://h/scoreboard#token=SECRETVALUE&ca=ab'):
            self.assertNotIn("SECRETVALUE", sa.redact(text), text)
        self.assertEqual(sa.redact('GET /x?a=1&b=2 HTTP/1.1'), 'GET /x?a=1&b=2 HTTP/1.1')
        self.assertIn("a=1&token=REDACTED&b=2", sa.redact('GET /x?a=1&token=SECRETVALUE&b=2'))

    def test_uvicorns_access_log_line_is_redacted_through_its_arguments(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("uvicorn.access")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        sa.install_redaction()
        sa.install_redaction()  # idempotent
        try:
            self.assertEqual(sum(isinstance(f, sa.RedactTokens) for f in logger.filters), 1)
            logger.info('%s - "%s %s HTTP/%s" %d', "10.0.0.2:5555", "GET", "/api/v1/stream?token=SECRETVALUE", "1.1", 101)
        finally:
            logger.removeHandler(handler)
        self.assertNotIn("SECRETVALUE", stream.getvalue())
        self.assertIn("token=REDACTED", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
