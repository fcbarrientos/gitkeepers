"""Counts for the home dashboard. Follow-up states use the same rules as the follow-up list."""
import sqlite3

from core import clock, sync_state
from core.assist import ai_status
from core.follow_ups import STATE_FILTERS
from core.supplies import list_items


def _count(conn: sqlite3.Connection, sql: str, *params) -> int:
    return conn.execute(sql, params).fetchone()[0]


def summary(conn: sqlite3.Connection) -> dict:
    today = clock.today().isoformat()
    return {
        "follow_ups": {
            state: _count(conn, f"SELECT count(*) FROM follow_ups f WHERE {STATE_FILTERS[state]}", today)
            for state in ("overdue", "due", "upcoming")
        },
        "visits_today": _count(conn, "SELECT count(*) FROM visits WHERE visit_date = ?", today),
        "drafts": _count(conn, "SELECT count(*) FROM visits WHERE status = 'draft'"),
        "households": _count(conn, "SELECT count(*) FROM households"),
        "patients": _count(conn, "SELECT count(*) FROM patients"),
        "referral_flags_open": _count(conn, "SELECT count(*) FROM referral_flags WHERE status = 'open'"),
        "low_stock": sum(1 for item in list_items(conn, include_inactive=False) if item["low"]),
        "unsynced": sync_state.unsynced_count(conn),
        "ai": ai_status(),
    }
