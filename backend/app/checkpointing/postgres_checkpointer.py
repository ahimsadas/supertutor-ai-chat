from __future__ import annotations

from typing import Dict, List

from contextlib import contextmanager

from ..core.config import get_settings


# Lazy import helpers to avoid import-time failures if deps aren't installed yet
def _import_postgres_saver():
    from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore

    return PostgresSaver


def _require_db_uri() -> str:
    settings = get_settings()
    db_uri = settings.SUPABASE_DB_URL
    if not db_uri:
        raise RuntimeError(
            "Missing required env var: SUPABASE_DB_URL (Postgres connection string)"
        )
    return db_uri


def get_checkpointer():
    """Return a PostgresSaver factory/instance for LangGraph checkpointing.

    This does not open a network/DB connection until used (e.g., as a context
    manager). Callers may use:

        with get_checkpointer().from_conn_string(db_uri) as cp:
            ...

    Or simply call ensure_checkpointer_setup() for one-time setup.
    """
    PostgresSaver = _import_postgres_saver()
    # Return the class itself so callers can construct with different lifecycles
    return PostgresSaver


def ensure_checkpointer_setup() -> Dict[str, bool]:
    """Ensure the LangGraph Postgres checkpoint tables are created.

    Creates tables on first run by invoking PostgresSaver.setup(). Safe to call
    multiple times.
    """
    PostgresSaver = _import_postgres_saver()
    db_uri = _require_db_uri()
    # Use context manager per library guidance
    with PostgresSaver.from_conn_string(db_uri) as cp:
        cp.setup()
    return {"initialized": True}


def inspect_checkpoint_tables() -> Dict[str, List[str]]:
    """Return a list of existing checkpoint-related tables in the public schema.

    This does not expose credentials; it only lists table names starting with
    'checkpoint'.
    """
    import psycopg  # type: ignore
    from psycopg.rows import dict_row  # type: ignore

    db_uri = _require_db_uri()
    tables: List[str] = []
    with psycopg.connect(db_uri, autocommit=True, row_factory=dict_row) as conn:  # type: ignore
        with conn.cursor() as cur:  # type: ignore
            cur.execute(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname='public' AND tablename LIKE 'checkpoint%';
                """
            )
            rows = cur.fetchall()
            tables = [r["tablename"] for r in rows]
    return {"tables": tables}
