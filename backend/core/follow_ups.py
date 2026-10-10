"""Follow-up visits: scheduling, derived due/overdue state, and completion."""
import sqlite3
import uuid
from datetime import date

from core import clock
from core.errors import ApiError
from core.forms import get_form
from core.records import _search_expression, get_patient

SELECT = (
    "SELECT f.id, f.patient_id, p.full_name AS patient_name, h.barangay, f.source_visit_id, f.form_type, "
    "f.due_date, f.reason, f.status, f.completed_visit_id, f.completed_at, f.created_at, f.updated_at "
    "FROM follow_ups f JOIN patients p ON p.id = f.patient_id JOIN households h ON h.id = p.household_id"
)
STATE_FILTERS = {
    "overdue": "f.status = 'scheduled' AND f.due_date < ?",
    "due": "f.status = 'scheduled' AND f.due_date = ?",
    "upcoming": "f.status = 'scheduled' AND f.due_date > ?",
    "completed": "f.status = 'completed'",
    "cancelled": "f.status = 'cancelled'",
}


def derive_state(status: str, due_date: str) -> str:
    if status != "scheduled":
        return status
    today = clock.today().isoformat()
    return "overdue" if due_date < today else "due" if due_date == today else "upcoming"


def _with_state(row: sqlite3.Row) -> dict:
    follow_up = dict(row)
    follow_up["state"] = derive_state(follow_up["status"], follow_up["due_date"])
    return follow_up


def get_follow_up(conn: sqlite3.Connection, follow_up_id: str) -> dict | None:
    row = conn.execute(f"{SELECT} WHERE f.id = ?", (follow_up_id,)).fetchone()
    return _with_state(row) if row is not None else None


def insert(conn, patient_id: str, due_date: date, reason: str | None, form_type: str | None,
           user_id: str, source_visit_id: str | None = None) -> str:
    """Insert a scheduled follow-up inside the caller's transaction."""
    follow_up_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO follow_ups (id, patient_id, source_visit_id, form_type, due_date, reason, status, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?)",
        (follow_up_id, patient_id, source_visit_id, form_type, due_date.isoformat(), reason, user_id),
    )
    return follow_up_id


def complete_in_tx(conn, follow_up_id: str, patient_id: str, visit_id: str | None) -> None:
    """Mark a scheduled follow-up of `patient_id` completed, inside the caller's transaction."""
    row = conn.execute("SELECT patient_id FROM follow_ups WHERE id = ?", (follow_up_id,)).fetchone()
    if row is None:
        raise ApiError(404, "Follow-up not found")
    cursor = conn.execute(
        "UPDATE follow_ups SET status = 'completed', completed_visit_id = ?, completed_at = datetime('now'), "
        "updated_at = datetime('now') WHERE id = ? AND patient_id = ? AND status = 'scheduled'",
        (visit_id, follow_up_id, patient_id),
    )
    if cursor.rowcount != 1:
        raise ApiError(409, "Follow-up is not scheduled")


def _check_due(due_date: date) -> None:
    if due_date < clock.today():
        raise ApiError(422, ["due_date: cannot be in the past"])


def create_follow_up(conn, patient_id: str, data: dict, user_id: str) -> dict | None:
    if get_patient(conn, patient_id) is None:
        return None
    _check_due(data["due_date"])
    if data.get("form_type") is not None and get_form(data["form_type"]) is None:
        raise ApiError(422, ["form_type: unknown form"])
    with conn:
        follow_up_id = insert(conn, patient_id, data["due_date"], data.get("reason"), data.get("form_type"), user_id)
    return get_follow_up(conn, follow_up_id)


def list_follow_ups(conn, state: str | None, patient_id: str | None, query: str | None,
                    limit: int, offset: int) -> dict:
    clauses, params = [], []
    if state is not None:
        clauses.append(STATE_FILTERS[state])
        if "?" in STATE_FILTERS[state]:
            params.append(clock.today().isoformat())
    if patient_id is not None:
        clauses.append("f.patient_id = ?")
        params.append(patient_id)
    if query:
        expression = _search_expression(query)
        if not expression:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        clauses.append("f.patient_id IN (SELECT patient_id FROM patient_search WHERE patient_search MATCH ?)")
        params.append(expression)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT count(*) FROM follow_ups f {where}", params).fetchone()[0]
    rows = conn.execute(f"{SELECT} {where} ORDER BY f.due_date, f.created_at, f.id LIMIT ? OFFSET ?",
                        [*params, limit, offset])
    return {"items": [_with_state(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def _scheduled_or_409(conn, follow_up_id: str) -> dict | None:
    follow_up = get_follow_up(conn, follow_up_id)
    if follow_up is not None and follow_up["status"] != "scheduled":
        raise ApiError(409, "Only scheduled follow-ups can be changed")
    return follow_up


def update_follow_up(conn, follow_up_id: str, changes: dict) -> dict | None:
    follow_up = _scheduled_or_409(conn, follow_up_id)
    if follow_up is None:
        return None
    fields = {}
    if changes.get("due_date") is not None:
        _check_due(changes["due_date"])
        fields["due_date"] = changes["due_date"].isoformat()
    if "reason" in changes:
        fields["reason"] = changes["reason"]
    if changes.get("status") == "cancelled":
        fields["status"] = "cancelled"
    if fields:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with conn:
            conn.execute(
                f"UPDATE follow_ups SET {assignments}, updated_at = datetime('now') "
                "WHERE id = ? AND status = 'scheduled'",
                (*fields.values(), follow_up_id),
            )
    return get_follow_up(conn, follow_up_id)


def complete_follow_up(conn, follow_up_id: str, visit_id: str | None) -> dict | None:
    follow_up = _scheduled_or_409(conn, follow_up_id)
    if follow_up is None:
        return None
    if visit_id is not None:
        row = conn.execute("SELECT patient_id, status FROM visits WHERE id = ?", (visit_id,)).fetchone()
        if row is None or row["status"] != "final" or row["patient_id"] != follow_up["patient_id"]:
            raise ApiError(422, ["visit_id: must be a finalized visit of the same patient"])
    with conn:
        complete_in_tx(conn, follow_up_id, follow_up["patient_id"], visit_id)
    return get_follow_up(conn, follow_up_id)
