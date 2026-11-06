# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings from the environment (no database; also run by tools/check.sh)."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atalaia_server.config import (QUOTA_DEFAULTS, ConfigError, Settings, database_url_from_env,  # noqa: E402
                                   redact_url)

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

    def test_a_server_that_is_not_hosted_needs_its_public_url(self) -> None:
        """SRV-7: the WebAuthn origin and the redirect URI must not come from the Host header."""
        from atalaia_server.config import require_public_url
        with self.assertRaisesRegex(ConfigError, "ATALAIA_PUBLIC_URL is not set"):
            require_public_url(Settings.from_env(BASE))
        self.assertTrue(require_public_url(Settings.from_env({**BASE, "ATALAIA_PUBLIC_URL": "https://campo.example.pt"})))
        self.assertTrue(require_public_url(Settings.from_env({**BASE, "ATALAIA_PUBLIC_URL": "http://localhost:8000"})))
        self.assertTrue(require_public_url(Settings.from_env({**BASE, "ATALAIA_HOSTED": "on",
                                                              "ATALAIA_HOSTED_DOMAIN": "hub.example.pt"})))
        # A preview is let through (its start must not break) and the caller warns.
        self.assertFalse(require_public_url(Settings.from_env({**BASE, "ATALAIA_PREVIEW": "on"})))

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

    def test_the_atak_relay(self) -> None:
        """The remote ATAK relay (Phase 4 follow-up FU5): off by default; on, it needs a name for the devices."""
        s = Settings.from_env(BASE)
        self.assertEqual((s.atak_relay, s.atak_relay_port, s.relay_public_port()), (False, 8089, 8089))
        with self.assertRaisesRegex(ConfigError, "ATALAIA_ATAK_RELAY=on needs ATALAIA_ATAK_RELAY_HOST"):
            Settings.from_env({**BASE, "ATALAIA_ATAK_RELAY": "on"})
        s = Settings.from_env({**BASE, "ATALAIA_ATAK_RELAY": "on", "ATALAIA_PUBLIC_URL": "https://Campo.example.pt"})
        self.assertEqual(s.relay_host(), "campo.example.pt")
        s = Settings.from_env({**BASE, "ATALAIA_ATAK_RELAY": "on", "ATALAIA_PUBLIC_URL": "https://campo.example.pt",
                               "ATALAIA_ATAK_RELAY_HOST": "ATAK.Example.pt", "ATALAIA_ATAK_RELAY_PORT": "9443",
                               "ATALAIA_ATAK_RELAY_PUBLIC_PORT": "443"})
        self.assertEqual((s.relay_host(), s.atak_relay_port, s.relay_public_port()), ("atak.example.pt", 9443, 443))
        for name, raw in (("ATALAIA_ATAK_RELAY", "yes"), ("ATALAIA_ATAK_RELAY_PORT", "0"),
                          ("ATALAIA_ATAK_RELAY_PORT", "65536"), ("ATALAIA_ATAK_RELAY_PUBLIC_PORT", "x"),
                          ("ATALAIA_ATAK_RELAY_HOST", "https://campo.example.pt"),
                          ("ATALAIA_ATAK_RELAY_HOST", "campo.example.pt:8089")):
            with self.subTest(name=name, raw=raw), self.assertRaisesRegex(ConfigError, name):
                Settings.from_env({**BASE, name: raw})
        hosted = {**BASE, "ATALAIA_HOSTED": "on", "ATALAIA_HOSTED_DOMAIN": "hub.example.pt", "ATALAIA_ATAK_RELAY": "on"}
        s = Settings.from_env(hosted)
        self.assertEqual((s.relay_host("campo-a"), s.relay_host()), ("campo-a.hub.example.pt", None))
        with self.assertRaisesRegex(ConfigError, "ATALAIA_ATAK_RELAY_HOST must be unset in hosted mode"):
            Settings.from_env({**hosted, "ATALAIA_ATAK_RELAY_HOST": "atak.example.pt"})

    def test_the_apps_identity_for_app_links(self) -> None:
        """PKA-1: the package and its certificates go together; each is checked."""
        sha = ":".join(["ab"] * 32)
        s = Settings.from_env(BASE)
        self.assertEqual((s.app_android_package, s.app_android_sha256, s.app_ios_app_ids), (None, (), ()))
        s = Settings.from_env({**BASE, "ATALAIA_APP_ANDROID_PACKAGE": "org.atalaia.app",
                               "ATALAIA_APP_ANDROID_SHA256": f"{sha}, {sha.upper()}",
                               "ATALAIA_APP_IOS_APP_IDS": "ABCDE12345.org.atalaia.app"})
        self.assertEqual(s.app_android_sha256, (sha.upper(), sha.upper()))
        self.assertEqual(s.app_ios_app_ids, ("ABCDE12345.org.atalaia.app",))
        for env in ({"ATALAIA_APP_ANDROID_PACKAGE": "org.atalaia.app"}, {"ATALAIA_APP_ANDROID_SHA256": sha},
                    {"ATALAIA_APP_ANDROID_PACKAGE": "nodots", "ATALAIA_APP_ANDROID_SHA256": sha},
                    {"ATALAIA_APP_ANDROID_PACKAGE": "org.atalaia.app", "ATALAIA_APP_ANDROID_SHA256": "AB:CD"},
                    {"ATALAIA_APP_IOS_APP_IDS": "org.atalaia.app"}):
            with self.subTest(env=env), self.assertRaisesRegex(ConfigError, "ATALAIA_APP_"):
                Settings.from_env({**BASE, **env})

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


class QuotaSettingsTests(unittest.TestCase):
    """Hosted mode's per-field quotas, the export's limits and the watch's interval (S21-12)."""

    def test_defaults(self) -> None:
        s = Settings.from_env(BASE)
        self.assertEqual(dict(s.quotas), QUOTA_DEFAULTS)
        self.assertEqual((s.export_min_interval_s, s.export_max_mb, s.hosted_watch_s), (300, 512, 2.0))
        self.assertTrue(all(v >= 1 for v in QUOTA_DEFAULTS.values()))

    def test_overrides_and_off(self) -> None:
        s = Settings.from_env({**BASE, "ATALAIA_QUOTA_GAMES": "50", "ATALAIA_QUOTA_ACCOUNTS": " off ",
                               "ATALAIA_EXPORT_MIN_INTERVAL_S": "0", "ATALAIA_EXPORT_MAX_MB": "64",
                               "ATALAIA_HOSTED_WATCH_S": "0.5"})
        self.assertEqual((s.quotas["games"], s.quotas["accounts"], s.quotas["streams"]),
                         (50, 0, QUOTA_DEFAULTS["streams"]))
        self.assertEqual((s.export_min_interval_s, s.export_max_mb, s.hosted_watch_s), (0, 64, 0.5))

    def test_wrong_values_are_errors(self) -> None:
        for env in ({"ATALAIA_QUOTA_GAMES": "0"}, {"ATALAIA_QUOTA_GAMES": "-1"}, {"ATALAIA_QUOTA_GAMES": "many"},
                    {"ATALAIA_QUOTA_STREAMS": "1.5"}, {"ATALAIA_EXPORT_MAX_MB": "0"},
                    {"ATALAIA_EXPORT_MIN_INTERVAL_S": "86401"}, {"ATALAIA_HOSTED_WATCH_S": "0"},
                    {"ATALAIA_HOSTED_WATCH_S": "61"}):
            with self.subTest(env=env), self.assertRaisesRegex(ConfigError, "ATALAIA_"):
                Settings.from_env({**BASE, **env})

    def test_unknown_quota_name_is_refused(self) -> None:
        with self.assertRaisesRegex(ConfigError, "unknown quota"):
            Settings(database_url=URL, secret_key=KEY, quotas={"gams": 3})
        s = Settings(database_url=URL, secret_key=KEY, quotas={"games": 3})  # the rest keep their defaults
        self.assertEqual((s.quotas["games"], s.quotas["accounts"]), (3, QUOTA_DEFAULTS["accounts"]))


class RedactTests(unittest.TestCase):
    def test_redact(self) -> None:
        self.assertEqual(redact_url(URL), "postgresql+asyncpg://atalaia:***@db:5432/atalaia")
        self.assertEqual(redact_url("postgresql+asyncpg://u:p@[::1]:5432/d?ssl=require"),
                         "postgresql+asyncpg://u:***@[::1]:5432/d?ssl=require")
        self.assertEqual(redact_url("postgresql+asyncpg://db/atalaia"), "postgresql+asyncpg://db/atalaia")



class ComposeTests(unittest.TestCase):
    """The settings an operator puts in .env reach the server's container: docker-compose.yml lists them in
    the server's environment (the social login settings were missing until 2026-10-29, so no Docker deployment
    could turn a provider on)."""

    def test_the_social_login_settings_reach_the_container(self) -> None:
        compose = Path(__file__).resolve().parents[1] / "docker-compose.yml"
        if not compose.exists():
            self.skipTest("docker-compose.yml is not next to the tests here")
        text = compose.read_text(encoding="utf-8")
        for provider, names in (("GOOGLE", ("CLIENT_ID", "CLIENT_SECRET")),
                                ("MICROSOFT", ("CLIENT_ID", "CLIENT_SECRET", "TENANT")),
                                ("APPLE", ("CLIENT_ID", "TEAM_ID", "KEY_ID", "KEY_FILE"))):
            for name in names:
                var = f"ATALAIA_OIDC_{provider}_{name}"
                self.assertIn(f'{var}: "${{{var}:-}}"', text, var)

    def test_every_setting_reaches_the_container_or_is_left_out_on_purpose(self) -> None:
        """Each setting the server reads (recorded from Settings.from_env, plus the env reads elsewhere in the
        package) and each one in README.md's settings table is passed to a container by one of the Compose files,
        or is in LEFT_OUT with its reason (SRVENV-1: ATALAIA_APP_ANDROID_* were in .env and never arrived)."""
        files, readme = _compose_files(self)
        server_env = {k for name, doc in files.items() for k in _service_env(doc, "server")}
        any_env = {k for doc in files.values() for svc in (doc.get("services") or {}) for k in _service_env(doc, svc)}
        recorder = _Recorder(BASE)
        Settings.from_env(recorder)
        read_by_settings = {k for k in recorder.seen if k.startswith("ATALAIA_")}
        self.assertGreater(len(read_by_settings), 40)
        source = "\n".join(p.read_text(encoding="utf-8")
                           for p in (Path(__file__).resolve().parents[1] / "atalaia_server").rglob("*.py"))
        read_elsewhere = set(re.findall(r"""(?:environ|env)(?:\.get\(|\[)\s*["'](ATALAIA_[A-Z0-9_]*[A-Z0-9])["']""",
                                        source))
        documented = _readme_settings(readme)
        read_by_scripts = set(re.findall(r"ATALAIA_[A-Z0-9_]*[A-Z0-9]", "\n".join(
            p.read_text(encoding="utf-8") for p in Path(__file__).resolve().parents[1].glob("*.sh"))))
        self.assertIn("ATALAIA_APP_ANDROID_SHA256", documented)
        for var in sorted(read_by_settings - LEFT_OUT.keys()):
            with self.subTest(var=var):
                self.assertIn(var, server_env, f"{var} is read by the server's settings but no Compose file passes "
                                               "it to the server: add it, or to LEFT_OUT with the reason")
        for var in sorted((read_elsewhere | documented) - LEFT_OUT.keys()):
            with self.subTest(var=var):
                self.assertIn(var, any_env, f"{var} reaches no container: add it to a Compose file, or to "
                                            "LEFT_OUT with the reason")
        for var, why in LEFT_OUT.items():
            with self.subTest(var=var):
                self.assertNotIn(var, server_env if var in read_by_settings else any_env,
                                 f"{var} is passed after all: take it out of LEFT_OUT")
                self.assertIn(var, read_by_settings | read_elsewhere | documented | read_by_scripts,
                              f"{var}: nothing reads it")
                self.assertTrue(why)

    def test_an_empty_setting_is_the_servers_own_default(self) -> None:
        """"${NAME:-}" sends an empty value when .env has none: the server must read it as unset. And the base
        file's other fallbacks ("${NAME:-info}") must be the server's own defaults."""
        files, _ = _compose_files(self)
        default = Settings.from_env(BASE)
        for name, doc in files.items():
            for var, value in _service_env(doc, "server").items():
                m = re.fullmatch(r"\$\{(ATALAIA_[A-Z0-9_]+):-([^}]*)\}", str(value))
                if not m or m.group(1) != var or (m.group(2) and name != "docker-compose.yml"):
                    continue
                with self.subTest(file=name, var=var):
                    self.assertEqual(Settings.from_env({**BASE, var: m.group(2)}), default, f"{name}: {var}")


# Settings no Compose file passes on purpose; the README's table says so in each row (SRVENV-*).
LEFT_OUT = {
    "ATALAIA_TEST_ADAPTER": "trials and tests only: a deployment never offers the in-memory platform",
    "ATALAIA_ALLOW_SIGNUP_WITHOUT_NOTICE": "development and tests only: a deployment publishes its notice (LIVE-2)",
    "ATALAIA_ATAK_RELAY_PORT": "the relay listens on 8089 in the container, the port Compose publishes; "
                               "ATALAIA_ATAK_PORT changes the published one",
    "ATALAIA_BACKUP_DAYS": "read by backup.sh from the env file, not by a container",
}


class _Recorder(dict):
    """A mapping that remembers each key asked for (present or not)."""

    def __init__(self, base: dict) -> None:
        super().__init__(base)
        self.seen: set[str] = set()

    def get(self, key, default=None):  # type: ignore[override]
        self.seen.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.seen.add(key)
        return super().__getitem__(key)

    def __contains__(self, key) -> bool:
        self.seen.add(key)
        return super().__contains__(key)


def _compose_files(case: unittest.TestCase) -> tuple[dict, str]:
    here = Path(__file__).resolve().parents[1]
    if not (here / "docker-compose.yml").exists():
        case.skipTest("docker-compose.yml is not next to the tests here")
    try:
        import yaml
    except ImportError:
        case.skipTest("PyYAML is not installed")

    class Loader(yaml.SafeLoader):
        """Compose's merge tags (!override, !reset) read as the plain value under them."""

    def plain(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> object:
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_scalar(node)

    Loader.add_multi_constructor("!", plain)
    files = {name: yaml.load((here / name).read_text(encoding="utf-8"), Loader=Loader)  # noqa: S506 (SafeLoader)
             for name in ("docker-compose.yml", "docker-compose.hosted.yml", "docker-compose.preview.yml")}
    return files, (here / "README.md").read_text(encoding="utf-8")


def _service_env(doc: dict, service: str) -> dict:
    env = ((doc.get("services") or {}).get(service) or {}).get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    return env


def _readme_settings(readme: str) -> set[str]:
    """The variables in the first column of README.md's "## Settings" table; ATALAIA_QUOTA_<NAME> is each quota."""
    section = readme.split("\n## Settings\n", 1)[1].split("\n## ", 1)[0]
    names: set[str] = set()
    for line in section.splitlines():
        if line.startswith("| `ATALAIA_"):
            names.update(re.findall(r"`(ATALAIA_[A-Z0-9_<>]+)`", line.split(" | ", 1)[0]))
    if "ATALAIA_QUOTA_<NAME>" in names:
        names.discard("ATALAIA_QUOTA_<NAME>")
        names.update(f"ATALAIA_QUOTA_{q.upper()}" for q in QUOTA_DEFAULTS)
    return names


if __name__ == "__main__":
    unittest.main()

