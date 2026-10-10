"""Checkup visits: validated form values, the draft/final lifecycle, and AI provenance."""
import json
import sqlite3
import uuid
from datetime import date

from core import clock, follow_ups
from core.errors import ApiError
from core.forms import get_form, validate_values
from core.records import get_patient

VISIT_COLUMNS = (
    "id, patient_id, form_type, visit_date, status, values_json, sources_json, note, "
    "suggestion_id, recorded_by, created_at, updated_at, finalized_at"
)
FINAL_ONLY = ("follow_up", "completes_follow_up_id")


def _decode(row: sqlite3.Row) -> dict:
    visit = dict(row)
    visit["values"] = json.loads(visit.pop("values_json"))
    visit["sources"] = json.loads(visit.pop("sources_json"))
    return visit


def get_visit(conn: sqlite3.Connection, visit_id: str) -> dict | None:
    row = conn.execute(f"SELECT {VISIT_COLUMNS} FROM visits WHERE id = ?", (visit_id,)).fetchone()
    return _decode(row) if row is not None else None


def list_visits(conn, patient_id: str, form_type: str | None, limit: int, offset: int) -> dict | None:
    if get_patient(conn, patient_id) is None:
        return None
    where, params = "WHERE patient_id = ?", [patient_id]
    if form_type is not None:
        where += " AND form_type = ?"
        params.append(form_type)
    total = conn.execute(f"SELECT count(*) FROM visits {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT {VISIT_COLUMNS} FROM visits {where} "
        "ORDER BY visit_date DESC, created_at DESC, id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"items": [_decode(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def _form(form_type: str) -> dict:
    form = get_form(form_type)
    if form is None:
        raise ApiError(422, ["form_type: unknown form"])
    return form


def _check_date(visit_date: date) -> None:
    if visit_date > clock.today():
        raise ApiError(422, ["visit_date: cannot be in the future"])


def _clean(form: dict, values: dict, final: bool) -> dict:
    clean, problems = validate_values(form, values, require_complete=final)
    if problems:
        raise ApiError(422, problems)
    return clean


def _same(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return sorted(a) == sorted(b)
    return a == b


def _sources(conn, patient_id: str, form_type: str, values: dict,
             suggestion_id: str | None, accepted: list[str]) -> dict:
    """Where each recorded value came from: manual, ai_accepted, or ai_edited."""
    if accepted and not suggestion_id:
        raise ApiError(422, ["ai_accepted_fields: requires suggestion_id"])
    suggested = {}
    if suggestion_id:
        row = conn.execute(
            "SELECT patient_id, form_type, values_json FROM ai_suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()
        if row is None or row["patient_id"] != patient_id or row["form_type"] != form_type:
            raise ApiError(422, ["suggestion_id: does not match this patient and form"])
        suggested = json.loads(row["values_json"])
    empty = [name for name in accepted if suggested.get(name) is None]
    if empty:
        raise ApiError(422, [f"{name}: the AI did not suggest a value" for name in empty])
    sources = {}
    for name, value in values.items():
        if value is None:
            continue
        if name in accepted:
            sources[name] = "ai_accepted" if _same(value, suggested[name]) else "ai_edited"
        else:
            sources[name] = "manual"
    return sources


def _reject_final_only_on_draft(data: dict, final: bool) -> None:
    if not final and any(data.get(key) for key in FINAL_ONLY):
        raise ApiError(422, ["follow_up: only allowed when finalizing"])


def on_finalize(conn, visit_id: str, patient_id: str, form_type: str, visit_date: date,
                data: dict, user_id: str) -> dict | None:
    """Follow-up side effects of finalizing a visit; runs inside the visit's transaction."""
    created_id = None
    plan = data.get("follow_up")
    if plan:
        if plan["due_date"] <= visit_date:
            raise ApiError(422, ["follow_up.due_date: must be after visit_date"])
        created_id = follow_ups.insert(conn, patient_id, plan["due_date"], plan.get("reason"),
                                       form_type, user_id, source_visit_id=visit_id)
    if data.get("completes_follow_up_id"):
        follow_ups.complete_in_tx(conn, data["completes_follow_up_id"], patient_id, visit_id)
    return follow_ups.get_follow_up(conn, created_id) if created_id else None


def _write(conn, sql: str, params: tuple, finalize_args: tuple | None) -> dict | None:
    """Run one visit write plus the finalize hook in a single transaction."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(sql, params)
        if cursor.rowcount != 1:  # a concurrent request finalized the draft first
            raise ApiError(409, "Finalized visits cannot be edited")
        created = on_finalize(conn, *finalize_args) if finalize_args else None
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return created


def create_visit(conn, patient_id: str, data: dict, user_id: str) -> dict | None:
    if get_patient(conn, patient_id) is None:
        return None
    form = _form(data["form_type"])
    final = data.get("status") == "final"
    _reject_final_only_on_draft(data, final)
    _check_date(data["visit_date"])
    values = _clean(form, data.get("values") or {}, final)
    accepted = data.get("ai_accepted_fields") or []
    sources = _sources(conn, patient_id, form["form_type"], values, data.get("suggestion_id"), accepted)
    visit_id = str(uuid.uuid4())
    created = _write(
        conn,
        "INSERT INTO visits (id, patient_id, form_type, visit_date, status, values_json, sources_json, "
        "note, suggestion_id, recorded_by, finalized_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN datetime('now') END)",
        (visit_id, patient_id, form["form_type"], data["visit_date"].isoformat(),
         "final" if final else "draft", json.dumps(values), json.dumps(sources), data.get("note"),
         data.get("suggestion_id"), user_id, final),
        (visit_id, patient_id, form["form_type"], data["visit_date"], data, user_id) if final else None,
    )
    visit = get_visit(conn, visit_id)
    visit["follow_up_created"] = created
    return visit


def update_visit(conn, visit_id: str, changes: dict, user_id: str) -> dict | None:
    current = get_visit(conn, visit_id)
    if current is None:
        return None
    if current["status"] == "final":
        raise ApiError(409, "Finalized visits cannot be edited")
    form = _form(current["form_type"])
    final = changes.get("status") == "final"
    _reject_final_only_on_draft(changes, final)
    visit_date = changes.get("visit_date") or date.fromisoformat(current["visit_date"])
    _check_date(visit_date)
    raw_values = (changes.get("values") or {}) if "values" in changes else current["values"]
    values = _clean(form, raw_values, final)
    suggestion_id = changes["suggestion_id"] if "suggestion_id" in changes else current["suggestion_id"]
    if "ai_accepted_fields" in changes:
        accepted = changes["ai_accepted_fields"] or []
    else:  # keep what the worker accepted earlier
        accepted = [name for name, source in current["sources"].items() if source != "manual"]
    sources = _sources(conn, current["patient_id"], form["form_type"], values, suggestion_id, accepted)
    note = changes["note"] if "note" in changes else current["note"]
    created = _write(
        conn,
        "UPDATE visits SET visit_date = ?, values_json = ?, sources_json = ?, note = ?, suggestion_id = ?, "
        "status = ?, finalized_at = CASE WHEN ? THEN datetime('now') END, updated_at = datetime('now') "
        "WHERE id = ? AND status = 'draft'",
        (visit_date.isoformat(), json.dumps(values), json.dumps(sources), note, suggestion_id,
         "final" if final else "draft", final, visit_id),
        (visit_id, current["patient_id"], form["form_type"], visit_date, changes, user_id) if final else None,
    )
    visit = get_visit(conn, visit_id)
    visit["follow_up_created"] = created
    return visit


def list_recent_visits(conn, visit_date: date | None, status: str | None, limit: int, offset: int) -> dict:
    """Visits across all patients, newest first, each with the patient's name."""
    clauses, params = [], []
    if visit_date is not None:
        clauses.append("v.visit_date = ?")
        params.append(visit_date.isoformat())
    if status is not None:
        clauses.append("v.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    columns = ", ".join(f"v.{name.strip()}" for name in VISIT_COLUMNS.split(","))
    total = conn.execute(f"SELECT count(*) FROM visits v {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT {columns}, p.full_name AS patient_name FROM visits v JOIN patients p ON p.id = v.patient_id "
        f"{where} ORDER BY v.visit_date DESC, v.created_at DESC, v.id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"items": [_decode(r) for r in rows], "total": total, "limit": limit, "offset": offset}
