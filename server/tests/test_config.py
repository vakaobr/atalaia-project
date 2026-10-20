# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings from the environment (no database; also run by tools/check.sh)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atalaia_server.config import ConfigError, Settings, database_url_from_env, redact_url  # noqa: E402

URL = "postgresql+asyncpg://atalaia:s3cret@db:5432/atalaia"
KEY = "k" * 43
BASE = {"ATALAIA_DATABASE_URL": URL, "ATALAIA_SECRET_KEY": KEY}


class SettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        s = Settings.from_env(BASE)
        self.assertEqual(s.database_url, URL)
        self.assertEqual((s.db_pool_size, s.db_max_overflow, s.db_timeout_s), (5, 5, 5.0))
        self.assertIsNone(s.metrics_token)
        self.assertEqual(s.log_level, "info")
        self.assertEqual((s.purge_hour, s.privacy_notice_version), (3, "template-2026-10-19"))

    def test_purge_hour_and_notice_version(self) -> None:
        s = Settings.from_env({**BASE, "ATALAIA_PURGE_HOUR": "0", "ATALAIA_PRIVACY_NOTICE_VERSION": "campo-tejo-v2"})
        self.assertEqual((s.purge_hour, s.privacy_notice_version), (0, "campo-tejo-v2"))
        self.assertIsNone(Settings.from_env({**BASE, "ATALAIA_PURGE_HOUR": " OFF "}).purge_hour)
        for raw in ("24", "-1", "3am"):
            with self.subTest(raw=raw), self.assertRaisesRegex(ConfigError, "ATALAIA_PURGE_HOUR"):
                Settings.from_env({**BASE, "ATALAIA_PURGE_HOUR": raw})
        for raw in ("v 2", "-v2", "x" * 65, "versão"):
            with self.subTest(raw=raw), self.assertRaisesRegex(ConfigError, "ATALAIA_PRIVACY_NOTICE_VERSION"):
                Settings.from_env({**BASE, "ATALAIA_PRIVACY_NOTICE_VERSION": raw})

    def test_public_url(self) -> None:
        self.assertIsNone(Settings.from_env(BASE).public_url)
        for raw, expected in (("https://Campo.Example.pt", "https://campo.example.pt"),
                              ("https://campo.example.pt/", "https://campo.example.pt"),
                              ("https://campo.example.pt:8443", "https://campo.example.pt:8443"),
                              ("http://localhost:8000", "http://localhost:8000")):
            with self.subTest(raw=raw):
                self.assertEqual(Settings.from_env({**BASE, "ATALAIA_PUBLIC_URL": raw}).public_url, expected)
        for raw in ("campo.example.pt", "ftp://campo.example.pt", "http://campo.example.pt",
                    "https://campo.example.pt/site", "https://campo.example.pt/?x=1", "https://u:p@campo.example.pt",
                    "https://campo.example.pt:99999"):
            with self.subTest(raw=raw), self.assertRaisesRegex(ConfigError, "ATALAIA_PUBLIC_URL"):
                Settings.from_env({**BASE, "ATALAIA_PUBLIC_URL": raw})

    def test_firmware_keys(self) -> None:
        self.assertEqual(Settings.from_env(BASE).firmware_keys, ())  # none: the catalogue takes no entry (S19-8)
        key = "A" * 43 + "="  # 32 zero bytes
        other = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="  # 32 bytes of 1
        self.assertEqual(Settings.from_env({**BASE, "ATALAIA_FIRMWARE_KEYS": f" {key} ,{other},"}).firmware_keys,
                         (key, other))
        for raw in ("AAAA", "A" * 44, "not base64!", ",".join([key] * 9)):
            with self.subTest(raw=raw[:20]), self.assertRaisesRegex(ConfigError, "ATALAIA_FIRMWARE_KEYS"):
                Settings.from_env({**BASE, "ATALAIA_FIRMWARE_KEYS": raw})

    def test_test_adapter(self) -> None:
        self.assertFalse(Settings.from_env(BASE).test_adapter)  # off unless asked for (plan phase 17)
        self.assertFalse(Settings.from_env({**BASE, "ATALAIA_TEST_ADAPTER": "Off"}).test_adapter)
        self.assertTrue(Settings.from_env({**BASE, "ATALAIA_TEST_ADAPTER": " on "}).test_adapter)
        for raw in ("1", "yes", "true"):
            with self.subTest(raw=raw), self.assertRaisesRegex(ConfigError, "ATALAIA_TEST_ADAPTER"):
                Settings.from_env({**BASE, "ATALAIA_TEST_ADAPTER": raw})

    def test_hosted_mode(self) -> None:
        s = Settings.from_env(BASE)
        self.assertEqual((s.hosted, s.hosted_domain), (False, None))  # off: a club's own server (plan phase 21)
        s = Settings.from_env({**BASE, "ATALAIA_HOSTED": "on", "ATALAIA_HOSTED_DOMAIN": " Hub.Example.PT "})
        self.assertEqual((s.hosted, s.hosted_domain), (True, "hub.example.pt"))
        for env, reason in (({"ATALAIA_HOSTED": "on"}, "ATALAIA_HOSTED_DOMAIN is not set"),
                            ({"ATALAIA_HOSTED": "yes"}, "ATALAIA_HOSTED must be on or off"),
                            ({"ATALAIA_HOSTED_DOMAIN": "hub.example.pt"}, "only for hosted mode"),
                            ({"ATALAIA_HOSTED": "on", "ATALAIA_HOSTED_DOMAIN": "hub.example.pt",
                              "ATALAIA_PUBLIC_URL": "https://hub.example.pt"}, "ATALAIA_PUBLIC_URL must be unset"),
                            ({"ATALAIA_HOSTED": "on", "ATALAIA_HOSTED_DOMAIN": "https://hub.example.pt"},
                             "domain name"),
                            ({"ATALAIA_HOSTED": "on", "ATALAIA_HOSTED_DOMAIN": "hub.example.pt:8443"}, "domain name"),
                            ({"ATALAIA_HOSTED": "on", "ATALAIA_HOSTED_DOMAIN": "localhost"}, "domain name"),
                            ({"ATALAIA_HOSTED": "on", "ATALAIA_HOSTED_DOMAIN": "-hub.example.pt"}, "domain name")):
            with self.subTest(env=env), self.assertRaisesRegex(ConfigError, reason):
                Settings.from_env({**BASE, **env})
        self.assertIn("hosted=True", repr(Settings.from_env({**BASE, "ATALAIA_HOSTED": "on",
                                                             "ATALAIA_HOSTED_DOMAIN": "hub.example.pt"})))

    def test_every_setting(self) -> None:
        s = Settings.from_env({
            **BASE, "ATALAIA_DB_POOL_SIZE": "10", "ATALAIA_DB_MAX_OVERFLOW": "0",
            "ATALAIA_DB_TIMEOUT_S": "2.5", "ATALAIA_METRICS_TOKEN": "m" * 32, "ATALAIA_LOG_LEVEL": "WARNING",
        })
        self.assertEqual((s.db_pool_size, s.db_max_overflow, s.db_timeout_s), (10, 0, 2.5))
        self.assertEqual(s.metrics_token, "m" * 32)
        self.assertEqual(s.log_level, "warning")

    def test_empty_values_mean_the_default(self) -> None:
        s = Settings.from_env({**BASE, "ATALAIA_DB_POOL_SIZE": " ",
                               "ATALAIA_METRICS_TOKEN": "", "ATALAIA_LOG_LEVEL": ""})
        self.assertEqual(s.db_pool_size, 5)
        self.assertIsNone(s.metrics_token)
        self.assertEqual(s.log_level, "info")

    def test_the_database_url_is_required(self) -> None:
        with self.assertRaisesRegex(ConfigError, "ATALAIA_DATABASE_URL is not set"):
            Settings.from_env({})

    def test_only_postgresql_through_asyncpg(self) -> None:
        for url in ("postgresql://a:b@db/atalaia", "sqlite+aiosqlite:///x.db", "mysql+aiomysql://db/x"):
            with self.subTest(url=url), self.assertRaisesRegex(ConfigError, "must start with postgresql\\+asyncpg"):
                Settings.from_env({**BASE, "ATALAIA_DATABASE_URL": url})

    def test_bad_urls(self) -> None:
        for url, reason in (("postgresql+asyncpg://db:5432/", "no database name"),
                            ("postgresql+asyncpg:///atalaia", "no host"),
                            ("postgresql+asyncpg://db:port/atalaia", "not a valid URL")):
            with self.subTest(url=url), self.assertRaisesRegex(ConfigError, reason):
                Settings.from_env({**BASE, "ATALAIA_DATABASE_URL": url})

    def test_bad_numbers_are_errors_not_defaults(self) -> None:
        for name, raw, reason in (("ATALAIA_DB_POOL_SIZE", "five", "an integer"),
                                  ("ATALAIA_DB_POOL_SIZE", "0", "between 1 and 100"),
                                  ("ATALAIA_DB_MAX_OVERFLOW", "101", "between 0 and 100"),
                                  ("ATALAIA_DB_TIMEOUT_S", "0", "between 0.1 and 60"),
                                  ("ATALAIA_DB_TIMEOUT_S", "soon", "a number")):
            with self.subTest(name=name, raw=raw), self.assertRaisesRegex(ConfigError, f"{name} must be {reason}"):
                Settings.from_env({**BASE, name: raw})

    def test_bad_log_level(self) -> None:
        with self.assertRaisesRegex(ConfigError, "ATALAIA_LOG_LEVEL"):
            Settings.from_env({**BASE, "ATALAIA_LOG_LEVEL": "loud"})

    def test_a_short_metrics_token_is_refused(self) -> None:
        with self.assertRaisesRegex(ConfigError, "at least 32 characters"):
            Settings.from_env({**BASE, "ATALAIA_METRICS_TOKEN": "short"})

    def test_the_secret_key_is_required_and_long(self) -> None:
        with self.assertRaisesRegex(ConfigError, "ATALAIA_SECRET_KEY is not set"):
            Settings.from_env({"ATALAIA_DATABASE_URL": URL})
        with self.assertRaisesRegex(ConfigError, "ATALAIA_SECRET_KEY must be at least 32 characters"):
            Settings.from_env({**BASE, "ATALAIA_SECRET_KEY": "k" * 31})
        self.assertEqual(Settings.from_env(BASE).secret_key, KEY)

    def test_migrations_need_only_the_database_url(self) -> None:
        self.assertEqual(database_url_from_env({"ATALAIA_DATABASE_URL": f" {URL} "}), URL)
        with self.assertRaisesRegex(ConfigError, "ATALAIA_DATABASE_URL is not set"):
            database_url_from_env({"ATALAIA_SECRET_KEY": KEY})
        with self.assertRaisesRegex(ConfigError, "must start with"):
            database_url_from_env({"ATALAIA_DATABASE_URL": "sqlite:///x"})

    def test_repr_hides_the_password_and_the_token(self) -> None:
        s = Settings(database_url=URL, secret_key=KEY, metrics_token="x" * 40)
        text = repr(s)
        self.assertNotIn("s3cret", text)
        self.assertNotIn(KEY, text)
        self.assertNotIn("x" * 40, text)
        self.assertIn("atalaia:***@db:5432", text)
        self.assertIn("metrics_token=set", text)


class RedactTests(unittest.TestCase):
    def test_redact(self) -> None:
        self.assertEqual(redact_url(URL), "postgresql+asyncpg://atalaia:***@db:5432/atalaia")
        self.assertEqual(redact_url("postgresql+asyncpg://u:p@[::1]:5432/d?ssl=require"),
                         "postgresql+asyncpg://u:***@[::1]:5432/d?ssl=require")
        self.assertEqual(redact_url("postgresql+asyncpg://db/atalaia"), "postgresql+asyncpg://db/atalaia")


if __name__ == "__main__":
    unittest.main()
