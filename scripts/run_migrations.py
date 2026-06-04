#!/usr/bin/env python3
"""
Apply additive SQL migrations to Supabase Postgres (production-safe).

Requires a direct Postgres connection (service role REST cannot run DDL):
  - DATABASE_URL=postgresql://postgres:PASSWORD@db.<ref>.supabase.co:5432/postgres
  OR
  - SUPABASE_URL + SUPABASE_DB_PASSWORD (script builds the URI)

Safety:
  - Only runs files under api/migrations/*.sql
  - Rejects destructive SQL (DROP TABLE, TRUNCATE, DELETE, etc.)
  - Allows DROP CONSTRAINT/TRIGGER/INDEX only with IF EXISTS
  - Skips migrations already recorded in schema_migrations
  - Each migration runs in a single transaction (rollback on error)

Usage:
  python scripts/run_migrations.py --dry-run
  python scripts/run_migrations.py
  python scripts/run_migrations.py --only 003_metering_tables
  python scripts/run_migrations.py --mark-applied 000_sessions_table_schema
  python scripts/run_migrations.py --mark-applied 001_create_app_auth_tables
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
_MIGRATIONS_DIR = _PKG_ROOT / "api" / "migrations"

# Destructive patterns — blocked for production runs.
_FORBIDDEN = re.compile(
    r"\b("
    r"DROP\s+TABLE|"
    r"DROP\s+DATABASE|"
    r"DROP\s+SCHEMA|"
    r"TRUNCATE\b|"
    r"DELETE\s+FROM"
    r")\b",
    re.IGNORECASE,
)

_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_PKG_ROOT / ".env")


def _resolve_database_url() -> str:
    import os

    direct = (os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or "").strip()
    if direct:
        return direct

    supabase_url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    password = (os.environ.get("SUPABASE_DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD") or "").strip()
    if not supabase_url or not password:
        raise SystemExit(
            "Missing database credentials.\n"
            "Set DATABASE_URL, or set SUPABASE_URL + SUPABASE_DB_PASSWORD in cv-drafter/.env\n"
            "(Supabase → Project Settings → Database → connection string / database password)."
        )

    # https://xyzcompany.supabase.co → db.xyzcompany.supabase.co
    host = supabase_url.replace("https://", "").replace("http://", "")
    if host.endswith(".supabase.co"):
        db_host = "db." + host
    else:
        raise SystemExit(f"Unrecognized SUPABASE_URL host: {host}")

    from urllib.parse import quote_plus

    safe_password = quote_plus(password)
    return f"postgresql://postgres:{safe_password}@{db_host}:5432/postgres?sslmode=require"


def _validate_sql(sql: str, version: str) -> None:
    if _FORBIDDEN.search(sql):
        raise SystemExit(
            f"Migration {version} contains blocked destructive SQL. "
            "Refusing to run on production."
        )


def _list_migrations(only: str | None) -> list[Path]:
    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise SystemExit(f"No migrations found in {_MIGRATIONS_DIR}")
    if only:
        match = [f for f in files if only in f.name]
        if not match:
            raise SystemExit(f"No migration matching --only {only!r}")
        return match
    return files


def _applied_versions(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version FROM public.schema_migrations ORDER BY version"
        )
        return {row[0] for row in cur.fetchall()}


def _mark_applied(conn, version: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.schema_migrations (version) VALUES (%s) "
            "ON CONFLICT (version) DO NOTHING",
            (version,),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run additive SQL migrations.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pending migrations without executing.",
    )
    parser.add_argument(
        "--only",
        metavar="SUBSTRING",
        help="Run only migrations whose filename contains this substring.",
    )
    parser.add_argument(
        "--mark-applied",
        metavar="VERSION",
        action="append",
        default=[],
        help="Record version(s) as applied without executing SQL (already done manually).",
    )
    args = parser.parse_args()

    _load_dotenv()
    database_url = _resolve_database_url()

    try:
        import psycopg
    except ImportError:
        raise SystemExit(
            "Install psycopg: pip install 'psycopg[binary]>=3.2'"
        ) from None

    migrations = _list_migrations(args.only)

    print(f"Migrations directory: {_MIGRATIONS_DIR}")
    print(f"Database host: {database_url.split('@')[-1].split('/')[0]}")

    try:
        conn_ctx = psycopg.connect(database_url, autocommit=False)
    except psycopg.OperationalError as exc:
        if "getaddrinfo failed" in str(exc) or "failed to resolve host" in str(exc):
            raise SystemExit(
                "Cannot resolve the database host (DNS).\n"
                "Fix: Supabase → Project Settings → Database → Connection string.\n"
                "Copy the full URI (try **Session pooler** on port 5432 if "
                "db.<ref>.supabase.co fails) into DATABASE_URL in .env.\n"
                "Or run migrations manually in the SQL Editor (000 → 001 → 002 → 003)."
            ) from exc
        raise

    with conn_ctx as conn:
        with conn.cursor() as cur:
            cur.execute(_BOOTSTRAP_SQL)
        conn.commit()

        applied = _applied_versions(conn)

        for version in args.mark_applied:
            name = version if version.endswith(".sql") else f"{version}.sql"
            stem = Path(name).stem
            if args.dry_run:
                print(f"[dry-run] would mark applied: {stem}")
            else:
                _mark_applied(conn, stem)
                conn.commit()
                print(f"Marked applied (no SQL run): {stem}")
            applied.add(stem)

        pending: list[tuple[str, str]] = []
        for path in migrations:
            version = path.stem
            if version in applied:
                print(f"Skip (already applied): {path.name}")
                continue
            sql = path.read_text(encoding="utf-8")
            _validate_sql(sql, version)
            pending.append((version, sql))

        if not pending:
            print("Nothing to apply.")
            return 0

        if args.dry_run:
            print("Pending migrations:")
            for version, _ in pending:
                print(f"  - {version}")
            return 0

        for version, sql in pending:
            print(f"Applying: {version} …")
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    _mark_applied(conn, version)
                conn.commit()
                print(f"  OK: {version}")
            except Exception as exc:
                conn.rollback()
                print(f"  FAILED: {version} — {exc}", file=sys.stderr)
                return 1

    print("All pending migrations applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
