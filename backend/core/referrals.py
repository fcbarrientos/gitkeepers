"""Referral flags from professional-reviewed rule files (never the AI), and referral slips."""
import json
import logging
import sqlite3
import uuid

from core import config
from core.errors import ApiError
from core.forms import get_form
from core.records import get_patient

log = logging.getLogger(__name__)

RULES_DIR = config.MIGRATIONS_DIR.parent / "referral_rules"
COMPARE = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def _conditions(when: dict) -> list[dict]:
    if "any" in when or "all" in when:
        return [c for part in when.get("any", []) + when.get("all", []) for c in _conditions(part)]
    return [when]


def _check(rule_set: dict) -> list[str]:
    """Problems that would make a rule set misfire; empty when it is usable."""
    form = get_form(rule_set.get("form_type", ""))
    if form is None:
        return [f"unknown form_type {rule_set.get('form_type')!r}"]
    types = {f["name"]: f["type"] for f in form["fields"]}
    problems = []
    for rule in rule_set.get("rules", []):
        name = rule.get("id", "?")
        if rule.get("urgency") not in ("urgent", "routine") or not rule.get("reason", {}).get("en"):
            problems.append(f"{name}: needs urgency urgent/routine and an English reason")
        for cond in _conditions(rule.get("when", {})):
            field_type = types.get(cond.get("field"))
            if field_type is None:
                problems.append(f"{name}: unknown field {cond.get('field')!r}")
            elif cond.get("op") == "is_true":
                if field_type != "boolean":
                    problems.append(f"{name}: is_true needs a yes/no field")
            elif cond.get("op") not in COMPARE or field_type not in ("integer", "number") \
                    or not isinstance(cond.get("value"), (int, float)):
                problems.append(f"{name}: bad comparison on {cond.get('field')!r}")
    return problems


def _read_rules() -> tuple[dict[str, dict], list[str]]:
    rules, problems = {}, []
    for path in sorted(RULES_DIR.glob("*.json")):
        try:
            rule_set = json.loads(path.read_text(encoding="utf-8"))
            found = _check(rule_set)
        except (ValueError, TypeError, AttributeError) as exc:
            found = [f"not valid rule JSON ({exc})"]
        if found:
            problems += [f"{path.name}: {p}" for p in found]
        else:
            rules[path.stem] = rule_set
    return rules, problems


def load_rules() -> dict[str, dict]:
    """Valid rule sets by form type, read fresh so edited files apply without a restart.

    A broken file is skipped and logged rather than blocking every visit from being finalized.
    """
    rules, problems = _read_rules()
    for problem in problems:
        log.warning("referral rules skipped: %s", problem)
    return rules


def rule_problems() -> list[str]:
    return _read_rules()[1]


def matches(condition: dict, values: dict) -> bool:
    if "any" in condition:
        return any(matches(c, values) for c in condition["any"])
    if "all" in condition:
        return all(matches(c, values) for c in condition["all"])
    value = values.get(condition["field"])
    if condition["op"] == "is_true":
        return value is True
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return False  # an unrecorded value never triggers a referral
    return COMPARE[condition["op"]](value, condition["value"])


def matching_rules(form_type: str, values: dict) -> list[dict]:
    rule_set = load_rules().get(form_type) or {}
    return [rule for rule in rule_set.get("rules", []) if matches(rule["when"], values)]


def flag_in_tx(conn: sqlite3.Connection, visit_id: str, patient_id: str, form_type: str, values: dict) -> None:
    """Record a flag for every rule a finalized visit meets, inside the caller's transaction."""
    for rule in matching_rules(form_type, values):
        conn.execute(
            "INSERT INTO referral_flags (id, visit_id, patient_id, rule_id, reason_en, reason_fil, urgency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), visit_id, patient_id, rule["id"], rule["reason"]["en"],
             rule["reason"].get("fil") or rule["reason"]["en"], rule["urgency"]),
        )


FLAG_SELECT = (
    "SELECT f.id, f.visit_id, f.patient_id, p.full_name AS patient_name, f.rule_id, f.reason_en, f.reason_fil, "
    "f.urgency, f.status, f.dismiss_note, f.created_at, v.form_type, v.visit_date "
    "FROM referral_flags f JOIN patients p ON p.id = f.patient_id JOIN visits v ON v.id = f.visit_id"
)


def get_flag(conn: sqlite3.Connection, flag_id: str) -> dict | None:
    row = conn.execute(f"{FLAG_SELECT} WHERE f.id = ?", (flag_id,)).fetchone()
    return dict(row) if row is not None else None


def list_flags(conn, status: str | None, patient_id: str | None, visit_id: str | None) -> list[dict]:
    clauses, params = [], []
    for column, value in (("f.status", status), ("f.patient_id", patient_id), ("f.visit_id", visit_id)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"{FLAG_SELECT} {where} ORDER BY f.urgency = 'urgent' DESC, f.created_at DESC, f.rule_id LIMIT 200", params)
    return [dict(r) for r in rows]


def dismiss_flag(conn, flag_id: str, note: str | None) -> dict | None:
    if get_flag(conn, flag_id) is None:
        return None
    with conn:
        cursor = conn.execute(
            "UPDATE referral_flags SET status = 'dismissed', dismiss_note = ?, updated_at = datetime('now') "
            "WHERE id = ? AND status = 'open'", (note, flag_id))
        if cursor.rowcount != 1:
            raise ApiError(409, "This flag was already handled")
    return get_flag(conn, flag_id)


REFERRAL_SELECT = (
    "SELECT r.id, r.patient_id, p.full_name AS patient_name, p.birth_date, p.sex, h.barangay, h.sitio, "
    "r.flag_id, r.facility, r.reason, r.urgency, r.notes, r.status, r.created_by, "
    "u.full_name AS created_by_name, r.created_at, r.updated_at "
    "FROM referrals r JOIN patients p ON p.id = r.patient_id "
    "JOIN households h ON h.id = p.household_id JOIN users u ON u.id = r.created_by"
)


def _with_visit(conn, row: sqlite3.Row) -> dict:
    referral = dict(row)
    referral["visit"] = None
    if referral["flag_id"]:
        visit = conn.execute(
            "SELECT v.id, v.form_type, v.visit_date, v.values_json FROM referral_flags f "
            "JOIN visits v ON v.id = f.visit_id WHERE f.id = ?", (referral["flag_id"],)).fetchone()
        if visit is not None:
            referral["visit"] = {"id": visit["id"], "form_type": visit["form_type"],
                                 "visit_date": visit["visit_date"], "values": json.loads(visit["values_json"])}
    return referral


def get_referral(conn, referral_id: str) -> dict | None:
    row = conn.execute(f"{REFERRAL_SELECT} WHERE r.id = ?", (referral_id,)).fetchone()
    return _with_visit(conn, row) if row is not None else None


def list_referrals(conn, status: str | None, patient_id: str | None, limit: int, offset: int) -> dict:
    clauses, params = [], []
    for column, value in (("r.status", status), ("r.patient_id", patient_id)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT count(*) FROM referrals r {where}", params).fetchone()[0]
    rows = conn.execute(f"{REFERRAL_SELECT} {where} ORDER BY r.created_at DESC, r.id LIMIT ? OFFSET ?",
                        [*params, limit, offset])
    return {"items": [_with_visit(conn, r) for r in rows], "total": total, "limit": limit, "offset": offset}


def create_referral(conn, data: dict, user_id: str) -> dict | None:
    if get_patient(conn, data["patient_id"]) is None:
        return None
    flag_id = data.get("flag_id")
    referral_id = str(uuid.uuid4())
    with conn:
        if flag_id:
            flag = conn.execute("SELECT patient_id FROM referral_flags WHERE id = ?", (flag_id,)).fetchone()
            if flag is None or flag["patient_id"] != data["patient_id"]:
                raise ApiError(422, ["flag_id: not a referral flag of this patient"])
            cursor = conn.execute(
                "UPDATE referral_flags SET status = 'referred', updated_at = datetime('now') "
                "WHERE id = ? AND status = 'open'", (flag_id,))
            if cursor.rowcount != 1:
                raise ApiError(409, "This flag was already handled")
        conn.execute(
            "INSERT INTO referrals (id, patient_id, flag_id, facility, reason, urgency, notes, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (referral_id, data["patient_id"], flag_id, data["facility"], data["reason"], data["urgency"],
             data.get("notes"), user_id),
        )
    return get_referral(conn, referral_id)
