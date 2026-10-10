"""Weekly and monthly summaries, and AI-drafted program-needs text for professional review.

The model only ever sees aggregated counts: no names, notes or record IDs.
"""
import json
import sqlite3
import uuid
from datetime import date, timedelta

from core import clock, sync_state
from core.assist import MODEL_LOCK, AIUnavailable
from core.errors import ApiError
from core.extraction import strip_think


def period_bounds(period: str, day: date) -> tuple[date, date]:
    if period == "week":
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=6)
    start = day.replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start, next_month - timedelta(days=1)


def _count(conn, sql: str, *params) -> int:
    return conn.execute(sql, params).fetchone()[0]


def _figures(conn: sqlite3.Connection, start: date, end: date) -> dict:
    s, e = start.isoformat(), end.isoformat()
    by_form = {row[0]: row[1] for row in conn.execute(
        "SELECT form_type, count(*) FROM visits WHERE visit_date BETWEEN ? AND ? GROUP BY form_type ORDER BY form_type",
        (s, e))}
    # Grouped by the rule that raised the flag, never by typed text (which can contain names).
    by_reason = {row[0]: row[1] for row in conn.execute(
        "SELECT COALESCE(f.reason_en, 'manual') AS reason, count(*) FROM referrals r "
        "LEFT JOIN referral_flags f ON f.id = r.flag_id WHERE date(r.created_at, 'localtime') BETWEEN ? AND ? "
        "GROUP BY reason ORDER BY count(*) DESC, reason", (s, e))}
    # Overdue as of the period end (or today, for the current period), whatever happened later.
    cutoff = min(end + timedelta(days=1), clock.today()).isoformat()
    supplies = [dict(row) for row in conn.execute(
        "SELECT i.name, i.unit, "
        "COALESCE(sum(CASE WHEN m.kind = 'received' THEN m.quantity END), 0) AS received, "
        "COALESCE(-sum(CASE WHEN m.kind = 'distributed' THEN m.quantity END), 0) AS distributed "
        "FROM supply_movements m JOIN supply_items i ON i.id = m.item_id WHERE m.movement_date BETWEEN ? AND ? "
        "GROUP BY i.id ORDER BY i.name COLLATE NOCASE", (s, e))]
    low_items = [row[0] for row in conn.execute(
        "SELECT i.name FROM supply_items i WHERE i.active = 1 AND COALESCE((SELECT sum(m.quantity) "
        "FROM supply_movements m WHERE m.item_id = i.id AND m.movement_date <= ?), 0) <= i.low_stock_threshold "
        "ORDER BY i.name COLLATE NOCASE", (e,))]
    return {
        "start": s,
        "end": e,
        "visits": {
            "total": sum(by_form.values()),
            "final": _count(conn, "SELECT count(*) FROM visits WHERE status = 'final' AND visit_date BETWEEN ? AND ?", s, e),
            "by_form": by_form,
        },
        "new_households": _count(conn, "SELECT count(*) FROM households WHERE date(created_at, 'localtime') BETWEEN ? AND ?", s, e),
        "new_patients": _count(conn, "SELECT count(*) FROM patients WHERE date(created_at, 'localtime') BETWEEN ? AND ?", s, e),
        "follow_ups_completed": _count(conn, "SELECT count(*) FROM follow_ups WHERE status = 'completed' "
                                             "AND date(completed_at, 'localtime') BETWEEN ? AND ?", s, e),
        "follow_ups_overdue": _count(conn, "SELECT count(*) FROM follow_ups WHERE due_date < ? AND (status = 'scheduled' "
                                           "OR (status = 'completed' AND date(completed_at, 'localtime') >= ?))",
                                     cutoff, cutoff),
        "referral_flags": _count(conn, "SELECT count(*) FROM referral_flags WHERE date(created_at, 'localtime') BETWEEN ? AND ?", s, e),
        "referrals_issued": _count(conn, "SELECT count(*) FROM referrals WHERE date(created_at, 'localtime') BETWEEN ? AND ?", s, e),
        "referrals_by_reason": by_reason,
        "supplies": supplies,
        "low_stock_items": low_items,
    }


def summary(conn, period: str, day: date) -> dict:
    start, end = period_bounds(period, day)
    previous_start, previous_end = period_bounds(period, start - timedelta(days=1))
    return {
        "period": period,
        "current": _figures(conn, start, end),
        "previous": _figures(conn, previous_start, previous_end),
        "unsynced_records": sync_state.unsynced_count(conn),
    }


def draft_prompt(report: dict) -> str:
    figures = {key: report[key] for key in ("period", "current", "previous")}
    return (
        "You support a barangay health team in the rural Philippines. Using ONLY the aggregated figures below, "
        "write a short draft (at most 150 words, plain sentences) of possible community health program and "
        "service needs the team could look into, and name the figures that support each point. This is a draft "
        "for professional review: do not diagnose anyone, do not make clinical decisions, and do not decide how "
        "resources are allocated.\n\nFigures (JSON):\n"
        f"{json.dumps(figures, ensure_ascii=False)}\n/no_think"
    )


DRAFT_SELECT = (
    "SELECT id, period, start_date, end_date, figures_json, text, status, model, created_by, approved_by, "
    "created_at, updated_at FROM report_drafts"
)


def _draft(row: sqlite3.Row) -> dict:
    draft = dict(row)
    draft["figures"] = json.loads(draft.pop("figures_json"))
    return draft


def get_draft(conn, draft_id: str) -> dict | None:
    row = conn.execute(f"{DRAFT_SELECT} WHERE id = ?", (draft_id,)).fetchone()
    return _draft(row) if row is not None else None


def list_drafts(conn, period: str, day: date) -> list[dict]:
    start, _ = period_bounds(period, day)
    rows = conn.execute(f"{DRAFT_SELECT} WHERE period = ? AND start_date = ? ORDER BY created_at DESC, rowid DESC",
                        (period, start.isoformat()))
    return [_draft(r) for r in rows]


def _insert(conn, report: dict, text: str, model: str | None, user_id: str) -> dict:
    draft_id = str(uuid.uuid4())
    with conn:
        conn.execute(
            "INSERT INTO report_drafts (id, period, start_date, end_date, figures_json, text, model, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (draft_id, report["period"], report["current"]["start"], report["current"]["end"],
             json.dumps(report), text, model, user_id))
    return get_draft(conn, draft_id)


def create_ai_draft(conn, llm, period: str, day: date, user_id: str) -> dict:
    report = summary(conn, period, day)
    try:
        with MODEL_LOCK:
            raw = llm.generate(draft_prompt(report), max_tokens=400)
    except Exception as exc:
        raise AIUnavailable() from exc
    text = strip_think(raw or "").strip()
    if not text:
        raise AIUnavailable()
    return _insert(conn, report, text, getattr(llm, "model_name", None), user_id)


def create_manual_draft(conn, period: str, day: date, text: str, user_id: str) -> dict:
    text = text.strip()
    if not text:
        raise ApiError(422, ["text: write the summary first"])
    return _insert(conn, summary(conn, period, day), text, None, user_id)


def update_draft(conn, draft_id: str, changes: dict, user_id: str) -> dict | None:
    draft = get_draft(conn, draft_id)
    if draft is None:
        return None
    if draft["status"] == "approved":
        raise ApiError(409, "Approved drafts cannot be edited")
    text = (changes.get("text") if changes.get("text") is not None else draft["text"]).strip()
    if not text:
        raise ApiError(422, ["text: cannot be empty"])
    approve = changes.get("status") == "approved"
    with conn:
        conn.execute(
            "UPDATE report_drafts SET text = ?, status = ?, approved_by = ?, updated_at = datetime('now') "
            "WHERE id = ? AND status = 'draft'",
            (text, "approved" if approve else "draft", user_id if approve else None, draft_id))
    return get_draft(conn, draft_id)
