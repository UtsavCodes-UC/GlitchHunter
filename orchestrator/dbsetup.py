"""Database isolation for uploaded projects: ONE PostgreSQL role + ONE schema per project.
The uploaded app, the attacker and the checks connect as that role, which owns its schema and has no rights anywhere else, so uploaded
code cannot read the demo tables, other projects' tables, other databases' roles, or create schemas.
Needs a server user that may create roles (GH_ADMIN_DATABASE_URL, default GH_DATABASE_URL): `ALTER ROLE <user> CREATEROLE;` run once
as a superuser, or a superuser URL. Nothing is created until a project's setup is first saved/tested."""
import re, secrets, psycopg2
from controller import config

FIX = ("The database user in {var} may not create roles. Run this once as a PostgreSQL superuser (for example in psql as postgres):\n"
       "    ALTER ROLE {user} CREATEROLE;\n"
       "or point GH_ADMIN_DATABASE_URL at a user that has CREATEROLE.")

def names(pid):
    if not re.fullmatch(r"u[0-9a-f]{10}", pid): raise KeyError(pid)
    return f"gh_up_{pid}", f"up_{pid}"

def _admin(cfg):
    c = psycopg2.connect(config.admin_url(cfg)); c.autocommit = True
    return c

def _who(cfg):
    from urllib.parse import urlparse, unquote
    return unquote(urlparse(config.admin_url(cfg)).username or "?")

def provision(cfg, pid):
    """create the project's role and schema (idempotent: an existing role keeps its password). Returns {role, password, schema}"""
    role, schema = names(pid); pw = secrets.token_urlsafe(24); c = _admin(cfg)
    try:
        with c.cursor() as cur:
            cur.execute("select 1 from pg_roles where rolname = %s", (role,))
            if cur.fetchone(): return {"role": role, "password": None, "schema": schema}   # caller already holds the password
            try:
                cur.execute(f"create role {role} login password %s nosuperuser nocreatedb nocreaterole noreplication nobypassrls noinherit connection limit 80", (pw,))
            except psycopg2.errors.InsufficientPrivilege:
                raise RuntimeError(FIX.format(var="GH_ADMIN_DATABASE_URL / GH_DATABASE_URL", user=_who(cfg)))
            try: cur.execute(f"grant {role} to current_user with set true, inherit true")   # PostgreSQL 16+: the creator must be allowed to SET ROLE
            except psycopg2.Error: cur.execute(f"grant {role} to current_user")
            cur.execute(f"create schema {schema} authorization {role}")
            cur.execute(f"alter role {role} set search_path = {schema}")
            cur.execute(f"alter role {role} set statement_timeout = '30s'")
            cur.execute(f"alter role {role} set idle_in_transaction_session_timeout = '15s'")
    finally: c.close()
    return {"role": role, "password": pw, "schema": schema}

def teardown(cfg, pid):
    """terminate the role's sessions, drop its schema and the role. Safe to call when nothing was provisioned."""
    role, schema = names(pid); c = _admin(cfg)
    try:
        with c.cursor() as cur:
            cur.execute("select 1 from pg_roles where rolname = %s", (role,))
            if not cur.fetchone(): return
            try: cur.execute("grant %s to current_user with set true, inherit true" % role)
            except psycopg2.Error: pass
            cur.execute("select pg_terminate_backend(pid) from pg_stat_activity where usename = %s", (role,))
            cur.execute(f"drop schema if exists {schema} cascade"); cur.execute(f"drop owned by {role}"); cur.execute(f"drop role {role}")
    finally: c.close()

def exists(cfg, pid):
    role, _ = names(pid); c = _admin(cfg)
    try:
        with c.cursor() as cur: cur.execute("select 1 from pg_roles where rolname = %s", (role,)); return bool(cur.fetchone())
    finally: c.close()

def drop_objects(cur):
    """empty the connected role's schema (current_schema): tables, views, sequences, types, functions. Used before the schema SQL runs."""
    cur.execute("select current_schema()"); schema = cur.fetchone()[0]
    cur.execute("select c.relkind, c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = %s and c.relkind in ('r','p','v','m','S','f') "
                "and not exists (select 1 from pg_depend d where d.objid = c.oid and d.deptype in ('e','a'))", (schema,))
    kind = {"r": "table", "p": "table", "v": "view", "m": "materialized view", "S": "sequence", "f": "foreign table"}
    for k, n in cur.fetchall(): cur.execute(f'drop {kind[k]} if exists "{schema}"."{n}" cascade')
    cur.execute("select t.typname from pg_type t join pg_namespace n on n.oid = t.typnamespace where n.nspname = %s and t.typtype in ('e','d')", (schema,))
    for (n,) in cur.fetchall(): cur.execute(f'drop type if exists "{schema}"."{n}" cascade')
    cur.execute("select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = %s", (schema,))
    for (f,) in cur.fetchall(): cur.execute(f"drop routine if exists {f} cascade")
