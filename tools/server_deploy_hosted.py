#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The hosted hub's deployment test (Phase 4 follow-up, decisions FU4-*):
`python3 tools/docker_server.py deploy-hosted`.

Runs the real hosted deployment (server/setup.sh --hosted, server/docker-compose.yml
with server/docker-compose.hosted.yml, Caddyfile.hosted, the tls-ask service,
backup.sh and restore.sh's hosted paths) on this machine in Docker, with
Caddy's own CA issuing on demand instead of a public CA (ATALAIA_TLS=internal)
and the hub's domain hub.test, ports on 127.0.0.1 only:

 1. setup.sh --hosted writes the env file (mode 0600, six secrets, never
    printed; no public URL; COMPOSE_FILE), keeps it on a second run, and
    refuses to turn a hosted env file into a single-field one or back;
 2. setup.sh --hosted starts the hub: the two roles (no superuser, no
    BYPASSRLS), the registry, the stack; the operator's commands (`docker
    compose run --rm hub hosted ...`, the owner role) make three fields and
    suspend one; the server's connections are the server role's;
 3. the ask endpoint says yes only for an active field's name (asked from
    Caddy's container); tests/deploy_probe_hosted.py, in a container on the
    public network only, checks that each field's name gets its own
    certificate and serves its own field (page, API key, WebSocket sync) and
    nothing of the other, that an unknown field, a suspended one and the hub's
    own name get no certificate, that an unknown field's Host gets 404, and
    that the database, the server and the ask endpoint cannot be reached;
 4. isolation: `hosted check` passes; as the server role, with each field's
    setting and with none, every table of every field is read: only the
    field's own rows are seen; TRUNCATE, the hub's audit log, the registry
    and dropping FORCE ROW LEVEL SECURITY are refused;
 5. backup.sh makes an encrypted backup; restore.sh refuses a damaged one, a
    single-field server's backup and (into a single-field env file) the
    hub's, each with nothing changed;
 6. everything is deleted (`down --volumes`), setup.sh --hosted starts a
    fresh, empty hub, restore.sh restores the backup, and every table of
    every field, the registry and the hub's audit log match their digests
    from before, ownership, grants, policies and the roles match exactly,
    the isolation checks of step 4 pass again and the probe finds both
    fields' data through Caddy, with new certificates from a new CA.
The hub runs with the remote ATAK relay on (Phase 4 follow-up FU5): after step 3
and again after the restore, the operator's `atak issue --field SLUG` (in the
server's container) makes a data package per field, the published relay port
answers TLS with the hub's relay certificate (*.DOMAIN), and
tests/deploy_probe_atak.py checks that each field's device gets its own
field's events and never the other's (the certificate's field picks the
tenant).
Everything it made is removed at the end, whatever the result.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server_deploy import SERVER, DeployFailure, Deployment, expect, say  # noqa: E402

DOMAIN = "hub.test"
FIELDS = (("campo-a", "Campo Alfa"), ("campo-b", "Campo Bravo"))
SUSPENDED = ("campo-c", "Campo Charlie")
SECRETS = ("POSTGRES_PASSWORD", "ATALAIA_OWNER_DB_PASSWORD", "ATALAIA_APP_DB_PASSWORD", "ATALAIA_SECRET_KEY",
           "ATALAIA_METRICS_TOKEN", "ATALAIA_BACKUP_KEY")
APP, OWNER = "atalaia_app", "atalaia_owner"
REFUSED = (f"nobody.{DOMAIN}", f"{SUSPENDED[0]}.{DOMAIN}", DOMAIN)

# Every table of every field, the registry and the hub's audit log up to a cut-off (starting the restored hub
# writes its own `tenant_migrate` entries after it), as digests: equal before the backup and after the restore.
FINGERPRINT_SQL = r"""
DO $$ BEGIN CREATE TEMP TABLE fp (name text, rows bigint, digest text); END $$;
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT schemaname, tablename FROM pg_tables
            WHERE schemaname LIKE 'field\_%' OR schemaname = 'public' ORDER BY 1, 2 LOOP
    EXECUTE format('INSERT INTO fp SELECT %L, count(*), md5(coalesce(string_agg(x::text, %L ORDER BY x::text), %L))
                    FROM %I.%I x %s', t.schemaname || '.' || t.tablename, E'\n', '', t.schemaname, t.tablename,
                   CASE WHEN t.schemaname = 'public' AND t.tablename = 'atalaia_hub_audit'
                        THEN 'WHERE x.id <= CUTOFF' ELSE '' END);
  END LOOP;
END $$;
SELECT name || ' ' || rows || ' ' || digest FROM fp ORDER BY name;
"""

# Who owns what, every grant, every policy, row-level security and the roles' attributes: equal after the restore.
# Privileges are the effective ones: an ACL that is just the default (pg_dump leaves it out) counts as the default.
PRIVILEGES_SQL = r"""
WITH acl AS (
  SELECT oid, (SELECT string_agg(x, ',' ORDER BY x) FROM (
     SELECT pg_get_userbyid(a.grantee) || ':' || a.privilege_type || ':' || pg_get_userbyid(a.grantor) AS x
       FROM aclexplode(coalesce(c.relacl,
                                acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))) a
     ) s) AS acl FROM pg_class c)
SELECT line FROM (
  SELECT 'rel ' || n.nspname || '.' || c.relname || ' ' || c.relkind::text || ' owner=' || pg_get_userbyid(c.relowner)
         || ' rls=' || c.relrowsecurity || ' force=' || c.relforcerowsecurity || ' acl=' || coalesce(acl.acl, '-')
         AS line
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN acl ON acl.oid = c.oid
   WHERE (n.nspname LIKE 'field\_%' OR n.nspname = 'public') AND c.relkind IN ('r', 'p', 'S', 'v', 'm')
  UNION ALL
  SELECT 'schema ' || nspname || ' owner=' || pg_get_userbyid(nspowner) || ' acl=' || coalesce((
           SELECT string_agg(x, ',' ORDER BY x) FROM (
             SELECT pg_get_userbyid(a.grantee) || ':' || a.privilege_type AS x
               FROM aclexplode(coalesce(nspacl, acldefault('n', nspowner))) a) s), '-')
    FROM pg_namespace WHERE nspname LIKE 'field\_%' OR nspname = 'public'
  UNION ALL
  SELECT 'policy ' || schemaname || '.' || tablename || ' ' || policyname || ' ' || permissive || ' '
         || roles::text || ' ' || cmd || ' ' || coalesce(qual, '') || ' ' || coalesce(with_check, '')
    FROM pg_policies
  UNION ALL
  SELECT 'role ' || rolname || ' super=' || rolsuper || ' bypassrls=' || rolbypassrls || ' login=' || rolcanlogin
         || ' inherit=' || rolinherit || ' createdb=' || rolcreatedb || ' createrole=' || rolcreaterole
         || ' replication=' || rolreplication || ' member_of=' || coalesce((
           SELECT string_agg(pg_get_userbyid(m.roleid), ',' ORDER BY 1) FROM pg_auth_members m
            WHERE m.member = r.oid), '-')
    FROM pg_roles r WHERE rolname IN ('atalaia_owner', 'atalaia_app') OR rolname LIKE 'atalaia\_t\_%'
  UNION ALL
  SELECT 'database atalaia owner=' || pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'atalaia'
) lines ORDER BY line;
"""


class HostedDeployment(Deployment):
    files = ("docker-compose.yml", "docker-compose.hosted.yml")
    name = "deploy-hosted"

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        self.keys: dict[str, str] = {}
        self.audit_cutoff = 0

    # --- 1 and 2: setup.sh --hosted -------------------------------------------------------------------

    def setup(self) -> None:
        say("1. setup.sh --hosted")
        self.run(["sh", str(SERVER / "setup.sh"), DOMAIN, "--hosted", "--no-start"])
        mode = stat.S_IMODE(self.env_file.stat().st_mode)
        expect(mode == 0o600, f"the env file is mode 0600 ({oct(mode)})")
        values = dict(line.split("=", 1) for line in self.env_file.read_text().splitlines()
                      if "=" in line and not line.startswith("#"))
        for name in SECRETS:
            expect(bool(re.fullmatch(r"[0-9a-f]{64}", values.get(name, ""))), f"{name}: 32 random bytes")
        self.secret_values = [values[name] for name in SECRETS]
        expect(len(set(self.secret_values)) == len(SECRETS), "every secret is different")
        expect(values.get("ATALAIA_HOSTED") == "on" and "ATALAIA_PUBLIC_URL" not in values
               and values.get("COMPOSE_FILE") == "docker-compose.yml:docker-compose.hosted.yml",
               "ATALAIA_HOSTED=on, no public URL, COMPOSE_FILE names both Compose files")
        before = self.env_file.read_bytes()
        self.env_file.chmod(0o644)
        self.run(["sh", str(SERVER / "setup.sh"), DOMAIN, "--hosted", "--no-start"])
        expect(self.env_file.read_bytes() == before, "run again, setup.sh keeps every value")
        expect(stat.S_IMODE(self.env_file.stat().st_mode) == 0o600, "and puts the mode back to 0600")
        refused = self.run(["sh", str(SERVER / "setup.sh"), DOMAIN, "--no-start"], check=False)
        expect(refused.returncode == 1 and self.env_file.read_bytes() == before,
               "setup.sh refuses to make the hub's env file a single-field server's")
        single = self.work / "single.env"
        env = {**self.env, "ATALAIA_ENV_FILE": str(single)}
        self.run(["sh", str(SERVER / "setup.sh"), "campo.test", "--no-start"], env=env)
        single_before = single.read_bytes()
        refused = self.run(["sh", str(SERVER / "setup.sh"), "campo.test", "--hosted", "--no-start"], env=env,
                           check=False)
        expect(refused.returncode == 1 and single.read_bytes() == single_before,
               "and a single-field server's env file a hub's")
        single.unlink()

    def start(self) -> None:
        """setup.sh --hosted: the roles, the registry and the stack (other ports if Windows holds these)."""
        for _ in range(3):
            done = self.run(["sh", str(SERVER / "setup.sh"), DOMAIN, "--hosted"], check=False)
            if done.returncode == 0:
                # Every container's log, PostgreSQL's included (the roles' passwords went to it): run() fails
                # on any secret in the output.
                self.dc("logs", "--no-color", quiet=True)
                say("ok   no secret in any container's log")
                return
            if b"ports are not available" not in done.stdout + done.stderr:
                break
            self.dc("down", "--remove-orphans", check=False, quiet=True)
            self.new_ports()
        raise DeployFailure("setup.sh --hosted could not start the hub")

    def hub(self, *args: str, check: bool = True) -> str:
        """An operator's command as the documented recipe runs it: docker compose run --rm hub hosted ..."""
        return self.dc("run", "--rm", "-T", "hub", "hosted", *args, check=check).stdout.decode()

    def roles(self) -> None:
        rows = self.sql("SELECT rolname || ' ' || rolsuper || ' ' || rolbypassrls || ' ' || rolcanlogin FROM pg_roles "
                        f"WHERE rolname IN ('{OWNER}', '{APP}') ORDER BY 1").splitlines()
        expect(rows == [f"{APP} false false true", f"{OWNER} false false true"],
               f"two login roles, no superuser, no BYPASSRLS: {rows}")
        expect(self.sql("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'atalaia'") == OWNER,
               "the database belongs to the owner role")

    def operator(self) -> None:
        say("2. the operator's commands (docker compose run --rm hub hosted ..., the owner role)")
        for slug, name in (*FIELDS, SUSPENDED):
            out = self.hub("create", slug, "--name", name, "--actor", "deploy-test")
            expect(f"Field {slug} created" in out, f"hosted create {slug}")
        self.hub("suspend", SUSPENDED[0], "--reason", "deployment test", "--actor", "deploy-test")
        listed = self.hub("list")
        expect(all(re.search(rf"^{s}\t{st}\t", listed, re.M) for s, st in
                   (("campo-a", "active"), ("campo-b", "active"), ("campo-c", "suspended"))),
               "hosted list: two active fields and a suspended one")
        for slug, _ in FIELDS:
            key = secrets.token_urlsafe(32)
            self.secret_values.append(key)
            self.keys[slug] = key
            schema = "field_" + slug.replace("-", "_")
            digest = hashlib.sha256(key.encode()).hexdigest()
            # A controller's key, and the public page on (as the field's administrator would set them).
            self.sql(f"INSERT INTO {schema}.field_api_keys (field_id, key_sha256) SELECT id, '{digest}' "
                     f"FROM {schema}.fields; UPDATE {schema}.fields SET public_page = true")

    def server_connects_as_its_role(self) -> None:
        users = self.sql("SELECT string_agg(DISTINCT usename, ',' ORDER BY usename) FROM pg_stat_activity "
                         "WHERE datname = 'atalaia' AND backend_type = 'client backend' AND pid <> pg_backend_pid()")
        expect(users == APP, f"the server and the ask endpoint connect as {APP} only (found {users})")

    # --- 3: the ask endpoint and the probe -----------------------------------------------------------

    def ask_endpoint(self) -> None:
        say("3. the ask endpoint (from Caddy's container) and the probe on the public network")
        for name, yes in ((f"campo-a.{DOMAIN}", True), (f"campo-b.{DOMAIN}", True), (f"CAMPO-A.{DOMAIN}", True),
                          (f"{SUSPENDED[0]}.{DOMAIN}", False), (f"nobody.{DOMAIN}", False), (DOMAIN, False),
                          (f"x.campo-a.{DOMAIN}", False), (f"campo-a.{DOMAIN}.example.com", False)):
            done = self.dc("exec", "-T", "caddy", "wget", "-q", "-O", "-", f"http://tls-ask:8001/check?domain={name}",
                           check=False, quiet=True)
            expect((done.returncode == 0) == yes, f"ask {name}: {'yes' if yes else 'no'}")

    def probe(self, phase: str, key: str = "") -> None:
        ca = self.work / "root.crt"
        if ca.exists():
            ca.unlink()
        for _ in range(30):
            if self.dc("cp", "caddy:/data/caddy/pki/authorities/local/root.crt", str(ca), check=False,
                       quiet=True).returncode == 0:
                break
            time.sleep(1)
        expect(ca.exists(), "Caddy's local root certificate")
        ca.chmod(0o644)
        closed = ",".join((f"{self.container_ip('postgres', 'db')}:5432", f"{self.container_ip('server', 'app')}:8000",
                           f"{self.container_ip('tls-ask', 'app')}:8001"))
        caddy = self.container_ip("caddy", "edge")
        hosts = [f"{slug}.{DOMAIN}" for slug, _ in FIELDS] + list(REFUSED)
        fields = ";".join(f"{slug}={self.keys[slug]}={name}" for slug, name in FIELDS)
        env = {**self.env, "ATALAIA_PROBE_FIELDS": fields}
        self.run(["docker", "run", "--rm", "--network", f"{self.project}_edge",
                  *[arg for host in hosts for arg in ("--add-host", f"{host}:{caddy}")],
                  "-v", f"{ca}:/ca.crt:ro", "-e", "ATALAIA_PROBE_FIELDS", "-e", f"ATALAIA_PROBE_DOMAIN={DOMAIN}",
                  "-e", "ATALAIA_PROBE_CA=/ca.crt", "-e", f"ATALAIA_PROBE_CLOSED={closed}",
                  "-e", f"ATALAIA_PROBE_REFUSED={','.join(REFUSED)}",
                  self.test_image, "python", "-m", "tests.deploy_probe_hosted", phase], env=env)

    # --- 4: isolation --------------------------------------------------------------------------------

    def field_tables(self) -> list[str]:
        return self.sql(r"SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname LIKE 'field\_%' "
                        "AND tablename <> 'alembic_version' ORDER BY 1").splitlines()

    def isolation(self) -> str:
        """Every check of the fields' isolation; returns the ownership and privileges, to compare."""
        out = self.hub("check")
        expect("Hub check passed: 3 fields" in out, "hosted check: ownership, forced RLS, policies, grants")
        tables = self.field_tables()
        schemas = sorted({t.split(".")[0] for t in tables})
        expect(len(schemas) == 3 and len(tables) >= 90, f"{len(tables)} tables in {len(schemas)} field schemas")
        weak = self.sql(r"SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        r"WHERE n.nspname LIKE 'field\_%' AND c.relkind IN ('r', 'p') "
                        "AND c.relname <> 'alembic_version' "
                        "AND NOT (c.relrowsecurity AND c.relforcerowsecurity)")
        expect(weak == "0", "row-level security is enabled and forced on every field table")
        truth = dict(line.split("|") for line in self.sql(
            "\n".join(f"SELECT '{t}|' || count(*) FROM {t};" for t in tables)).splitlines())
        for schema in schemas:
            expect(int(truth[f"{schema}.fields"]) == 1, f"{schema} has its field")
        for slug, _ in FIELDS:
            schema = "field_" + slug.replace("-", "_")
            expect(int(truth[f"{schema}.game_events"]) == 2, f"{schema} has its two synced events")
        roles = dict(line.split("|") for line in self.sql(
            "SELECT schema_name || '|' || role_name FROM public.atalaia_tenants").splitlines())
        expect(len(roles) == 3 and all(r.startswith("atalaia_t_") for r in roles.values()),
               "every field has a database role of its own (atalaia_t_<field id>)")
        for schema in schemas:  # each field's role: its own rows only, whatever the setting, no other field at all
            own = [t for t in tables if t.startswith(schema + ".")]
            for setting in (schema, ""):
                script = (f"BEGIN; SELECT set_config('atalaia.tenant', '{setting}', true); "
                          f"SET LOCAL ROLE {roles[schema]};\n" + "\n".join(f"SELECT '{t}|' || count(*) FROM {t};" for t in own) + "\nROLLBACK;")
                seen = dict(line.split("|") for line in self.sql(script).splitlines() if "|" in line)
                wrong = [t for t in own if seen.get(t) != (truth[t] if setting else "0")]
                what = "its own setting" if setting else "no setting"
                expect(len(seen) == len(own) and not wrong,
                       f"as the role of {schema} with {what}: {'its own rows only' if setting else 'nothing'}, in "
                       f"every table ({len(own)}){': ' + ', '.join(wrong[:5]) if wrong else ''}")
            other = next(x for x in schemas if x != schema)
            for statement, why in ((f"SELECT count(*) FROM {other}.users", "reading another field's table"),
                                   (f"INSERT INTO {other}.users (username, password_hash) VALUES ('x', 'y')",
                                    "writing another field's table"),
                                   (f"SELECT set_config('atalaia.tenant', '{other}', true)",
                                    "calling set_config (it could name another field or role)")):
                done = self.dc("exec", "-T", "postgres", "psql", "-U", "atalaia", "-d", "atalaia", "-v",
                               "ON_ERROR_STOP=1", "-q", "-At",
                               input=f"BEGIN; SET LOCAL ROLE {roles[schema]}; {statement}; ROLLBACK;".encode(),
                               check=False, quiet=True)
                expect(done.returncode != 0 and "permission denied" in done.stderr.decode(),
                       f"as the role of {schema}, {why} is refused")
        for schema in schemas:  # the server's login role holds no field's table itself
            done = self.dc("exec", "-T", "postgres", "psql", "-U", "atalaia", "-d", "atalaia", "-v", "ON_ERROR_STOP=1",
                           "-q", "-At", input=f"BEGIN; SET LOCAL ROLE {APP}; SELECT count(*) FROM {schema}.users; "
                                              "ROLLBACK;".encode(), check=False, quiet=True)
            expect(done.returncode != 0 and "permission denied" in done.stderr.decode(),
                   f"as {APP}, {schema}.users is refused (only the field's role may read it)")
        for statement, why in (("TRUNCATE field_campo_b.users", "TRUNCATE (which RLS does not cover)"),
                               ("SELECT count(*) FROM public.atalaia_hub_audit", "reading the hub's audit log"),
                               ("UPDATE public.atalaia_tenants SET status = 'active'", "changing the registry"),
                               ("ALTER TABLE field_campo_a.users NO FORCE ROW LEVEL SECURITY", "dropping FORCE"),
                               ("SELECT count(*) FROM field_campo_a.alembic_version", "alembic_version"),
                               ("CREATE TABLE field_campo_a.extra (id integer)", "a new table in a field"),
                               ("SELECT * FROM public.atalaia_share_members", "the sharing's tables")):
            done = self.dc("exec", "-T", "postgres", "psql", "-U", "atalaia", "-d", "atalaia", "-v", "ON_ERROR_STOP=1",
                           "-q", "-At", input=f"BEGIN; SET LOCAL ROLE {APP}; {statement}; ROLLBACK;".encode(),
                           check=False, quiet=True)
            err = done.stderr.decode()
            expect(done.returncode != 0 and ("permission denied" in err or "must be owner" in err),
                   f"as {APP}, {why} is refused")
        members = self.sql(f"SELECT string_agg(g.rolname, ',' ORDER BY g.rolname) FROM pg_auth_members m "
                           f"JOIN pg_roles r ON r.oid = m.member JOIN pg_roles g ON g.oid = m.roleid "
                           f"WHERE r.rolname = '{APP}'")
        expect(members == ",".join(sorted(roles.values())),
               f"{APP} is a member of the fields' own roles only (it cannot become the owner)")
        expect(self.sql("SELECT count(*) FROM pg_proc p, aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a "
                        "WHERE p.proname = 'set_config' AND a.grantee = 0") == "0",
               "set_config can be called by the owner and the server's role only (hosted-roles.sh)")
        return self.sql(PRIVILEGES_SQL)

    # --- 5 and 6: backup and restore -----------------------------------------------------------------

    def fingerprint(self) -> str:
        return self.sql(FINGERPRINT_SQL.replace("CUTOFF", str(int(self.audit_cutoff))))

    def sealed(self, dump: bytes, name: str) -> Path:
        path = self.work / name
        done = self.dc("run", "--rm", "-T", "backup-crypt", "seal", input=dump, quiet=True)
        path.write_bytes(done.stdout)
        return path

    def refused_restores(self, good: Path) -> None:
        super().refused_restores(good)  # a damaged backup, no --yes
        expect(b"Campo Alfa" not in good.read_bytes() and b"field_campo_a" not in good.read_bytes(),
               "the hub's backup is encrypted (no field name or schema in clear)")
        fingerprint = self.fingerprint()
        # A single-field server's backup (a database with public.fields), sealed with this hub's key.
        self.sql("CREATE DATABASE single_mode_check", db="postgres")
        try:
            self.sql("CREATE TABLE public.fields (id integer)", db="single_mode_check")
            dump = self.dc("exec", "-T", "postgres", "pg_dump", "-U", "atalaia", "-d", "single_mode_check", "-Fc",
                           quiet=True).stdout
        finally:
            self.sql("DROP DATABASE single_mode_check", db="postgres")
        single = self.sealed(dump, "single.backup")
        done = self.run(["sh", str(SERVER / "restore.sh"), str(single), "--yes"], check=False)
        expect(done.returncode != 0 and b"single-field server's backup" in done.stderr
               and b"nothing was changed" in done.stderr, "a single-field server's backup is refused by the hub")
        # The hub's backup into a single-field env file (the same machine, the same key).
        single_env = self.work / "single.env"
        single_env.write_text("".join(line + "\n" for line in self.env_file.read_text().splitlines()
                                      if not line.startswith(("ATALAIA_HOSTED=", "COMPOSE_FILE="))))
        single_env.chmod(0o600)
        done = self.run(["sh", str(SERVER / "restore.sh"), str(good), "--yes"], check=False,
                        env={**self.env, "ATALAIA_ENV_FILE": str(single_env)})
        expect(done.returncode != 0 and b"hosted hub's backup" in done.stderr and b"nothing was changed" in done.stderr,
               "the hub's backup is refused by a single-field env file")
        single_env.unlink()
        expect(self.fingerprint() == fingerprint, "and the hub is untouched")
        out = self.hub("list")
        expect("campo-a\tactive" in out, "the hub still serves its fields")

    def restore_hub(self, backup: Path, expected: str, privileges: str) -> None:
        say("6. a fresh hub (setup.sh --hosted), then restore.sh")
        self.dc("down", "--volumes", "--remove-orphans")
        self.start()
        self.roles()
        expect(self.hub("list").strip() == "", "the fresh hub has no field")
        self.run(["sh", str(SERVER / "restore.sh"), str(backup), "--yes"])
        got = self.fingerprint()
        expect(got == expected, f"every table of every field, the registry and the hub's audit log match "
                                f"({len(expected.splitlines())} tables)")
        expect(self.sql("SELECT count(*) FROM public.atalaia_hub_audit WHERE action = 'tenant_migrate' "
                        f"AND id > {int(self.audit_cutoff)}") == "6",
               "restoring migrated every field to give it its role and grants back, and starting the hub did again")
        say("   the isolation after the restore")
        after = self.isolation()
        changed = sorted(set(privileges.splitlines()) ^ set(after.splitlines()))
        expect(after == privileges, f"ownership, grants, policies and roles exactly as before "
                                    f"({len(privileges.splitlines())} lines){': ' if changed else ''}"
                                    + " | ".join(changed[:6]))
        self.roles()


def run(suffix: str, server_image: str, test_image: str) -> int:
    for tool in ("sh", "docker"):
        if shutil.which(tool) is None:
            say(f"{tool} is not installed")
            return 1
    work = Path(tempfile.mkdtemp(prefix="atalaia-deploy-hosted-"))
    d = HostedDeployment(suffix, server_image, test_image, work)
    try:
        d.setup()
        say("2. setup.sh --hosted starts the hub")
        d.start()
        d.roles()
        d.operator()
        d.ask_endpoint()
        d.probe("before")
        say("   the remote ATAK relay: one device per field, each field's events to its own device only")
        for slug, _ in FIELDS:
            d.atak_enrol(slug, f"{slug}.{DOMAIN}", d.keys[slug])
        d.atak_published(f"*.{DOMAIN}")
        d.atak_probe([f"{slug}.{DOMAIN}" for slug, _ in FIELDS])
        d.server_connects_as_its_role()
        d.one_worker()
        say("4. the isolation")
        privileges = d.isolation()
        d.audit_cutoff = int(d.sql("SELECT max(id) FROM public.atalaia_hub_audit"))
        expected = d.fingerprint()
        say("5. backup.sh")
        backup = d.backup()
        d.refused_restores(backup)
        d.restore_hub(backup, expected, privileges)
        d.ask_endpoint()
        d.probe("after")
        d.atak_published(f"*.{DOMAIN}")
        d.atak_probe([f"{slug}.{DOMAIN}" for slug, _ in FIELDS])
        d.server_connects_as_its_role()
        say("every hosted deployment check passed (Caddy's local CA on this machine; not a real domain, "
            "a real DNS wildcard or a public certificate)")
        return 0
    except DeployFailure as exc:
        say(f"failed: {exc}")
        d.dc("logs", "--no-color", "--tail", "60", check=False)
        return 1
    finally:
        d.down()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sfx = os.environ.get("ATALAIA_VOLUME_SUFFIX", "")
    sys.exit(run(sfx, f"atalaia-server{sfx}".lower(), f"atalaia-server-test{sfx}".lower()))
