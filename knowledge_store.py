"""
The Domain Knowledge Store, per AGENT_INSTRUCTIONS.md Section 11.

This is genuinely new: LangGraph's PostgresSaver (already set up in
graph.py) only stores run *checkpoints* -- it has no idea what a
"confirmed domain rule" is. This module adds a second, small table in
the same Postgres database for that purpose. Same database, different
job -- one instance of Postgres can hold both.
"""

import os
import psycopg

DATABASE_URL = os.environ["QA_FRAMEWORK_DATABASE_URL"]


def setup():
    """Creates the table if it doesn't exist yet. Safe to call every run."""
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS domain_rules (
                id SERIAL PRIMARY KEY,
                statement TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed',  -- 'confirmed' | 'superseded'
                confirmed_by_run_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        conn.commit()


def get_confirmed_rules() -> list[str]:
    """Only ever returns currently-confirmed rules -- superseded ones are
    excluded, but never deleted, so the history stays intact per Section 11."""
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT statement FROM domain_rules WHERE status = 'confirmed' ORDER BY created_at"
        ).fetchall()
        return [r[0] for r in rows]


def add_confirmed_rule(statement: str, run_id: str) -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            "INSERT INTO domain_rules (statement, status, confirmed_by_run_id) VALUES (%s, 'confirmed', %s)",
            (statement, run_id),
        )
        conn.commit()


def supersede_rule(rule_id: int) -> None:
    """Marks a rule as no longer current without deleting it -- Section 11
    requires history to stay traceable, never silently regenerated."""
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("UPDATE domain_rules SET status = 'superseded' WHERE id = %s", (rule_id,))
        conn.commit()
