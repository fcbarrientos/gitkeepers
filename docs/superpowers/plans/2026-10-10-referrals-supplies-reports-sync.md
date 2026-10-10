# Referrals, Supplies, Reports and Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four "Coming soon" tabs with working referrals (rule-based flags and slips), medicine and supply tracking, weekly/monthly reports with an editable AI draft, and manual encrypted sync with signed RHU receipts.

**Architecture:** Four backend modules (`core/referrals.py`, `core/supplies.py`, `core/sync_state.py`, `core/reports.py`), each with a router and one shared migration (`005`). Referral flags are written inside the existing visit-finalize transaction. Sync state is derived from transfer-file records instead of being stored on each row. The frontend gets one API module per feature (`src/api/modules.ts`) and one page set per tab.

**Tech Stack:**
- Backend: FastAPI and SQLite, `unittest`.
- Frontend: React 18, React Router 6, Vitest and Testing Library, all as already installed.

**Spec:** `docs/superpowers/specs/2026-10-10-referrals-supplies-reports-sync-design.md`

## Global Constraints

- **No git operations.** Never commit, push, branch or stash. Every "commit" point is a stop-and-verify point.
- Backend commands run from `gitkeepers/backend` with `.venv/Scripts/python`. Frontend commands run from `gitkeepers/frontend`.
- Errors follow the existing contract: `{detail}` is safe to show, and 422 returns a list of `"<field>: <problem>"`.
- Every user-visible string goes through `t()`, and `en.json` and `fil.json` keep identical key sets.
- Referral flags come only from rule files. The AI is never involved in flagging.
- The AI report prompt contains aggregated numbers only: no names, notes or IDs.
- A record counts as synced only after a valid RHU receipt for a transfer file holding its current version.
- Ruling carried from the spec: the prenatal form has no blurred-vision field, so the prenatal rules use abdominal pain and shortness of breath instead.

## Review Focus

1. **Distributing more stock than is on hand** (including a negative adjustment): the request is refused with the amount in stock, and nothing is recorded. Tested in Task 2.
2. **A forged, mismatched or unknown receipt:** nothing is marked synced, and the error is clear. Tested in Task 3.
3. **A record edited after it was exported** goes back to pending and is included in the next transfer file. Tested in Task 3.
4. **Personal details never leave in a transfer file:** no names, phone numbers or locations in the payload. Tested in Task 3.
5. **The AI unavailable or returning nothing for a report draft:** 503, and the worker can still write and approve the summary by hand. Tested in Tasks 4 and 8.

---

### Task 1: Referral rules, flags on finalize, referrals API (backend)

**Files:**
- Create: `backend/migrations/005_referrals_supplies_reports_sync.sql`
- Create: `backend/referral_rules/prenatal.json`, `child_growth.json`, `bp_followup.json`
- Create: `backend/core/referrals.py`, `backend/routes/referrals.py`, `backend/tests/test_referrals.py`
- Modify: `backend/core/visits.py` (`on_finalize`), `backend/api.py` (include router)

**Interfaces:**
- Produces:
  - `referrals.matches(condition, values) -> bool`
  - `referrals.flag_in_tx(conn, visit_id, patient_id, form_type, values)`
  - `GET /referral-rules`
  - `GET /referral-flags?status=&patient_id=&visit_id=` → `list[ReferralFlag]`
  - `GET /referral-flags/{id}` and `POST /referral-flags/{id}/dismiss {note}`
  - `POST /referrals`, `GET /referrals?status=&patient_id=&limit=&offset=` and `GET /referrals/{id}` (which includes `visit {id, form_type, visit_date, values}`)
  - The tables used by Tasks 2–4.

- [ ] **Step 1: Write the migration and rule files**

`backend/migrations/005_referrals_supplies_reports_sync.sql`:

```sql
CREATE TABLE referral_flags (
    id            TEXT PRIMARY KEY,
    visit_id      TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    rule_id       TEXT NOT NULL,
    reason_en     TEXT NOT NULL,
    reason_fil    TEXT NOT NULL,
    urgency       TEXT NOT NULL CHECK (urgency IN ('urgent', 'routine')),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'referred', 'dismissed')),
    dismiss_note  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_flags_status ON referral_flags(status, created_at);
CREATE INDEX idx_flags_patient ON referral_flags(patient_id);
CREATE INDEX idx_flags_visit ON referral_flags(visit_id);

CREATE TABLE referrals (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    flag_id     TEXT REFERENCES referral_flags(id),
    facility    TEXT NOT NULL,
    reason      TEXT NOT NULL,
    urgency     TEXT NOT NULL CHECK (urgency IN ('urgent', 'routine')),
    notes       TEXT,
    status      TEXT NOT NULL DEFAULT 'issued' CHECK (status IN ('issued', 'sent')),
    created_by  TEXT NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_referrals_patient ON referrals(patient_id);

CREATE TABLE supply_items (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL UNIQUE COLLATE NOCASE,
    unit                 TEXT NOT NULL,
    low_stock_threshold  INTEGER NOT NULL CHECK (low_stock_threshold >= 0),
    target_level         INTEGER NOT NULL CHECK (target_level >= 0),
    active               INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE supply_movements (
    id             TEXT PRIMARY KEY,
    item_id        TEXT NOT NULL REFERENCES supply_items(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('received', 'distributed', 'adjusted')),
    quantity       INTEGER NOT NULL,   -- signed change in stock: received > 0, distributed < 0
    movement_date  TEXT NOT NULL,      -- YYYY-MM-DD
    note           TEXT,
    recorded_by    TEXT NOT NULL REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_movements_item ON supply_movements(item_id, movement_date);

CREATE TABLE report_drafts (
    id            TEXT PRIMARY KEY,
    period        TEXT NOT NULL CHECK (period IN ('week', 'month')),
    start_date    TEXT NOT NULL,
    end_date      TEXT NOT NULL,
    figures_json  TEXT NOT NULL,       -- the summary the draft was written from
    text          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
    model         TEXT,                -- NULL when written by hand
    created_by    TEXT NOT NULL REFERENCES users(id),
    approved_by   TEXT REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_drafts_period ON report_drafts(period, start_date);

CREATE TABLE sync_bundles (
    id               TEXT PRIMARY KEY,
    record_count     INTEGER NOT NULL,
    bundle_json      TEXT NOT NULL,    -- kept so the same file can be downloaded again
    created_by       TEXT NOT NULL REFERENCES users(id),
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    acknowledged_at  TEXT
);

CREATE TABLE sync_bundle_records (
    bundle_id          TEXT NOT NULL REFERENCES sync_bundles(id) ON DELETE CASCADE,
    record_type        TEXT NOT NULL,
    record_id          TEXT NOT NULL,
    record_updated_at  TEXT NOT NULL,  -- the version that was exported
    PRIMARY KEY (bundle_id, record_type, record_id)
);
CREATE INDEX idx_sync_records ON sync_bundle_records(record_type, record_id);
```

`backend/referral_rules/prenatal.json`:

```json
{
  "form_type": "prenatal",
  "verification": "draft, pending professional review",
  "rules": [
    {"id": "prenatal-high-bp", "urgency": "urgent",
     "when": {"any": [{"field": "bp_systolic", "op": ">=", "value": 140},
                      {"field": "bp_diastolic", "op": ">=", "value": 90}]},
     "reason": {"en": "High blood pressure in pregnancy (140/90 or higher)",
                "fil": "Mataas na presyon habang buntis (140/90 o higit pa)"}},
    {"id": "prenatal-bleeding", "urgency": "urgent",
     "when": {"field": "bleeding", "op": "is_true"},
     "reason": {"en": "Vaginal bleeding in pregnancy", "fil": "Pagdurugo habang buntis"}},
    {"id": "prenatal-fever", "urgency": "urgent",
     "when": {"field": "temperature_c", "op": ">=", "value": 38.0},
     "reason": {"en": "Fever of 38.0 °C or higher in pregnancy", "fil": "Lagnat na 38.0 °C pataas habang buntis"}},
    {"id": "prenatal-abdominal-pain", "urgency": "urgent",
     "when": {"field": "abdominal_pain", "op": "is_true"},
     "reason": {"en": "Abdominal pain in pregnancy", "fil": "Pananakit ng tiyan habang buntis"}},
    {"id": "prenatal-breathing", "urgency": "urgent",
     "when": {"field": "shortness_of_breath", "op": "is_true"},
     "reason": {"en": "Shortness of breath in pregnancy", "fil": "Hirap huminga habang buntis"}}
  ]
}
```

`backend/referral_rules/child_growth.json`:

```json
{
  "form_type": "child_growth",
  "verification": "draft, pending professional review",
  "rules": [
    {"id": "child-muac", "urgency": "urgent",
     "when": {"field": "muac_cm", "op": "<", "value": 11.5},
     "reason": {"en": "Severe acute malnutrition (MUAC below 11.5 cm)",
                "fil": "Malubhang malnutrisyon (MUAC na mas mababa sa 11.5 cm)"}},
    {"id": "child-fever", "urgency": "routine",
     "when": {"field": "temperature_c", "op": ">=", "value": 38.5},
     "reason": {"en": "Child with fever of 38.5 °C or higher", "fil": "Batang may lagnat na 38.5 °C pataas"}}
  ]
}
```

`backend/referral_rules/bp_followup.json`:

```json
{
  "form_type": "bp_followup",
  "verification": "draft, pending professional review",
  "rules": [
    {"id": "bp-severe", "urgency": "urgent",
     "when": {"any": [{"field": "bp_systolic", "op": ">=", "value": 180},
                      {"field": "bp_diastolic", "op": ">=", "value": 110}]},
     "reason": {"en": "Very high blood pressure (180/110 or higher)",
                "fil": "Napakataas na presyon (180/110 o higit pa)"}},
    {"id": "bp-chest-pain", "urgency": "urgent",
     "when": {"field": "chest_pain", "op": "is_true"},
     "reason": {"en": "Chest pain with high blood pressure", "fil": "Sakit ng dibdib na may mataas na presyon"}},
    {"id": "bp-breathing", "urgency": "urgent",
     "when": {"field": "shortness_of_breath", "op": "is_true"},
     "reason": {"en": "Shortness of breath", "fil": "Hirap huminga"}}
  ]
}
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_referrals.py`:

```python
"""Rule-based referral flags and referral slips."""
from core.forms import get_form
from core.referrals import COMPARE, load_rules, matches
from tests.api_case import VisitTestCase

SEVERE = {"bp_systolic": 185, "bp_diastolic": 100, "chest_pain": True}


class RuleFileTests(VisitTestCase):
    def test_every_rule_names_a_real_field_with_a_matching_type(self):
        for form_type, rule_set in load_rules().items():
            form = get_form(form_type)
            self.assertIsNotNone(form, form_type)
            types = {f["name"]: f["type"] for f in form["fields"]}
            for rule in rule_set["rules"]:
                self.assertIn(rule["urgency"], ("urgent", "routine"))
                self.assertTrue(rule["reason"]["en"] and rule["reason"]["fil"], rule["id"])
                for cond in rule["when"].get("any") or rule["when"].get("all") or [rule["when"]]:
                    self.assertIn(cond["field"], types, rule["id"])
                    if cond["op"] == "is_true":
                        self.assertEqual(types[cond["field"]], "boolean", rule["id"])
                    else:
                        self.assertIn(cond["op"], COMPARE, rule["id"])
                        self.assertIn(types[cond["field"]], ("integer", "number"), rule["id"])

    def test_matching_ignores_unrecorded_values(self):
        rule = {"any": [{"field": "bp_systolic", "op": ">=", "value": 140}, {"field": "bleeding", "op": "is_true"}]}
        self.assertTrue(matches(rule, {"bp_systolic": 150}))
        self.assertTrue(matches(rule, {"bleeding": True}))
        self.assertFalse(matches(rule, {"bp_systolic": None, "bleeding": False}))
        self.assertFalse(matches({"all": [{"field": "a", "op": "<", "value": 1}]}, {"a": True}))


class FlagTests(VisitTestCase):
    def flags(self, query=""):
        return self.client.get(f"/api/v1/referral-flags{query}", headers=self.headers).json()

    def test_finalizing_flags_every_matching_rule(self):
        visit = self.create_visit(status="final", values=SEVERE).json()
        flags = self.flags(f"?visit_id={visit['id']}")
        self.assertEqual(sorted(f["rule_id"] for f in flags), ["bp-chest-pain", "bp-severe"])
        self.assertEqual(flags[0]["patient_name"], "Ana Dela Cruz")
        self.assertEqual({f["status"] for f in flags}, {"open"})

    def test_drafts_and_normal_values_are_not_flagged(self):
        self.create_visit(values=SEVERE)  # draft
        self.create_visit(status="final", values={"bp_systolic": 130, "bp_diastolic": 85})
        self.assertEqual(self.flags(), [])

    def test_finalizing_a_draft_flags_it(self):
        draft = self.create_visit(values=SEVERE).json()
        self.assertEqual(self.patch_visit(draft["id"], status="final").status_code, 200)
        self.assertEqual(len(self.flags(f"?visit_id={draft['id']}")), 2)

    def test_dismiss_once(self):
        self.create_visit(status="final", values={"bp_systolic": 190, "bp_diastolic": 100})
        flag = self.flags()[0]
        response = self.client.post(f"/api/v1/referral-flags/{flag['id']}/dismiss",
                                    json={"note": "Seen by midwife"}, headers=self.headers)
        self.assertEqual((response.status_code, response.json()["status"]), (200, "dismissed"))
        again = self.client.post(f"/api/v1/referral-flags/{flag['id']}/dismiss", json={}, headers=self.headers)
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.flags("?status=open"), [])

    def test_rules_endpoint(self):
        rule_sets = self.client.get("/api/v1/referral-rules", headers=self.headers).json()
        self.assertEqual({r["form_type"] for r in rule_sets}, {"prenatal", "child_growth", "bp_followup"})


class ReferralTests(VisitTestCase):
    def referral(self, **overrides):
        payload = {"patient_id": self.patient_id, "facility": "San Roque RHU", "reason": "Very high BP",
                   "urgency": "urgent", **overrides}
        return self.client.post("/api/v1/referrals", json=payload, headers=self.headers)

    def test_referral_from_a_flag_marks_it_referred_and_carries_the_visit(self):
        self.create_visit(status="final", values={"bp_systolic": 190, "bp_diastolic": 100})
        flag = self.client.get("/api/v1/referral-flags", headers=self.headers).json()[0]
        response = self.referral(flag_id=flag["id"], notes="Please assess today")
        self.assertEqual(response.status_code, 201, response.text)
        referral = response.json()
        self.assertEqual((referral["status"], referral["created_by_name"]), ("issued", "Test User"))
        self.assertEqual(referral["visit"]["values"]["bp_systolic"], 190)
        self.assertEqual(referral["barangay"], "San Roque")
        flag = self.client.get(f"/api/v1/referral-flags/{flag['id']}", headers=self.headers).json()
        self.assertEqual(flag["status"], "referred")
        self.assertEqual(self.referral(flag_id=flag["id"]).status_code, 409)

    def test_manual_referral_and_listing(self):
        self.assertEqual(self.referral().status_code, 201)
        page = self.client.get(f"/api/v1/referrals?patient_id={self.patient_id}", headers=self.headers).json()
        self.assertEqual(page["total"], 1)
        self.assertIsNone(page["items"][0]["visit"])

    def test_rejects_bad_input(self):
        other = self.make_patient(self.token, full_name="Berto Santos", contact_number="09179999999")
        self.create_visit(patient_id=other, status="final", values={"bp_systolic": 190, "bp_diastolic": 100})
        flag = self.client.get("/api/v1/referral-flags", headers=self.headers).json()[0]
        self.assertEqual(self.referral(flag_id=flag["id"]).json()["detail"],
                         ["flag_id: not a referral flag of this patient"])
        self.assertEqual(self.referral(facility="   ").status_code, 422)
        self.assertEqual(self.referral(patient_id="nope").status_code, 404)
```

- [ ] **Step 3: Run them and check they fail**

Run: `.venv/Scripts/python -m unittest tests.test_referrals`

Expected: ERROR, `ModuleNotFoundError: No module named 'core.referrals'`.

- [ ] **Step 4: Implement**

`backend/core/referrals.py`:

```python
"""Referral flags from professional-reviewed rule files (never the AI), and referral slips."""
import json
import sqlite3
import uuid

from core import config
from core.errors import ApiError
from core.records import get_patient

RULES_DIR = config.MIGRATIONS_DIR.parent / "referral_rules"
COMPARE = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


def load_rules() -> dict[str, dict]:
    """Rule sets by form type, read fresh so edited rule files apply without a restart."""
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(RULES_DIR.glob("*.json"))}


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
```

`backend/routes/referrals.py`:

```python
"""Referral rules, flags raised by them, and referral slips."""
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from core.auth import AuthContext, current_user
from core.referrals import create_referral, dismiss_flag, get_flag, get_referral, list_flags, list_referrals, load_rules
from core.storage import get_db

router = APIRouter()
Urgency = Literal["urgent", "routine"]


class ReferralRule(BaseModel):
    id: str
    urgency: Urgency
    reason: dict[str, str]
    when: dict[str, Any]


class RuleSet(BaseModel):
    form_type: str
    verification: str
    rules: list[ReferralRule]


class ReferralFlag(BaseModel):
    id: str
    visit_id: str
    patient_id: str
    patient_name: str
    rule_id: str
    reason_en: str
    reason_fil: str
    urgency: Urgency
    status: Literal["open", "referred", "dismissed"]
    dismiss_note: str | None
    created_at: str
    form_type: str
    visit_date: str


class FlagDismiss(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ReferralCreate(BaseModel):
    patient_id: str = Field(min_length=1, max_length=64)
    flag_id: str | None = Field(default=None, max_length=64)
    facility: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)
    urgency: Urgency = "urgent"
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("facility", "reason")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ReferralVisit(BaseModel):
    id: str
    form_type: str
    visit_date: str
    values: dict[str, Any]


class Referral(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    birth_date: str | None
    sex: str | None
    barangay: str
    sitio: str | None
    flag_id: str | None
    facility: str
    reason: str
    urgency: Urgency
    notes: str | None
    status: Literal["issued", "sent"]
    created_by: str
    created_by_name: str
    created_at: str
    updated_at: str
    visit: ReferralVisit | None


class ReferralPage(BaseModel):
    items: list[Referral]
    total: int
    limit: int
    offset: int


@router.get("/referral-rules", response_model=list[RuleSet], operation_id="listReferralRules")
def referral_rules():
    return list(load_rules().values())


@router.get("/referral-flags", response_model=list[ReferralFlag], operation_id="listReferralFlags")
def flags(
    status_filter: Literal["open", "referred", "dismissed"] | None = Query(default=None, alias="status"),
    patient_id: str | None = None,
    visit_id: str | None = None,
    db: sqlite3.Connection = Depends(get_db),
):
    return list_flags(db, status_filter, patient_id, visit_id)


@router.get("/referral-flags/{flag_id}", response_model=ReferralFlag, operation_id="getReferralFlag")
def flag_detail(flag_id: str, db: sqlite3.Connection = Depends(get_db)):
    flag = get_flag(db, flag_id)
    if flag is None:
        raise HTTPException(status_code=404, detail="Referral flag not found")
    return flag


@router.post("/referral-flags/{flag_id}/dismiss", response_model=ReferralFlag, operation_id="dismissReferralFlag")
def dismiss(flag_id: str, data: FlagDismiss, db: sqlite3.Connection = Depends(get_db)):
    flag = dismiss_flag(db, flag_id, data.note)
    if flag is None:
        raise HTTPException(status_code=404, detail="Referral flag not found")
    return flag


@router.post("/referrals", response_model=Referral, status_code=status.HTTP_201_CREATED, operation_id="createReferral")
def new_referral(data: ReferralCreate, auth: AuthContext = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    referral = create_referral(db, data.model_dump(), auth.user["id"])
    if referral is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return referral


@router.get("/referrals", response_model=ReferralPage, operation_id="listReferrals")
def referrals(
    status_filter: Literal["issued", "sent"] | None = Query(default=None, alias="status"),
    patient_id: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    return list_referrals(db, status_filter, patient_id, limit, offset)


@router.get("/referrals/{referral_id}", response_model=Referral, operation_id="getReferral")
def referral_detail(referral_id: str, db: sqlite3.Connection = Depends(get_db)):
    referral = get_referral(db, referral_id)
    if referral is None:
        raise HTTPException(status_code=404, detail="Referral not found")
    return referral
```

In `backend/core/visits.py`:
- Change `from core import clock, follow_ups` to `from core import clock, follow_ups, referrals`.
- In `on_finalize`, insert before `return follow_ups.get_follow_up(...)`:

```python
    values = json.loads(conn.execute("SELECT values_json FROM visits WHERE id = ?", (visit_id,)).fetchone()[0])
    referrals.flag_in_tx(conn, visit_id, patient_id, form_type, values)
```

In `backend/api.py`:
- Add `from routes.referrals import router as referrals_router`.
- After the dashboard `include_router` line, add:

```python
app.include_router(referrals_router, prefix="/api/v1", dependencies=signed_in, tags=["referrals"])
```

- [ ] **Step 5: Run the tests and check they pass**

Run: `.venv/Scripts/python -m unittest tests.test_referrals tests.test_visits tests.test_follow_ups`

Expected: OK.

- [ ] **Step 6: Stop. No git operations.**

---

### Task 2: Medicine and supply tracking (backend)

**Files:**
- Create: `backend/core/supplies.py`, `backend/routes/supplies.py`, `backend/tests/test_supplies.py`
- Modify: `backend/api.py`

**Interfaces:**
- Produces:
  - `GET /supplies?include_inactive=` → `list[SupplyItem]` (with `on_hand` and `low`)
  - `POST /supplies`, `GET|PATCH /supplies/{id}`
  - `GET /supplies/{id}/movements?limit=&offset=` and `POST /supplies/{id}/movements {kind, quantity, movement_date, note}`
  - `GET /supplies/request-list` → items plus `request_quantity`
  - `supplies.list_items(conn, include_inactive)`, used by the dashboard in Task 4.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_supplies.py`:

```python
"""Supply items, stock movements, low-stock flags and the request list."""
from tests.api_case import VisitTestCase


class SupplyTests(VisitTestCase):
    def item(self, name="Paracetamol 500mg", unit="tablets", low=50, target=200):
        response = self.client.post("/api/v1/supplies", json={
            "name": name, "unit": unit, "low_stock_threshold": low, "target_level": target}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def move(self, item_id, kind, quantity, movement_date="2026-10-09", note=None):
        return self.client.post(f"/api/v1/supplies/{item_id}/movements", json={
            "kind": kind, "quantity": quantity, "movement_date": movement_date, "note": note}, headers=self.headers)

    def get(self, item_id):
        return self.client.get(f"/api/v1/supplies/{item_id}", headers=self.headers).json()

    def test_stock_is_the_sum_of_movements(self):
        item = self.item()
        self.assertEqual(self.move(item["id"], "received", 100).status_code, 201)
        self.assertEqual(self.move(item["id"], "distributed", 30).json()["quantity"], -30)
        self.assertEqual(self.move(item["id"], "adjusted", -5, note="count").status_code, 201)
        current = self.get(item["id"])
        self.assertEqual((current["on_hand"], current["low"]), (65, False))
        history = self.client.get(f"/api/v1/supplies/{item['id']}/movements", headers=self.headers).json()
        self.assertEqual(history["total"], 3)
        self.assertEqual(history["items"][0]["recorded_by_name"], "Test User")

    def test_cannot_take_more_than_is_in_stock(self):
        item = self.item()
        self.move(item["id"], "received", 10)
        for kind, quantity in (("distributed", 11), ("adjusted", -11)):
            response = self.move(item["id"], kind, quantity)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"], ["quantity: only 10 tablets in stock"])
        self.assertEqual(self.get(item["id"])["on_hand"], 10)

    def test_rejects_bad_movements(self):
        item = self.item()
        self.assertEqual(self.move(item["id"], "received", 0).json()["detail"], ["quantity: must be more than 0"])
        self.assertEqual(self.move(item["id"], "adjusted", 0).json()["detail"], ["quantity: an adjustment cannot be 0"])
        self.assertEqual(self.move(item["id"], "received", 5, movement_date="2026-10-11").json()["detail"],
                         ["movement_date: cannot be in the future"])
        self.assertEqual(self.move("nope", "received", 5).status_code, 404)

    def test_low_stock_and_request_list(self):
        low = self.item(name="ORS sachets", unit="sachets", low=50, target=200)
        self.move(low["id"], "received", 40)
        ok = self.item(name="Iron tablets")
        self.move(ok["id"], "received", 500)
        self.assertTrue(self.get(low["id"])["low"])
        request = self.client.get("/api/v1/supplies/request-list", headers=self.headers).json()
        self.assertEqual([(r["name"], r["request_quantity"]) for r in request], [("ORS sachets", 160)])

    def test_item_rules(self):
        self.item()
        duplicate = self.client.post("/api/v1/supplies", json={
            "name": "paracetamol 500MG", "unit": "tablets", "low_stock_threshold": 1, "target_level": 2},
            headers=self.headers)
        self.assertEqual(duplicate.status_code, 409)
        bad = self.client.post("/api/v1/supplies", json={
            "name": "Gauze", "unit": "rolls", "low_stock_threshold": 20, "target_level": 10}, headers=self.headers)
        self.assertEqual(bad.json()["detail"], ["target_level: must be at least the low-stock level"])

    def test_update_and_deactivate(self):
        item = self.item()
        response = self.client.patch(f"/api/v1/supplies/{item['id']}", json={"low_stock_threshold": 5, "active": False},
                                     headers=self.headers)
        self.assertEqual((response.json()["low_stock_threshold"], response.json()["active"]), (5, False))
        self.assertEqual(self.client.get("/api/v1/supplies", headers=self.headers).json(), [])
        self.assertEqual(len(self.client.get("/api/v1/supplies?include_inactive=true", headers=self.headers).json()), 1)
```

- [ ] **Step 2: Run them and check they fail**

Run: `.venv/Scripts/python -m unittest tests.test_supplies`

Expected: FAIL. `POST /api/v1/supplies` returns 404, so `test_item_rules` and the others fail at `assertEqual(response.status_code, 201)`.

- [ ] **Step 3: Implement**

`backend/core/supplies.py`:

```python
"""Medicine and supply stock. On-hand stock is always the sum of recorded movements."""
import sqlite3
import uuid

from core import clock
from core.errors import ApiError

ITEM_SELECT = (
    "SELECT i.id, i.name, i.unit, i.low_stock_threshold, i.target_level, i.active, i.created_at, i.updated_at, "
    "COALESCE((SELECT sum(m.quantity) FROM supply_movements m WHERE m.item_id = i.id), 0) AS on_hand "
    "FROM supply_items i"
)
MOVEMENT_SELECT = (
    "SELECT m.id, m.item_id, m.kind, m.quantity, m.movement_date, m.note, m.recorded_by, "
    "u.full_name AS recorded_by_name, m.created_at FROM supply_movements m JOIN users u ON u.id = m.recorded_by"
)
EDITABLE = ("name", "unit", "low_stock_threshold", "target_level", "active")


def _item(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["active"] = bool(item["active"])
    item["low"] = item["on_hand"] <= item["low_stock_threshold"]
    return item


def list_items(conn, include_inactive: bool) -> list[dict]:
    where = "" if include_inactive else "WHERE i.active = 1"
    return [_item(r) for r in conn.execute(f"{ITEM_SELECT} {where} ORDER BY i.name COLLATE NOCASE")]


def get_item(conn, item_id: str) -> dict | None:
    row = conn.execute(f"{ITEM_SELECT} WHERE i.id = ?", (item_id,)).fetchone()
    return _item(row) if row is not None else None


def _check_levels(low: int, target: int) -> None:
    if target < low:
        raise ApiError(422, ["target_level: must be at least the low-stock level"])


def create_item(conn, data: dict) -> dict:
    _check_levels(data["low_stock_threshold"], data["target_level"])
    item_id = str(uuid.uuid4())
    try:
        with conn:
            conn.execute(
                "INSERT INTO supply_items (id, name, unit, low_stock_threshold, target_level) VALUES (?, ?, ?, ?, ?)",
                (item_id, data["name"], data["unit"], data["low_stock_threshold"], data["target_level"]))
    except sqlite3.IntegrityError as exc:
        raise ApiError(409, "An item with this name already exists") from exc
    return get_item(conn, item_id)


def update_item(conn, item_id: str, changes: dict) -> dict | None:
    item = get_item(conn, item_id)
    if item is None:
        return None
    fields = {key: changes[key] for key in EDITABLE if changes.get(key) is not None}
    _check_levels(fields.get("low_stock_threshold", item["low_stock_threshold"]),
                  fields.get("target_level", item["target_level"]))
    if fields:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        try:
            with conn:
                conn.execute(f"UPDATE supply_items SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                             (*fields.values(), item_id))
        except sqlite3.IntegrityError as exc:
            raise ApiError(409, "An item with this name already exists") from exc
    return get_item(conn, item_id)


def record_movement(conn, item_id: str, data: dict, user_id: str) -> dict | None:
    item = get_item(conn, item_id)
    if item is None:
        return None
    kind, quantity = data["kind"], data["quantity"]
    if kind == "adjusted":
        if quantity == 0:
            raise ApiError(422, ["quantity: an adjustment cannot be 0"])
        change = quantity
    else:
        if quantity <= 0:
            raise ApiError(422, ["quantity: must be more than 0"])
        change = -quantity if kind == "distributed" else quantity
    if data["movement_date"] > clock.today():
        raise ApiError(422, ["movement_date: cannot be in the future"])
    movement_id = str(uuid.uuid4())
    conn.execute("BEGIN IMMEDIATE")  # read and write the stock level in one step
    try:
        on_hand = conn.execute("SELECT COALESCE(sum(quantity), 0) FROM supply_movements WHERE item_id = ?",
                               (item_id,)).fetchone()[0]
        if on_hand + change < 0:
            raise ApiError(422, [f"quantity: only {on_hand} {item['unit']} in stock"])
        conn.execute(
            "INSERT INTO supply_movements (id, item_id, kind, quantity, movement_date, note, recorded_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (movement_id, item_id, kind, change, data["movement_date"].isoformat(), data.get("note"), user_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return dict(conn.execute(f"{MOVEMENT_SELECT} WHERE m.id = ?", (movement_id,)).fetchone())


def list_movements(conn, item_id: str, limit: int, offset: int) -> dict | None:
    if get_item(conn, item_id) is None:
        return None
    total = conn.execute("SELECT count(*) FROM supply_movements WHERE item_id = ?", (item_id,)).fetchone()[0]
    rows = conn.execute(
        f"{MOVEMENT_SELECT} WHERE m.item_id = ? ORDER BY m.movement_date DESC, m.created_at DESC, m.rowid DESC "
        "LIMIT ? OFFSET ?", (item_id, limit, offset))
    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def request_list(conn) -> list[dict]:
    return [{**item, "request_quantity": max(item["target_level"] - item["on_hand"], 0)}
            for item in list_items(conn, include_inactive=False) if item["low"]]
```

`backend/routes/supplies.py`:

```python
"""Medicine and supply inventory."""
import sqlite3
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from core.auth import AuthContext, current_user
from core.storage import get_db
from core.supplies import create_item, get_item, list_items, list_movements, record_movement, request_list, update_item

router = APIRouter()


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class SupplyItem(BaseModel):
    id: str
    name: str
    unit: str
    low_stock_threshold: int
    target_level: int
    active: bool
    on_hand: int
    low: bool
    created_at: str
    updated_at: str


class RequestItem(SupplyItem):
    request_quantity: int


class SupplyItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=40)
    low_stock_threshold: int = Field(ge=0, le=1_000_000)
    target_level: int = Field(ge=0, le=1_000_000)

    @field_validator("name", "unit")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        return _strip(value)


class SupplyItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    low_stock_threshold: int | None = Field(default=None, ge=0, le=1_000_000)
    target_level: int | None = Field(default=None, ge=0, le=1_000_000)
    active: bool | None = None

    @field_validator("name", "unit")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        return _strip(value)


class MovementCreate(BaseModel):
    kind: Literal["received", "distributed", "adjusted"]
    quantity: int = Field(ge=-1_000_000, le=1_000_000)
    movement_date: date
    note: str | None = Field(default=None, max_length=500)


class Movement(BaseModel):
    id: str
    item_id: str
    kind: Literal["received", "distributed", "adjusted"]
    quantity: int
    movement_date: str
    note: str | None
    recorded_by: str
    recorded_by_name: str
    created_at: str


class MovementPage(BaseModel):
    items: list[Movement]
    total: int
    limit: int
    offset: int


def _found(item):
    if item is None:
        raise HTTPException(status_code=404, detail="Supply item not found")
    return item


@router.get("/supplies", response_model=list[SupplyItem], operation_id="listSupplies")
def supplies(include_inactive: bool = False, db: sqlite3.Connection = Depends(get_db)):
    return list_items(db, include_inactive)


@router.post("/supplies", response_model=SupplyItem, status_code=status.HTTP_201_CREATED, operation_id="createSupply")
def new_supply(data: SupplyItemCreate, db: sqlite3.Connection = Depends(get_db)):
    return create_item(db, data.model_dump())


@router.get("/supplies/request-list", response_model=list[RequestItem], operation_id="supplyRequestList")
def supply_request_list(db: sqlite3.Connection = Depends(get_db)):
    return request_list(db)


@router.get("/supplies/{item_id}", response_model=SupplyItem, operation_id="getSupply")
def supply_detail(item_id: str, db: sqlite3.Connection = Depends(get_db)):
    return _found(get_item(db, item_id))


@router.patch("/supplies/{item_id}", response_model=SupplyItem, operation_id="updateSupply")
def change_supply(item_id: str, data: SupplyItemUpdate, db: sqlite3.Connection = Depends(get_db)):
    return _found(update_item(db, item_id, data.model_dump(exclude_unset=True)))


@router.get("/supplies/{item_id}/movements", response_model=MovementPage, operation_id="listSupplyMovements")
def movements(item_id: str, limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0),
              db: sqlite3.Connection = Depends(get_db)):
    return _found(list_movements(db, item_id, limit, offset))


@router.post("/supplies/{item_id}/movements", response_model=Movement, status_code=status.HTTP_201_CREATED,
             operation_id="recordSupplyMovement")
def new_movement(item_id: str, data: MovementCreate, auth: AuthContext = Depends(current_user),
                 db: sqlite3.Connection = Depends(get_db)):
    return _found(record_movement(db, item_id, data.model_dump(), auth.user["id"]))
```

In `backend/api.py`, add `from routes.supplies import router as supplies_router` and this line after the referrals router:

```python
app.include_router(supplies_router, prefix="/api/v1", dependencies=signed_in, tags=["supplies"])
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `.venv/Scripts/python -m unittest tests.test_supplies`

Expected: 6 tests OK.

- [ ] **Step 5: Stop. No git operations.**

---

### Task 3: Sync state, transfer files and RHU receipts (backend)

**Files:**
- Create: `backend/core/sync_state.py`, `backend/routes/sync.py`, `backend/scripts/rhu_receipt.py`, `backend/tests/test_sync.py`
- Modify: `backend/api.py`

**Interfaces:**
- Consumes: `core.sync.create_sync_bundle(records, station_id, secret)` and `core.sync.derive_key(secret, salt)`.
- Produces:
  - `sync_state.unsynced_count(conn) -> int`, used by Task 4.
  - `sync_state.make_receipt(bundle, passphrase) -> dict`.
  - `GET /sync/status` → `{station_id, passphrase_set, records: {type: {pending, awaiting, synced}}, last_acknowledged_at, open_bundles}`
  - `PUT /sync/settings {passphrase}` (admin, 204)
  - `GET /sync/bundles`, `POST /sync/bundles` (admin, 201, returns the bundle JSON) and `GET /sync/bundles/{id}` (admin)
  - `POST /sync/receipts` (admin) → bundle summary

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_sync.py`:

```python
"""Manual transfer: pending records, encrypted transfer files and signed RHU receipts."""
import json
import tempfile
from pathlib import Path

from core.storage import connect
from core.sync_state import make_receipt
from scripts.rhu_receipt import write_receipt
from tests.api_case import VisitTestCase

PASSPHRASE = "rhu-shared-secret-123"


class SyncTestCase(VisitTestCase):
    def setUp(self):
        super().setUp()
        self.visit = self.create_visit(status="final").json()
        self.referral = self.client.post("/api/v1/referrals", json={
            "patient_id": self.patient_id, "facility": "RHU", "reason": "BP", "urgency": "urgent"},
            headers=self.headers).json()

    def set_passphrase(self, passphrase=PASSPHRASE, headers=None):
        return self.client.put("/api/v1/sync/settings", json={"passphrase": passphrase},
                               headers=headers or self.headers)

    def status(self):
        return self.client.get("/api/v1/sync/status", headers=self.headers).json()

    def export(self):
        return self.client.post("/api/v1/sync/bundles", headers=self.headers)

    def receipt(self, receipt):
        return self.client.post("/api/v1/sync/receipts", json=receipt, headers=self.headers)


class ExportTests(SyncTestCase):
    def test_new_records_are_pending(self):
        records = self.status()["records"]
        self.assertEqual(records["household"]["pending"], 1)
        self.assertEqual(records["patient"]["pending"], 1)
        self.assertEqual(records["visit"]["pending"], 1)
        self.assertEqual(records["referral"]["pending"], 1)

    def test_drafts_are_not_transferred(self):
        self.create_visit()  # draft
        self.assertEqual(self.status()["records"]["visit"]["pending"], 1)

    def test_export_needs_a_passphrase_set_by_an_admin(self):
        self.assertEqual(self.export().json()["detail"], ["passphrase: set the RHU passphrase in Sync settings first"])
        self.assertEqual(self.set_passphrase("short").status_code, 422)
        volunteer = self.active_volunteer(self.token)
        self.assertTrue(volunteer)
        volunteer_headers = self.bearer(self.token_for("bhw.ben"))
        self.assertEqual(self.set_passphrase(headers=volunteer_headers).status_code, 403)
        self.assertEqual(self.set_passphrase().status_code, 204)
        self.assertTrue(self.status()["passphrase_set"])

    def test_export_moves_records_to_awaiting_and_hides_identities(self):
        self.set_passphrase()
        response = self.export()
        self.assertEqual(response.status_code, 201, response.text)
        bundle = response.json()
        self.assertEqual(bundle["record_count"], 4)
        payload = json.dumps(bundle["payload"])
        for secret in ("Ana Dela Cruz", "09171234567", "San Roque", "Malinis", "Purok 2"):
            self.assertNotIn(secret, payload)
        records = self.status()["records"]
        self.assertEqual((records["visit"]["pending"], records["visit"]["awaiting"]), (0, 1))
        self.assertEqual(self.export().status_code, 409)  # nothing left to send
        again = self.client.get(f"/api/v1/sync/bundles/{bundle['bundle_id']}", headers=self.headers).json()
        self.assertEqual(again["bundle_id"], bundle["bundle_id"])


class ReceiptTests(SyncTestCase):
    def setUp(self):
        super().setUp()
        self.set_passphrase()
        self.bundle = self.export().json()

    def test_valid_receipt_marks_records_synced_and_referrals_sent(self):
        response = self.receipt(make_receipt(self.bundle, PASSPHRASE))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(response.json()["acknowledged_at"])
        status = self.status()
        self.assertEqual(status["records"]["visit"], {"pending": 0, "awaiting": 0, "synced": 1})
        self.assertIsNotNone(status["last_acknowledged_at"])
        referral = self.client.get(f"/api/v1/referrals/{self.referral['id']}", headers=self.headers).json()
        self.assertEqual(referral["status"], "sent")
        self.assertEqual(self.status()["records"]["referral"]["synced"], 1)  # "sent" is not a new version
        self.assertEqual(self.receipt(make_receipt(self.bundle, PASSPHRASE)).status_code, 200)  # idempotent

    def test_bad_receipts_change_nothing(self):
        good = make_receipt(self.bundle, PASSPHRASE)
        cases = [
            ({**good, "signature": make_receipt(self.bundle, "some-other-passphrase")["signature"]},
             "signature: this receipt was not signed with this device's RHU passphrase"),
            ({**good, "record_count": 99}, "record_count: does not match the transfer file"),
            ({**good, "bundle_id": "nope"}, "bundle_id: no transfer file with this ID was made on this device"),
            ({**good, "format": "x"}, "format: this is not a GitKeepers RHU receipt"),
        ]
        for receipt, message in cases:
            response = self.receipt(receipt)
            self.assertEqual((response.status_code, response.json()["detail"]), (422, [message]))
        self.assertEqual(self.status()["records"]["visit"]["awaiting"], 1)

    def test_a_record_edited_after_export_is_pending_again(self):
        db = connect()
        try:
            with db:
                db.execute("UPDATE patients SET updated_at = '2099-01-01 00:00:00'")
        finally:
            db.close()
        self.receipt(make_receipt(self.bundle, PASSPHRASE))
        records = self.status()["records"]
        self.assertEqual((records["patient"]["pending"], records["patient"]["synced"]), (1, 0))
        self.assertEqual(self.export().json()["record_count"], 1)

    def test_rhu_script_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "transfer.json"
            path.write_text(json.dumps(self.bundle), encoding="utf-8")
            receipt_path = write_receipt(path, PASSPHRASE)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(self.receipt(receipt).status_code, 200)
        listed = self.client.get("/api/v1/sync/bundles", headers=self.headers).json()
        self.assertEqual(listed[0]["record_count"], 4)
        self.assertIsNotNone(listed[0]["acknowledged_at"])
```

- [ ] **Step 2: Run them and check they fail**

Run: `.venv/Scripts/python -m unittest tests.test_sync`

Expected: ERROR, `ModuleNotFoundError: No module named 'core.sync_state'`.

- [ ] **Step 3: Implement**

`backend/core/sync_state.py`:

```python
"""What still has to reach the RHU, and the manual transfer files that carry it.

A record's sync state is derived from the transfer files that included it at its current
version (`updated_at`): synced once the RHU acknowledged such a file, awaiting while that file
is unacknowledged, otherwise pending. Editing a record after export makes it pending again.
"""
import hashlib
import hmac
import json
import sqlite3
import uuid

from core.errors import ApiError
from core.sync import create_sync_bundle, derive_key

RECEIPT_FORMAT = "gitkeepers-receipt-v1"
# Column aliases matter: core.pseudonymize masks values by key (full_name, contact_number,
# barangay, sitio, address, note/notes), so identifying columns use those names.
RECORD_SOURCES = {
    "household": "SELECT id, barangay, sitio, address_line AS address, contact_number, created_at, updated_at "
                 "FROM households",
    "patient": "SELECT id, household_id, full_name, birth_date, sex, relationship_to_head, contact_number, "
               "is_household_head, created_at, updated_at FROM patients",
    "visit": "SELECT id, patient_id, form_type, visit_date, values_json, sources_json, note, finalized_at, "
             "created_at, updated_at FROM visits WHERE status = 'final'",
    "follow_up": "SELECT id, patient_id, source_visit_id, form_type, due_date, reason, status, completed_visit_id, "
                 "completed_at, created_at, updated_at FROM follow_ups",
    "referral": "SELECT id, patient_id, flag_id, facility, reason, urgency, notes, created_at, updated_at "
                "FROM referrals",
    "supply_item": "SELECT id, name AS item_name, unit, low_stock_threshold, target_level, active, created_at, "
                   "updated_at FROM supply_items",
    "supply_movement": "SELECT id, item_id, kind, quantity, movement_date, note, created_at, updated_at "
                       "FROM supply_movements",
}
_IN_BUNDLE = (
    "EXISTS (SELECT 1 FROM sync_bundle_records r JOIN sync_bundles b ON b.id = r.bundle_id "
    "WHERE r.record_type = ? AND r.record_id = t.id AND r.record_updated_at = t.updated_at "
    "AND b.acknowledged_at IS {})"
)


def get_setting(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def set_setting(conn, key: str, value: str) -> None:
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def station_id(conn) -> str:
    current = get_setting(conn, "station_id")
    if current is None:
        current = f"station-{uuid.uuid4().hex[:8]}"
        set_setting(conn, "station_id", current)
    return current


def _rows(conn, record_type: str) -> list[sqlite3.Row]:
    sql = (f"SELECT t.*, {_IN_BUNDLE.format('NOT NULL')} AS synced, {_IN_BUNDLE.format('NULL')} AS awaiting "
           f"FROM ({RECORD_SOURCES[record_type]}) t")
    return conn.execute(sql, (record_type, record_type)).fetchall()


def counts(conn) -> dict[str, dict[str, int]]:
    result = {}
    for record_type in RECORD_SOURCES:
        rows = _rows(conn, record_type)
        synced = sum(1 for r in rows if r["synced"])
        awaiting = sum(1 for r in rows if r["awaiting"] and not r["synced"])
        result[record_type] = {"pending": len(rows) - synced - awaiting, "awaiting": awaiting, "synced": synced}
    return result


def unsynced_count(conn) -> int:
    return sum(c["pending"] + c["awaiting"] for c in counts(conn).values())


def pending_records(conn) -> list[dict]:
    records = []
    for record_type in RECORD_SOURCES:
        for row in _rows(conn, record_type):
            if row["synced"] or row["awaiting"]:
                continue
            data = {key: row[key] for key in row.keys() if key not in ("synced", "awaiting")}
            records.append({"record_type": record_type, "record_id": row["id"], "version": row["updated_at"],
                            "data": data})
    return records


def receipt_signature(passphrase: str, bundle_id: str, record_count: int) -> str:
    key = derive_key(passphrase, salt=b"gitkeepers-receipt-salt")
    return hmac.new(key, f"{bundle_id}:{record_count}".encode(), hashlib.sha256).hexdigest()


def make_receipt(bundle: dict, passphrase: str) -> dict:
    """What the RHU sends back after storing a transfer file (see scripts/rhu_receipt.py)."""
    return {"format": RECEIPT_FORMAT, "bundle_id": bundle["bundle_id"], "station_id": bundle["station_id"],
            "record_count": bundle["record_count"],
            "signature": receipt_signature(passphrase, bundle["bundle_id"], bundle["record_count"])}


def create_bundle(conn, user_id: str) -> dict:
    passphrase = get_setting(conn, "sync_passphrase")
    if not passphrase:
        raise ApiError(422, ["passphrase: set the RHU passphrase in Sync settings first"])
    station = station_id(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        records = pending_records(conn)
        if not records:
            raise ApiError(409, "Nothing to transfer: every record is synced or waiting for an RHU receipt")
        bundle_id = str(uuid.uuid4())
        bundle = create_sync_bundle(records, station, passphrase)
        bundle["bundle_id"] = bundle_id
        conn.execute("INSERT INTO sync_bundles (id, record_count, bundle_json, created_by) VALUES (?, ?, ?, ?)",
                     (bundle_id, len(records), json.dumps(bundle, ensure_ascii=False), user_id))
        conn.executemany(
            "INSERT INTO sync_bundle_records (bundle_id, record_type, record_id, record_updated_at) VALUES (?, ?, ?, ?)",
            [(bundle_id, r["record_type"], r["record_id"], r["version"]) for r in records])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return bundle


BUNDLE_SELECT = (
    "SELECT b.id, b.record_count, b.created_at, b.acknowledged_at, u.full_name AS created_by_name "
    "FROM sync_bundles b JOIN users u ON u.id = b.created_by"
)


def list_bundles(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(f"{BUNDLE_SELECT} ORDER BY b.created_at DESC, b.rowid DESC LIMIT 50")]


def bundle_file(conn, bundle_id: str) -> dict | None:
    row = conn.execute("SELECT bundle_json FROM sync_bundles WHERE id = ?", (bundle_id,)).fetchone()
    return json.loads(row["bundle_json"]) if row is not None else None


def accept_receipt(conn, receipt: dict) -> dict:
    if receipt.get("format") != RECEIPT_FORMAT:
        raise ApiError(422, ["format: this is not a GitKeepers RHU receipt"])
    row = conn.execute("SELECT id, record_count, acknowledged_at FROM sync_bundles WHERE id = ?",
                       (str(receipt.get("bundle_id")),)).fetchone()
    if row is None:
        raise ApiError(422, ["bundle_id: no transfer file with this ID was made on this device"])
    if receipt.get("record_count") != row["record_count"]:
        raise ApiError(422, ["record_count: does not match the transfer file"])
    passphrase = get_setting(conn, "sync_passphrase") or ""
    expected = receipt_signature(passphrase, row["id"], row["record_count"])
    if not passphrase or not hmac.compare_digest(str(receipt.get("signature", "")), expected):
        raise ApiError(422, ["signature: this receipt was not signed with this device's RHU passphrase"])
    if row["acknowledged_at"] is None:
        with conn:
            conn.execute("UPDATE sync_bundles SET acknowledged_at = datetime('now') WHERE id = ?", (row["id"],))
            # Status only: updated_at stays, so a sent referral does not need transferring again.
            conn.execute(
                "UPDATE referrals SET status = 'sent' WHERE status = 'issued' AND id IN "
                "(SELECT record_id FROM sync_bundle_records WHERE bundle_id = ? AND record_type = 'referral')",
                (row["id"],))
    return dict(conn.execute(f"{BUNDLE_SELECT} WHERE b.id = ?", (row["id"],)).fetchone())


def status(conn) -> dict:
    return {
        "station_id": station_id(conn),
        "passphrase_set": bool(get_setting(conn, "sync_passphrase")),
        "records": counts(conn),
        "last_acknowledged_at": conn.execute("SELECT max(acknowledged_at) FROM sync_bundles").fetchone()[0],
        "open_bundles": conn.execute("SELECT count(*) FROM sync_bundles WHERE acknowledged_at IS NULL").fetchone()[0],
    }
```

`backend/routes/sync.py`:

```python
"""Manual transfer to the RHU: status, transfer files and receipts."""
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from core.auth import AuthContext, require_admin
from core.storage import get_db
from core.sync_state import accept_receipt, bundle_file, create_bundle, list_bundles, set_setting
from core.sync_state import status as sync_status

router = APIRouter()


class SyncCounts(BaseModel):
    pending: int
    awaiting: int
    synced: int


class SyncStatus(BaseModel):
    station_id: str
    passphrase_set: bool
    records: dict[str, SyncCounts]
    last_acknowledged_at: str | None
    open_bundles: int


class SyncSettings(BaseModel):
    passphrase: str = Field(min_length=12, max_length=200)


class BundleSummary(BaseModel):
    id: str
    record_count: int
    created_at: str
    acknowledged_at: str | None
    created_by_name: str


@router.get("/sync/status", response_model=SyncStatus, operation_id="getSyncStatus")
def get_status(db: sqlite3.Connection = Depends(get_db)):
    return sync_status(db)


@router.put("/sync/settings", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)],
            operation_id="updateSyncSettings")
def update_settings(data: SyncSettings, db: sqlite3.Connection = Depends(get_db)):
    set_setting(db, "sync_passphrase", data.passphrase)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sync/bundles", response_model=list[BundleSummary], operation_id="listSyncBundles")
def bundles(db: sqlite3.Connection = Depends(get_db)):
    return list_bundles(db)


@router.post("/sync/bundles", status_code=status.HTTP_201_CREATED, operation_id="createSyncBundle")
def new_bundle(auth: AuthContext = Depends(require_admin), db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return create_bundle(db, auth.user["id"])


@router.get("/sync/bundles/{bundle_id}", dependencies=[Depends(require_admin)], operation_id="getSyncBundle")
def get_bundle(bundle_id: str, db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    bundle = bundle_file(db, bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Transfer file not found")
    return bundle


@router.post("/sync/receipts", response_model=BundleSummary, dependencies=[Depends(require_admin)],
             operation_id="acceptSyncReceipt")
def receipts(receipt: dict[str, Any], db: sqlite3.Connection = Depends(get_db)):
    return accept_receipt(db, receipt)
```

`backend/scripts/rhu_receipt.py`:

```python
"""RHU side of a manual transfer: check a GitKeepers transfer file and write its signed receipt.

Run from backend/:
    RHU_PASSPHRASE=... python -m scripts.rhu_receipt path/to/transfer.json
The passphrase comes from the environment so it does not end up in shell history.
"""
import json
import os
import sys
from pathlib import Path

from core.sync import unpack_and_resolve_bundle
from core.sync_state import make_receipt


def write_receipt(bundle_path: Path, passphrase: str) -> Path:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    records = unpack_and_resolve_bundle(bundle, passphrase)  # raises if the passphrase is wrong
    if len(records) != bundle["record_count"]:
        raise ValueError("record count does not match the payload")
    receipt_path = bundle_path.with_name(f"{bundle_path.stem}.receipt.json")
    receipt_path.write_text(json.dumps(make_receipt(bundle, passphrase), indent=2), encoding="utf-8")
    return receipt_path


if __name__ == "__main__":
    secret = os.environ.get("RHU_PASSPHRASE")
    if len(sys.argv) != 2 or not secret:
        sys.exit("usage: RHU_PASSPHRASE=... python -m scripts.rhu_receipt TRANSFER_FILE.json")
    print("wrote", write_receipt(Path(sys.argv[1]), secret))
```

In `backend/api.py`, add `from routes.sync import router as sync_router` and this line after the supplies router:

```python
app.include_router(sync_router, prefix="/api/v1", dependencies=signed_in, tags=["sync"])
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `.venv/Scripts/python -m unittest tests.test_sync`

Expected: 8 tests OK.

- [ ] **Step 5: Stop. No git operations.**

---

### Task 4: Reports, AI drafts and dashboard counts (backend)

**Files:**
- Create: `backend/core/reports.py`, `backend/routes/reports.py`, `backend/tests/test_reports.py`
- Modify:
  - `backend/core/dashboard.py`, `backend/routes/dashboard.py`
  - `backend/tests/fakes.py` (add `generate`)
  - `backend/tests/test_dashboard.py` (one new test)
  - `backend/api.py`

**Interfaces:**
- Consumes:
  - `sync_state.unsynced_count`
  - `supplies.list_items`
  - `assist.MODEL_LOCK`, `AIUnavailable` and `get_assist_llm`
  - `extraction.strip_think`
- Produces:
  - `GET /reports/summary?period=week|month&date=` → `{period, current, previous, unsynced_records}`
  - `GET /reports/drafts?period=&date=`
  - `POST /reports/drafts {period, date}` (AI, 201 or 503)
  - `POST /reports/drafts/manual {period, date, text}` (201)
  - `PATCH /reports/drafts/{id} {text?, status?: "approved"}`
  - Dashboard gains `referral_flags_open`, `low_stock` and `unsynced`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/fakes.py`, inside `FakeLLM`:

```python
    def generate(self, prompt, max_tokens=256):
        self.calls.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(prompt) if callable(self.reply) else self.reply
```

`backend/tests/test_reports.py`:

```python
"""Weekly/monthly summaries and AI-assisted program-needs drafts."""
from datetime import date

from core.reports import period_bounds
from tests.api_case import VisitTestCase
from tests.fakes import FakeLLM


class PeriodTests(VisitTestCase):
    def test_week_runs_monday_to_sunday_and_month_covers_the_calendar_month(self):
        self.assertEqual(period_bounds("week", date(2026, 10, 10)), (date(2026, 10, 5), date(2026, 10, 11)))
        self.assertEqual(period_bounds("month", date(2026, 2, 14)), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(period_bounds("month", date(2026, 12, 31)), (date(2026, 12, 1), date(2026, 12, 31)))


class SummaryTests(VisitTestCase):
    def summary(self, query="?period=week&date=2026-10-10"):
        response = self.client.get(f"/api/v1/reports/summary{query}", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_counts_current_and_previous_period(self):
        self.create_visit(status="final", values={"bp_systolic": 190, "bp_diastolic": 100})  # 2026-10-10
        self.create_visit(visit_date="2026-10-01", status="final")  # previous week
        self.client.post("/api/v1/referrals", json={"patient_id": self.patient_id, "facility": "RHU",
                                                    "reason": "Very high BP", "urgency": "urgent"}, headers=self.headers)
        item = self.client.post("/api/v1/supplies", json={"name": "ORS", "unit": "sachets",
                                                          "low_stock_threshold": 10, "target_level": 50},
                                headers=self.headers).json()
        self.client.post(f"/api/v1/supplies/{item['id']}/movements", json={
            "kind": "received", "quantity": 20, "movement_date": "2026-10-06"}, headers=self.headers)
        self.client.post(f"/api/v1/supplies/{item['id']}/movements", json={
            "kind": "distributed", "quantity": 15, "movement_date": "2026-10-07"}, headers=self.headers)
        report = self.summary()
        current, previous = report["current"], report["previous"]
        self.assertEqual((current["start"], current["end"]), ("2026-10-05", "2026-10-11"))
        self.assertEqual((current["visits"]["total"], previous["visits"]["total"]), (1, 1))
        self.assertEqual(current["visits"]["by_form"], {"bp_followup": 1})
        self.assertEqual((current["referral_flags"], current["referrals_issued"]), (1, 1))
        self.assertEqual(current["referrals_by_reason"], {"Very high BP": 1})
        self.assertEqual(current["supplies"], [{"name": "ORS", "unit": "sachets", "received": 20, "distributed": 15}])
        self.assertEqual(current["low_stock_items"], ["ORS"])
        self.assertEqual(previous["low_stock_items"], ["ORS"])  # nothing had arrived yet
        self.assertGreater(report["unsynced_records"], 0)

    def test_month_period_and_default_date(self):
        self.create_visit(visit_date="2026-10-01", status="final")
        self.assertEqual(self.summary("?period=month&date=2026-10-20")["current"]["visits"]["total"], 1)
        self.assertEqual(self.summary("?period=month")["current"]["start"], "2026-10-01")
        bad = self.client.get("/api/v1/reports/summary?period=year", headers=self.headers)
        self.assertEqual(bad.status_code, 422)


class DraftTests(VisitTestCase):
    def ai_draft(self, llm):
        self.use_llm(llm)
        return self.client.post("/api/v1/reports/drafts", json={"period": "week", "date": "2026-10-10"},
                                headers=self.headers)

    def test_ai_draft_sees_only_totals(self):
        self.create_visit(status="final", note="Ana Dela Cruz said she is dizzy")
        llm = FakeLLM("<think>hmm</think>Consider a BP screening day.")
        response = self.ai_draft(llm)
        self.assertEqual(response.status_code, 201, response.text)
        draft = response.json()
        self.assertEqual((draft["text"], draft["status"], draft["model"]), ("Consider a BP screening day.", "draft", "fake-model"))
        prompt = llm.calls[0]
        self.assertIn('"total": 1', prompt)
        for secret in ("Ana", "dizzy", self.patient_id):
            self.assertNotIn(secret, prompt)

    def test_ai_failures_are_503(self):
        for llm in (FakeLLM(RuntimeError("boom")), FakeLLM("   ")):
            self.assertEqual(self.ai_draft(llm).status_code, 503)
        app_without_model = self.client.post("/api/v1/reports/drafts", json={"period": "week", "date": "2026-10-10"},
                                              headers=self.headers)
        self.assertEqual(app_without_model.status_code, 503)

    def test_manual_draft_edit_and_approve(self):
        response = self.client.post("/api/v1/reports/drafts/manual", json={
            "period": "month", "date": "2026-10-10", "text": "More prenatal visits needed."}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        draft = response.json()
        self.assertIsNone(draft["model"])
        patch = lambda **body: self.client.patch(f"/api/v1/reports/drafts/{draft['id']}", json=body, headers=self.headers)
        self.assertEqual(patch(text="  ").json()["detail"], ["text: cannot be empty"])
        approved = patch(text="Edited.", status="approved").json()
        self.assertEqual((approved["text"], approved["status"]), ("Edited.", "approved"))
        self.assertEqual(patch(text="again").status_code, 409)
        listed = self.client.get("/api/v1/reports/drafts?period=month&date=2026-10-31", headers=self.headers).json()
        self.assertEqual([d["id"] for d in listed], [draft["id"]])
        empty = self.client.post("/api/v1/reports/drafts/manual", json={
            "period": "month", "date": "2026-10-10", "text": " "}, headers=self.headers)
        self.assertEqual(empty.json()["detail"], ["text: write the summary first"])
```

Add to `backend/tests/test_dashboard.py`, inside `DashboardTests`:

```python
    def test_referral_supply_and_sync_counts(self):
        self.create_visit(status="final", values={"bp_systolic": 190, "bp_diastolic": 100})
        item = self.client.post("/api/v1/supplies", json={"name": "ORS", "unit": "sachets",
                                                          "low_stock_threshold": 10, "target_level": 50},
                                headers=self.headers).json()
        self.assertTrue(item["low"])
        summary = self.dashboard()
        self.assertEqual((summary["referral_flags_open"], summary["low_stock"]), (1, 1))
        self.assertGreater(summary["unsynced"], 0)
```

- [ ] **Step 2: Run them and check they fail**

Run: `.venv/Scripts/python -m unittest tests.test_reports tests.test_dashboard`

Expected: ERROR, `No module named 'core.reports'`, and the dashboard test fails with `KeyError: 'referral_flags_open'`.

- [ ] **Step 3: Implement**

`backend/core/reports.py`:

```python
"""Weekly and monthly summaries, and AI-drafted program-needs text for professional review.

The model only ever sees aggregated counts: no names, notes or record IDs.
"""
import json
import sqlite3
import uuid
from datetime import date, timedelta

from core import sync_state
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
    by_reason = {row[0]: row[1] for row in conn.execute(
        "SELECT reason, count(*) FROM referrals WHERE date(created_at) BETWEEN ? AND ? "
        "GROUP BY reason ORDER BY count(*) DESC, reason", (s, e))}
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
        "new_households": _count(conn, "SELECT count(*) FROM households WHERE date(created_at) BETWEEN ? AND ?", s, e),
        "new_patients": _count(conn, "SELECT count(*) FROM patients WHERE date(created_at) BETWEEN ? AND ?", s, e),
        "follow_ups_completed": _count(conn, "SELECT count(*) FROM follow_ups WHERE status = 'completed' "
                                             "AND date(completed_at) BETWEEN ? AND ?", s, e),
        "follow_ups_overdue": _count(conn, "SELECT count(*) FROM follow_ups WHERE status = 'scheduled' "
                                           "AND due_date <= ?", e),
        "referral_flags": _count(conn, "SELECT count(*) FROM referral_flags WHERE date(created_at) BETWEEN ? AND ?", s, e),
        "referrals_issued": _count(conn, "SELECT count(*) FROM referrals WHERE date(created_at) BETWEEN ? AND ?", s, e),
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
```

`backend/routes/reports.py`:

```python
"""Report summaries and AI-assisted drafts (reviewed and approved by a person)."""
import sqlite3
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from core import clock
from core.assist import get_assist_llm
from core.auth import AuthContext, current_user
from core.reports import create_ai_draft, create_manual_draft, list_drafts, summary, update_draft
from core.storage import get_db

router = APIRouter()
Period = Literal["week", "month"]


class DraftRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    period: Period
    day: date = Field(alias="date")


class ManualDraft(DraftRequest):
    text: str = Field(max_length=5000)


class DraftUpdate(BaseModel):
    text: str | None = Field(default=None, max_length=5000)
    status: Literal["approved"] | None = None


class ReportDraft(BaseModel):
    id: str
    period: Period
    start_date: str
    end_date: str
    figures: dict[str, Any]
    text: str
    status: Literal["draft", "approved"]
    model: str | None
    created_by: str
    approved_by: str | None
    created_at: str
    updated_at: str


@router.get("/reports/summary", operation_id="getReportSummary")
def report_summary(period: Period = "week", day: date | None = Query(default=None, alias="date"),
                   db: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return summary(db, period, day or clock.today())


@router.get("/reports/drafts", response_model=list[ReportDraft], operation_id="listReportDrafts")
def drafts(period: Period = "week", day: date | None = Query(default=None, alias="date"),
           db: sqlite3.Connection = Depends(get_db)):
    return list_drafts(db, period, day or clock.today())


@router.post("/reports/drafts", response_model=ReportDraft, status_code=status.HTTP_201_CREATED,
             operation_id="createAiReportDraft")
def ai_draft(data: DraftRequest, auth: AuthContext = Depends(current_user), db: sqlite3.Connection = Depends(get_db),
             llm=Depends(get_assist_llm)):
    return create_ai_draft(db, llm, data.period, data.day, auth.user["id"])


@router.post("/reports/drafts/manual", response_model=ReportDraft, status_code=status.HTTP_201_CREATED,
             operation_id="createManualReportDraft")
def manual_draft(data: ManualDraft, auth: AuthContext = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    return create_manual_draft(db, data.period, data.day, data.text, auth.user["id"])


@router.patch("/reports/drafts/{draft_id}", response_model=ReportDraft, operation_id="updateReportDraft")
def edit_draft(draft_id: str, data: DraftUpdate, auth: AuthContext = Depends(current_user),
               db: sqlite3.Connection = Depends(get_db)):
    draft = update_draft(db, draft_id, data.model_dump(exclude_unset=True), auth.user["id"])
    if draft is None:
        raise HTTPException(status_code=404, detail="Report draft not found")
    return draft
```

In `backend/core/dashboard.py`:
- Add the imports `from core import clock, sync_state` (replacing `from core import clock`) and `from core.supplies import list_items`.
- Add these keys to the returned dict:

```python
        "referral_flags_open": _count(conn, "SELECT count(*) FROM referral_flags WHERE status = 'open'"),
        "low_stock": sum(1 for item in list_items(conn, include_inactive=False) if item["low"]),
        "unsynced": sync_state.unsynced_count(conn),
```

In `backend/routes/dashboard.py`, add these fields to `Dashboard` after `patients: int`:

```python
    referral_flags_open: int
    low_stock: int
    unsynced: int
```

In `backend/api.py`, add `from routes.reports import router as reports_router` and this line after the sync router:

```python
app.include_router(reports_router, prefix="/api/v1", dependencies=signed_in, tags=["reports"])
```

- [ ] **Step 4: Run the tests, then the full backend suite**

Run: `.venv/Scripts/python -m unittest tests.test_reports tests.test_dashboard`

Expected: OK.

Run: `.venv/Scripts/python -m unittest discover -s tests`

Expected: OK, apart from the known pseudonymize marker test if sub-project 2's fix has not landed yet.

- [ ] **Step 5: Stop. No git operations.**

---

### Task 5: Frontend foundations (types, API module, downloads, strings, styles, nav)

**Files:**
- Create: `frontend/src/api/modules.ts`, `frontend/src/lib/download.ts`, `frontend/src/lib/download.test.ts`
- Create, then delete after merging: `frontend/src/i18n/_add.en.json`, `frontend/src/i18n/_add.fil.json`
- Modify:
  - `frontend/src/api/types.ts` (append types; extend `Dashboard`)
  - `frontend/src/test/fixtures.ts` (`dashboard` gets the new counts)
  - `frontend/src/test/setup.ts` (stub `URL.createObjectURL`)
  - `frontend/src/styles/base.css` (append)
  - `frontend/src/components/Layout.tsx` (no "Soon" tags; sync chip)
  - `frontend/src/pages/DashboardPage.tsx` (live cards)
  - `frontend/src/pages/app.test.tsx` (dashboard assertion)
- Delete: `frontend/src/pages/ComingSoonPage.tsx` and its four routes in `frontend/src/routes.tsx`

**Interfaces:**
- Produces:
  - `referralsApi`, `suppliesApi`, `reportsApi` and `syncApi` (signatures below).
  - `toCsv(rows)` and `downloadFile(name, content, type)`.
  - The new types.
  - All i18n keys used by Tasks 6–9.

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/download.test.ts`:

```ts
import { downloadFile, readText, toCsv } from "./download";

describe("downloads", () => {
  it("quotes CSV cells that need it", () => {
    expect(toCsv([["Item", "Note"], ["ORS", 'says "hi", ok'], ["Gauze", null]])).toBe(
      'Item,Note\r\nORS,"says ""hi"", ok"\r\nGauze,\r\n',
    );
  });

  it("downloads text as a file", async () => {
    downloadFile("a.csv", "x,y\r\n", "text/csv");
    const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls[0][0] as Blob;
    expect(await readText(blob)).toBe("x,y\r\n");
  });
});
```

In `frontend/src/test/setup.ts`, add after the `globalThis.Request = TestRequest;` line:

```ts
// jsdom has no object URLs; downloads only need a placeholder.
URL.createObjectURL = vi.fn(() => "blob:test");
URL.revokeObjectURL = vi.fn();
```

In the dashboard test of `frontend/src/pages/app.test.tsx`, replace the test `shows the counts and links them, but not the coming-soon cards` with:

```tsx
  it("shows the counts and links them", async () => {
    mockApi({ ...signedInAs(admin), ...homeData });
    renderApp("/", { signedIn: true });
    const overdue = (await screen.findByRole("heading", { name: "Overdue" })).closest("a");
    expect(overdue).toHaveAttribute("href", "/follow-ups?state=overdue");
    expect(within(overdue!).getByText("3")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Open referral flags" }).closest("a")).toHaveAttribute("href", "/referrals");
    expect(screen.getByRole("heading", { name: "Low-stock supplies" }).closest("a")).toHaveAttribute("href", "/supplies");
  });
```

In `frontend/src/test/fixtures.ts`, add `referral_flags_open: 2, low_stock: 1, unsynced: 5,` to the `dashboard` object after `patients: 40,`.

- [ ] **Step 2: Run them and check they fail**

Run: `npx vitest run src/lib src/pages/app.test.tsx`

Expected: FAIL. `./download` does not resolve, and the "Open referral flags" heading is not found.

- [ ] **Step 3: Implement**

Append to `frontend/src/api/types.ts`:

```ts
export type Urgency = "urgent" | "routine";

export interface ReferralFlag {
  id: string;
  visit_id: string;
  patient_id: string;
  patient_name: string;
  rule_id: string;
  reason_en: string;
  reason_fil: string;
  urgency: Urgency;
  status: "open" | "referred" | "dismissed";
  dismiss_note: string | null;
  created_at: string;
  form_type: string;
  visit_date: string;
}

export interface Referral {
  id: string;
  patient_id: string;
  patient_name: string;
  birth_date: string | null;
  sex: Sex | null;
  barangay: string;
  sitio: string | null;
  flag_id: string | null;
  facility: string;
  reason: string;
  urgency: Urgency;
  notes: string | null;
  status: "issued" | "sent";
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  visit: { id: string; form_type: string; visit_date: string; values: Values } | null;
}

export interface ReferralInput {
  patient_id: string;
  flag_id: string | null;
  facility: string;
  reason: string;
  urgency: Urgency;
  notes: string | null;
}

export interface SupplyItem {
  id: string;
  name: string;
  unit: string;
  low_stock_threshold: number;
  target_level: number;
  active: boolean;
  on_hand: number;
  low: boolean;
  created_at: string;
  updated_at: string;
}

export interface SupplyItemInput {
  name: string;
  unit: string;
  low_stock_threshold: number;
  target_level: number;
}

export type MovementKind = "received" | "distributed" | "adjusted";

export interface SupplyMovement {
  id: string;
  item_id: string;
  kind: MovementKind;
  quantity: number;
  movement_date: string;
  note: string | null;
  recorded_by: string;
  recorded_by_name: string;
  created_at: string;
}

export interface RequestItem extends SupplyItem {
  request_quantity: number;
}

export type Period = "week" | "month";

export interface ReportFigures {
  start: string;
  end: string;
  visits: { total: number; final: number; by_form: Record<string, number> };
  new_households: number;
  new_patients: number;
  follow_ups_completed: number;
  follow_ups_overdue: number;
  referral_flags: number;
  referrals_issued: number;
  referrals_by_reason: Record<string, number>;
  supplies: { name: string; unit: string; received: number; distributed: number }[];
  low_stock_items: string[];
}

export interface ReportSummary {
  period: Period;
  current: ReportFigures;
  previous: ReportFigures;
  unsynced_records: number;
}

export interface ReportDraft {
  id: string;
  period: Period;
  start_date: string;
  end_date: string;
  figures: ReportSummary;
  text: string;
  status: "draft" | "approved";
  model: string | null;
  created_by: string;
  approved_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SyncCounts {
  pending: number;
  awaiting: number;
  synced: number;
}

export interface SyncStatus {
  station_id: string;
  passphrase_set: boolean;
  records: Record<string, SyncCounts>;
  last_acknowledged_at: string | null;
  open_bundles: number;
}

export interface SyncBundleSummary {
  id: string;
  record_count: number;
  created_at: string;
  acknowledged_at: string | null;
  created_by_name: string;
}

export interface SyncBundle {
  bundle_id: string;
  station_id: string;
  record_count: number;
  [key: string]: unknown;
}
```

In the `Dashboard` interface in `types.ts`, add after `patients: number;`:

```ts
  referral_flags_open: number;
  low_stock: number;
  unsynced: number;
```

`frontend/src/api/modules.ts`:

```ts
import { qs, request } from "./client";
import type {
  Page, Period, Referral, ReferralFlag, ReferralInput, ReportDraft, ReportSummary, RequestItem, SupplyItem,
  SupplyItemInput, SupplyMovement, SyncBundle, SyncBundleSummary, SyncStatus, MovementKind,
} from "./types";

type Params = Record<string, string | number | null | undefined>;
const id = encodeURIComponent;

export const referralsApi = {
  listFlags: (params: Params = {}) => request<ReferralFlag[]>("GET", `/referral-flags${qs(params)}`),
  getFlag: (flagId: string) => request<ReferralFlag>("GET", `/referral-flags/${id(flagId)}`),
  dismissFlag: (flagId: string, note: string | null) =>
    request<ReferralFlag>("POST", `/referral-flags/${id(flagId)}/dismiss`, { note }),
  list: (params: Params = {}) => request<Page<Referral>>("GET", `/referrals${qs(params)}`),
  get: (referralId: string) => request<Referral>("GET", `/referrals/${id(referralId)}`),
  create: (body: ReferralInput) => request<Referral>("POST", "/referrals", body),
};

export const suppliesApi = {
  list: () => request<SupplyItem[]>("GET", "/supplies"),
  get: (itemId: string) => request<SupplyItem>("GET", `/supplies/${id(itemId)}`),
  create: (body: SupplyItemInput) => request<SupplyItem>("POST", "/supplies", body),
  update: (itemId: string, body: Partial<SupplyItemInput> & { active?: boolean }) =>
    request<SupplyItem>("PATCH", `/supplies/${id(itemId)}`, body),
  movements: (itemId: string, params: Params = {}) =>
    request<Page<SupplyMovement>>("GET", `/supplies/${id(itemId)}/movements${qs(params)}`),
  addMovement: (itemId: string, body: { kind: MovementKind; quantity: number; movement_date: string; note: string | null }) =>
    request<SupplyMovement>("POST", `/supplies/${id(itemId)}/movements`, body),
  requestList: () => request<RequestItem[]>("GET", "/supplies/request-list"),
};

export const reportsApi = {
  summary: (period: Period, date: string) => request<ReportSummary>("GET", `/reports/summary${qs({ period, date })}`),
  drafts: (period: Period, date: string) => request<ReportDraft[]>("GET", `/reports/drafts${qs({ period, date })}`),
  createAiDraft: (period: Period, date: string) => request<ReportDraft>("POST", "/reports/drafts", { period, date }),
  createManualDraft: (period: Period, date: string, text: string) =>
    request<ReportDraft>("POST", "/reports/drafts/manual", { period, date, text }),
  updateDraft: (draftId: string, body: { text?: string; status?: "approved" }) =>
    request<ReportDraft>("PATCH", `/reports/drafts/${id(draftId)}`, body),
};

export const syncApi = {
  status: () => request<SyncStatus>("GET", "/sync/status"),
  bundles: () => request<SyncBundleSummary[]>("GET", "/sync/bundles"),
  createBundle: () => request<SyncBundle>("POST", "/sync/bundles"),
  getBundle: (bundleId: string) => request<SyncBundle>("GET", `/sync/bundles/${id(bundleId)}`),
  sendReceipt: (receipt: unknown) => request<SyncBundleSummary>("POST", "/sync/receipts", receipt),
  setPassphrase: (passphrase: string) => request<void>("PUT", "/sync/settings", { passphrase }),
};
```

`frontend/src/lib/download.ts`:

```ts
/** Rows to CSV text (RFC 4180 quoting; CRLF line ends so spreadsheet apps open it cleanly). */
export function toCsv(rows: (string | number | null)[][]): string {
  const cell = (value: string | number | null) => {
    const text = value === null ? "" : String(value);
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return rows.map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

/** Save text as a file through the browser's normal download. */
export function downloadFile(filename: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** A file or blob's text. FileReader works in every browser and in the jsdom test environment. */
export function readText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(blob);
  });
}
```

`frontend/src/i18n/_add.en.json`:

```json
{
  "referrals.title": "Referrals",
  "referrals.rulesNote": "Flags come from referral rules (draft, pending professional review). The AI never decides referrals.",
  "referrals.openFlags": "Open flags",
  "referrals.list": "Referrals",
  "referrals.noFlags": "No open referral flags",
  "referrals.noReferrals": "No referrals yet",
  "referrals.createReferral": "Create referral",
  "referrals.dismiss": "Dismiss",
  "referrals.dismissTitle": "Dismiss this flag?",
  "referrals.dismissBody": "Use this when a health professional decided no referral is needed.",
  "referrals.dismissed": "Flag dismissed",
  "referrals.flagBannerTitle": "Referral flags",
  "referrals.visitOn": "Visit {date}",
  "referrals.newTitle": "New referral",
  "referrals.fromFlag": "Flagged: {reason}",
  "referrals.facility": "Receiving facility (RHU or hospital)",
  "referrals.reason": "Reason for referral",
  "referrals.urgency": "Urgency",
  "referrals.urgency.urgent": "Urgent",
  "referrals.urgency.routine": "Routine",
  "referrals.notes": "Notes for the receiving facility",
  "referrals.save": "Save and view slip",
  "referrals.status.issued": "Issued",
  "referrals.status.sent": "Sent to RHU",
  "referrals.refer": "Refer patient",
  "slip.title": "Referral slip",
  "slip.draftNote": "Layout pending DOH form review",
  "slip.print": "Print or save as PDF",
  "slip.back": "Back to referrals",
  "slip.date": "Date",
  "slip.patient": "Patient",
  "slip.birthDate": "Birth date",
  "slip.sex": "Sex",
  "slip.address": "Address",
  "slip.referredBy": "Referred by",
  "slip.status": "Status",
  "slip.findings": "Findings from the visit on {date}",
  "slip.receivedBy": "Received by (name, signature, date)",
  "supplies.title": "Medicine & supplies",
  "supplies.addItem": "Add item",
  "supplies.requestList": "Request list",
  "supplies.name": "Item name",
  "supplies.unit": "Unit (e.g. tablets, vials)",
  "supplies.threshold": "Low-stock level",
  "supplies.target": "Target stock level",
  "supplies.onHand": "{count} {unit} on hand",
  "supplies.low": "Low stock",
  "supplies.none": "No items yet. Add the medicines and supplies you keep.",
  "supplies.itemAdded": "Item added",
  "supplies.recordMovement": "Record stock movement",
  "supplies.kind": "Type",
  "supplies.kind.received": "Received",
  "supplies.kind.distributed": "Distributed",
  "supplies.kind.adjusted": "Adjustment (count correction)",
  "supplies.quantity": "Quantity",
  "supplies.adjustHint": "For an adjustment, use a negative number to remove stock.",
  "supplies.date": "Date",
  "supplies.note": "Note",
  "supplies.recorded": "Stock movement recorded",
  "supplies.history": "Stock history",
  "supplies.noHistory": "No movements yet",
  "supplies.by": "By",
  "supplies.settings": "Stock levels",
  "supplies.saved": "Item saved",
  "supplies.requestTitle": "Supply request list",
  "supplies.requestIntro": "Items at or below their low-stock level, with the amount needed to reach the target.",
  "supplies.requestNone": "Nothing to request: no item is low on stock.",
  "supplies.request": "Request",
  "supplies.print": "Print",
  "supplies.exportCsv": "Export CSV",
  "reports.title": "Reports",
  "reports.period": "Period",
  "reports.week": "Week",
  "reports.month": "Month",
  "reports.date": "Any date in the period",
  "reports.range": "{start} to {end}",
  "reports.previous": "previous: {value}",
  "reports.unsynced": "{count} records are not yet transferred to the RHU, so RHU figures may differ.",
  "reports.visits": "Visits",
  "reports.finalVisits": "Finalized visits",
  "reports.newHouseholds": "New households",
  "reports.newPatients": "New patients",
  "reports.followUpsCompleted": "Follow-ups completed",
  "reports.followUpsOverdue": "Follow-ups still open past due",
  "reports.referralFlags": "Referral flags",
  "reports.referralsIssued": "Referrals issued",
  "reports.byForm": "Visits by form",
  "reports.byReason": "Referrals by reason",
  "reports.suppliesMoved": "Supplies received and distributed",
  "reports.received": "Received",
  "reports.distributed": "Distributed",
  "reports.lowStock": "Low stock at period end",
  "reports.nothing": "None in this period",
  "reports.exportCsv": "Export CSV",
  "reports.metric": "Measure",
  "reports.current": "This period",
  "reports.previousPeriod": "Previous period",
  "reports.draftTitle": "Possible program and service needs",
  "reports.draftNote": "Draft for professional review. The AI sees only the totals above and does not make clinical or resource decisions.",
  "reports.generate": "Generate AI draft",
  "reports.generating": "Writing the draft…",
  "reports.writeManually": "Write without AI",
  "reports.continue": "Continue editing draft",
  "reports.draftText": "Draft text",
  "reports.saveDraft": "Save draft",
  "reports.approve": "Approve",
  "reports.draftSaved": "Draft saved",
  "reports.approved": "Summary approved",
  "reports.approvedOn": "Approved {date}",
  "reports.aiUnavailable": "AI assistant unavailable — write the summary by hand.",
  "sync.title": "Sync",
  "sync.manualNote": "No RHU connection is set up yet. Records are transferred by file (for example on a USB stick) and count as synced only after the RHU's receipt is imported.",
  "sync.pending": "Waiting to transfer",
  "sync.awaiting": "Sent, waiting for RHU receipt",
  "sync.lastReceipt": "Last RHU receipt",
  "sync.never": "Never",
  "sync.type": "Record type",
  "sync.synced": "Synced",
  "sync.type.household": "Households",
  "sync.type.patient": "Patients",
  "sync.type.visit": "Finalized visits",
  "sync.type.follow_up": "Follow-ups",
  "sync.type.referral": "Referrals",
  "sync.type.supply_item": "Supply items",
  "sync.type.supply_movement": "Stock movements",
  "sync.createBundle": "Create transfer file",
  "sync.bundleCreated": "Transfer file created with {count} records. Give it to the RHU.",
  "sync.needPassphrase": "An admin must set the RHU passphrase first.",
  "sync.adminOnly": "Only an admin can create transfer files and import receipts.",
  "sync.awaitingFiles": "Transfer files waiting for a receipt",
  "sync.noAwaiting": "None",
  "sync.fileLine": "{date} · {count} records",
  "sync.downloadAgain": "Download again",
  "sync.importReceipt": "Import RHU receipt",
  "sync.receiptFile": "Receipt file from the RHU",
  "sync.receiptAccepted": "Receipt accepted: records marked as synced",
  "sync.notJson": "This file is not a receipt (not valid JSON).",
  "sync.history": "Acknowledged transfers",
  "sync.passphraseTitle": "RHU passphrase",
  "sync.passphraseHint": "Agreed with the RHU; at least 12 characters. Changing it means older transfer files can't be acknowledged.",
  "sync.passphrase": "Passphrase",
  "sync.passphraseSaved": "Passphrase saved",
  "sync.passphraseSet": "A passphrase is set.",
  "sync.chip": "{count} not synced",
  "dashboard.referralFlags": "Open referral flags",
  "dashboard.lowStock": "Low-stock supplies",
  "dashboard.sync": "Not yet synced",
  "dashboard.unsyncedNote": "Records waiting for the RHU"
}
```

`frontend/src/i18n/_add.fil.json`:

```json
{
  "referrals.title": "Mga referral",
  "referrals.rulesNote": "Galing ang mga flag sa mga patakaran sa referral (draft, hinihintay ang pagsusuri ng propesyonal). Hindi kailanman ang AI ang nagpapasya ng referral.",
  "referrals.openFlags": "Bukas na flag",
  "referrals.list": "Mga referral",
  "referrals.noFlags": "Walang bukas na referral flag",
  "referrals.noReferrals": "Wala pang referral",
  "referrals.createReferral": "Gumawa ng referral",
  "referrals.dismiss": "Isara",
  "referrals.dismissTitle": "Isara ang flag na ito?",
  "referrals.dismissBody": "Gamitin ito kapag nagpasya ang propesyonal na hindi kailangan ng referral.",
  "referrals.dismissed": "Naisara ang flag",
  "referrals.flagBannerTitle": "Mga referral flag",
  "referrals.visitOn": "Bisita {date}",
  "referrals.newTitle": "Bagong referral",
  "referrals.fromFlag": "Na-flag: {reason}",
  "referrals.facility": "Tatanggap na pasilidad (RHU o ospital)",
  "referrals.reason": "Dahilan ng referral",
  "referrals.urgency": "Pagkaapurahan",
  "referrals.urgency.urgent": "Apurahan",
  "referrals.urgency.routine": "Karaniwan",
  "referrals.notes": "Tala para sa tatanggap na pasilidad",
  "referrals.save": "I-save at tingnan ang slip",
  "referrals.status.issued": "Naibigay",
  "referrals.status.sent": "Naipadala sa RHU",
  "referrals.refer": "I-refer ang pasyente",
  "slip.title": "Referral slip",
  "slip.draftNote": "Hinihintay ang pagsusuri ng DOH sa ayos ng form",
  "slip.print": "I-print o i-save bilang PDF",
  "slip.back": "Bumalik sa mga referral",
  "slip.date": "Petsa",
  "slip.patient": "Pasyente",
  "slip.birthDate": "Petsa ng kapanganakan",
  "slip.sex": "Kasarian",
  "slip.address": "Tirahan",
  "slip.referredBy": "Nag-refer",
  "slip.status": "Katayuan",
  "slip.findings": "Mga natuklasan sa bisita noong {date}",
  "slip.receivedBy": "Tinanggap ni (pangalan, lagda, petsa)",
  "supplies.title": "Mga gamot at supply",
  "supplies.addItem": "Magdagdag ng item",
  "supplies.requestList": "Listahan ng hihilingin",
  "supplies.name": "Pangalan ng item",
  "supplies.unit": "Yunit (hal. tableta, vial)",
  "supplies.threshold": "Antas ng mababang stock",
  "supplies.target": "Target na dami ng stock",
  "supplies.onHand": "{count} {unit} ang nasa kamay",
  "supplies.low": "Mababa ang stock",
  "supplies.none": "Wala pang item. Idagdag ang mga gamot at supply na hawak ninyo.",
  "supplies.itemAdded": "Naidagdag ang item",
  "supplies.recordMovement": "Itala ang galaw ng stock",
  "supplies.kind": "Uri",
  "supplies.kind.received": "Natanggap",
  "supplies.kind.distributed": "Naipamigay",
  "supplies.kind.adjusted": "Pagwawasto ng bilang",
  "supplies.quantity": "Dami",
  "supplies.adjustHint": "Para sa pagwawasto, gumamit ng negatibong numero para magbawas ng stock.",
  "supplies.date": "Petsa",
  "supplies.note": "Tala",
  "supplies.recorded": "Naitala ang galaw ng stock",
  "supplies.history": "Kasaysayan ng stock",
  "supplies.noHistory": "Wala pang galaw",
  "supplies.by": "Ni",
  "supplies.settings": "Mga antas ng stock",
  "supplies.saved": "Na-save ang item",
  "supplies.requestTitle": "Listahan ng supply na hihilingin",
  "supplies.requestIntro": "Mga item na nasa o mas mababa sa antas ng mababang stock, kasama ang kailangang dami para maabot ang target.",
  "supplies.requestNone": "Walang hihilingin: walang item na mababa ang stock.",
  "supplies.request": "Hihilingin",
  "supplies.print": "I-print",
  "supplies.exportCsv": "I-export bilang CSV",
  "reports.title": "Mga ulat",
  "reports.period": "Panahon",
  "reports.week": "Linggo",
  "reports.month": "Buwan",
  "reports.date": "Anumang petsa sa panahon",
  "reports.range": "{start} hanggang {end}",
  "reports.previous": "nakaraan: {value}",
  "reports.unsynced": "{count} rekord ang hindi pa naililipat sa RHU, kaya maaaring iba ang bilang sa RHU.",
  "reports.visits": "Mga bisita",
  "reports.finalVisits": "Mga natapos na bisita",
  "reports.newHouseholds": "Mga bagong sambahayan",
  "reports.newPatients": "Mga bagong pasyente",
  "reports.followUpsCompleted": "Mga natapos na follow-up",
  "reports.followUpsOverdue": "Mga bukas pang follow-up na lampas na",
  "reports.referralFlags": "Mga referral flag",
  "reports.referralsIssued": "Mga naibigay na referral",
  "reports.byForm": "Mga bisita ayon sa form",
  "reports.byReason": "Mga referral ayon sa dahilan",
  "reports.suppliesMoved": "Mga supply na natanggap at naipamigay",
  "reports.received": "Natanggap",
  "reports.distributed": "Naipamigay",
  "reports.lowStock": "Mababang stock sa katapusan ng panahon",
  "reports.nothing": "Wala sa panahong ito",
  "reports.exportCsv": "I-export bilang CSV",
  "reports.metric": "Sukatan",
  "reports.current": "Ngayong panahon",
  "reports.previousPeriod": "Nakaraang panahon",
  "reports.draftTitle": "Posibleng pangangailangan sa programa at serbisyo",
  "reports.draftNote": "Draft para sa pagsusuri ng propesyonal. Ang mga kabuuan lang sa itaas ang nakikita ng AI at hindi ito nagpapasya tungkol sa paggamot o paglalaan ng resources.",
  "reports.generate": "Gumawa ng AI draft",
  "reports.generating": "Isinusulat ang draft…",
  "reports.writeManually": "Isulat nang walang AI",
  "reports.continue": "Ituloy ang pag-edit ng draft",
  "reports.draftText": "Teksto ng draft",
  "reports.saveDraft": "I-save ang draft",
  "reports.approve": "Aprubahan",
  "reports.draftSaved": "Na-save ang draft",
  "reports.approved": "Naaprubahan ang buod",
  "reports.approvedOn": "Naaprubahan {date}",
  "reports.aiUnavailable": "Hindi magamit ang AI assistant — isulat ang buod nang mano-mano.",
  "sync.title": "Sync",
  "sync.manualNote": "Wala pang koneksyon sa RHU. Inililipat ang mga rekord sa pamamagitan ng file (hal. sa USB stick) at itinuturing na naka-sync lamang kapag na-import na ang resibo ng RHU.",
  "sync.pending": "Naghihintay mailipat",
  "sync.awaiting": "Naipadala, hinihintay ang resibo ng RHU",
  "sync.lastReceipt": "Huling resibo ng RHU",
  "sync.never": "Wala pa",
  "sync.type": "Uri ng rekord",
  "sync.synced": "Naka-sync",
  "sync.type.household": "Mga sambahayan",
  "sync.type.patient": "Mga pasyente",
  "sync.type.visit": "Mga natapos na bisita",
  "sync.type.follow_up": "Mga follow-up",
  "sync.type.referral": "Mga referral",
  "sync.type.supply_item": "Mga supply item",
  "sync.type.supply_movement": "Mga galaw ng stock",
  "sync.createBundle": "Gumawa ng transfer file",
  "sync.bundleCreated": "Nagawa ang transfer file na may {count} rekord. Ibigay ito sa RHU.",
  "sync.needPassphrase": "Kailangang itakda muna ng admin ang passphrase ng RHU.",
  "sync.adminOnly": "Admin lamang ang maaaring gumawa ng transfer file at mag-import ng resibo.",
  "sync.awaitingFiles": "Mga transfer file na naghihintay ng resibo",
  "sync.noAwaiting": "Wala",
  "sync.fileLine": "{date} · {count} rekord",
  "sync.downloadAgain": "I-download muli",
  "sync.importReceipt": "I-import ang resibo ng RHU",
  "sync.receiptFile": "Resibong file mula sa RHU",
  "sync.receiptAccepted": "Tinanggap ang resibo: naka-sync na ang mga rekord",
  "sync.notJson": "Hindi resibo ang file na ito (hindi valid na JSON).",
  "sync.history": "Mga nakumpirmang paglilipat",
  "sync.passphraseTitle": "Passphrase ng RHU",
  "sync.passphraseHint": "Napagkasunduan kasama ang RHU; hindi bababa sa 12 character. Kapag pinalitan ito, hindi na makukumpirma ang mga lumang transfer file.",
  "sync.passphrase": "Passphrase",
  "sync.passphraseSaved": "Na-save ang passphrase",
  "sync.passphraseSet": "May nakatakdang passphrase.",
  "sync.chip": "{count} hindi pa naka-sync",
  "dashboard.referralFlags": "Bukas na referral flag",
  "dashboard.lowStock": "Mga supply na mababa ang stock",
  "dashboard.sync": "Hindi pa naka-sync",
  "dashboard.unsyncedNote": "Mga rekord na naghihintay para sa RHU"
}
```

Merge the additions, then delete the two `_add` files:

```bash
python - <<'EOF'
import json
from pathlib import Path
for lang in ("en", "fil"):
    base = Path(f"src/i18n/{lang}.json"); extra = Path(f"src/i18n/_add.{lang}.json")
    merged = {**json.loads(base.read_text(encoding="utf-8")), **json.loads(extra.read_text(encoding="utf-8"))}
    base.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extra.unlink()
print("merged")
EOF
```

Append to `frontend/src/styles/base.css`:

```css
.table-wrap { overflow-x: auto; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); }
.table th[scope="col"] { color: var(--muted); font-weight: 600; }
.badge-urgent { background: var(--danger-bg); color: var(--danger); }
.badge-routine, .badge-issued { background: var(--blue-100); color: var(--blue-800); }
.badge-sent { background: var(--ok-bg); color: var(--ok); }
.flag-banner ul { margin: 6px 0 0; padding-left: 20px; }
.controls { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; margin-bottom: 16px; }
.controls .stack { min-width: 160px; }
.report-compare { margin: 4px 0 0; color: var(--muted); font-size: 0.9rem; }
.draft-text { white-space: pre-wrap; }
.slip { max-width: 760px; }
.slip-grid { display: grid; grid-template-columns: minmax(110px, 30%) minmax(0, 1fr); gap: 6px 16px; margin: 16px 0; }
.slip-grid dt { font-weight: 600; color: var(--muted); }
.slip-grid dd { margin: 0; overflow-wrap: anywhere; }
.slip-sign { margin-top: 32px; }
@media print {
  .sidebar, .topbar, .no-print, .toasts { display: none !important; }
  .shell { display: block; }
  body { background: #fff; }
  .content { padding: 0; max-width: none; }
  .card, .slip { box-shadow: none; }
}
```

In `frontend/src/components/Layout.tsx`:
- In `NAV`, remove every `soon: true` property and the `{item.soon && …}` span.
- Replace `import { AiChip } from "./AiChip";` with:

```tsx
import { syncApi } from "../api/modules";
import { useApi } from "../api/useApi";
import { AiChip } from "./AiChip";
```

- Inside `Layout`, after `const location = useLocation();`, add:

```tsx
  const sync = useApi(syncApi.status, [location.pathname]);
  const unsynced = sync.data
    ? Object.values(sync.data.records).reduce((sum, c) => sum + c.pending + c.awaiting, 0)
    : 0;
```

- In the header, before `<AiChip />`, add:

```tsx
            {unsynced > 0 && <Link to="/sync" className="chip chip-off">{t("sync.chip", { count: unsynced })}</Link>}
```

In `frontend/src/pages/DashboardPage.tsx`, replace the three cards `<BentoCard title={t("nav.referrals")} soon />`, `<BentoCard title={t("nav.supplies")} soon />` and `<BentoCard title={t("nav.reports")} soon />` with:

```tsx
        <BentoCard title={t("dashboard.referralFlags")} value={data.referral_flags_open} to="/referrals"
          tone={data.referral_flags_open ? "alert" : undefined} />
        <BentoCard title={t("dashboard.lowStock")} value={data.low_stock} to="/supplies"
          tone={data.low_stock ? "gold" : undefined} />
        <BentoCard title={t("dashboard.sync")} value={data.unsynced} note={t("dashboard.unsyncedNote")} to="/sync" />
```

Delete `frontend/src/pages/ComingSoonPage.tsx`. In `frontend/src/routes.tsx`, remove its import and the four `ComingSoonPage` routes (`referrals`, `supplies`, `reports`, `sync`).

- [ ] **Step 4: Run all frontend tests and the build**

Run: `npx vitest run`

Expected: all pass, including `download.test.ts` and the i18n key-parity test.

Run: `npm run build`

Expected: no TypeScript errors.

- [ ] **Step 5: Stop. No git operations.**

---

### Task 6: Referrals tab, referral form, slip, flag banners (frontend)

**Files:**
- Create:
  - `frontend/src/components/FlagBanner.tsx`
  - `frontend/src/pages/ReferralsPage.tsx`, `ReferralNewPage.tsx`, `ReferralSlipPage.tsx`, `referrals.test.tsx`
- Modify:
  - `frontend/src/routes.tsx`
  - `frontend/src/pages/CheckupPage.tsx` (banner on final visits)
  - `frontend/src/pages/PatientPage.tsx` (banner and "Refer patient")

**Interfaces:**
- Consumes: `referralsApi`, `api.getPatient`, `api.getForm`, `displayValue`, `pick`, `ConfirmDialog` and `useListParams`.
- Produces: the routes `referrals`, `referrals/new?flag=|patient=` and `referrals/:referralId/slip`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/pages/referrals.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import type { Referral, ReferralFlag } from "../api/types";
import { admin, bpForm, page, patient } from "../test/fixtures";
import { callsTo, mockApi, signedInAs } from "../test/http";
import { renderApp } from "../test/render";

const flag: ReferralFlag = {
  id: "fl1", visit_id: "v1", patient_id: "p1", patient_name: "Ana Dela Cruz", rule_id: "bp-severe",
  reason_en: "Very high blood pressure (180/110 or higher)", reason_fil: "Napakataas na presyon (180/110 o higit pa)",
  urgency: "urgent", status: "open", dismiss_note: null, created_at: "2026-10-10 08:00:00",
  form_type: "bp_followup", visit_date: "2026-10-10",
};
const referral: Referral = {
  id: "r1", patient_id: "p1", patient_name: "Ana Dela Cruz", birth_date: "1995-03-14", sex: "female",
  barangay: "San Roque", sitio: "Malinis", flag_id: "fl1", facility: "Rural Health Unit",
  reason: flag.reason_en, urgency: "urgent", notes: null, status: "issued", created_by: "u1",
  created_by_name: "Ada Admin", created_at: "2026-10-10 08:05:00", updated_at: "2026-10-10 08:05:00",
  visit: { id: "v1", form_type: "bp_followup", visit_date: "2026-10-10", values: { bp_systolic: 185, bp_diastolic: 112 } },
};

function backend() {
  return mockApi({
    ...signedInAs(admin),
    "GET /referral-flags": [200, [flag]],
    "GET /referral-flags/fl1": [200, flag],
    "POST /referral-flags/fl1/dismiss": [200, { ...flag, status: "dismissed" }],
    "GET /referrals": [200, page([referral])],
    "GET /referrals/r1": [200, referral],
    "POST /referrals": [201, referral],
    "GET /patients/p1": [200, patient],
    "GET /forms/bp_followup": [200, bpForm],
  });
}

describe("referrals", () => {
  it("turns a flag into a referral and shows the slip", async () => {
    const { calls } = backend();
    const { user } = renderApp("/referrals", { signedIn: true });
    await user.click(await screen.findByRole("link", { name: "Create referral" }));
    expect(await screen.findByLabelText("Reason for referral")).toHaveValue(flag.reason_en);
    await user.type(screen.getByLabelText("Receiving facility (RHU or hospital)"), "Rural Health Unit");
    await user.click(screen.getByRole("button", { name: "Save and view slip" }));
    expect(await screen.findByRole("heading", { name: "Referral slip" })).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/referrals")[0].body).toEqual({
      patient_id: "p1", flag_id: "fl1", facility: "Rural Health Unit", reason: flag.reason_en,
      urgency: "urgent", notes: null,
    });
    const findings = await screen.findByRole("table");
    expect(within(findings).getByText("BP systolic (mmHg)")).toBeInTheDocument();
    expect(within(findings).getByText("185")).toBeInTheDocument();
  });

  it("dismisses a flag only after confirming", async () => {
    const { calls } = backend();
    const { user } = renderApp("/referrals", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(callsTo(calls, "POST", "/referral-flags/fl1/dismiss")).toHaveLength(0);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Dismiss" }));
    expect(await screen.findByText("Flag dismissed")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/referral-flags/fl1/dismiss")).toHaveLength(1);
  });

  it("lists issued referrals", async () => {
    backend();
    const { user } = renderApp("/referrals", { signedIn: true });
    await user.click(await screen.findByRole("tab", { name: "Referrals" }));
    expect(await screen.findByText("Rural Health Unit")).toBeInTheDocument();
    expect(screen.getByText("Issued")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run them and check they fail**

Run: `npx vitest run src/pages/referrals.test.tsx`

Expected: FAIL. With no route, "Page not found" renders and the `findBy…` queries time out.

- [ ] **Step 3: Implement**

`frontend/src/components/FlagBanner.tsx`:

```tsx
import { Link } from "react-router-dom";
import { referralsApi } from "../api/modules";
import { useApi } from "../api/useApi";
import { useI18n } from "../i18n/i18n";

/** Open referral flags for a visit or a patient, each with a link to refer. */
export function FlagBanner({ visitId, patientId }: { visitId?: string; patientId?: string }) {
  const { t, lang } = useI18n();
  const flags = useApi(() => referralsApi.listFlags({ visit_id: visitId, patient_id: patientId, status: "open" }),
    [visitId, patientId]);
  const items = flags.data ?? [];
  if (items.length === 0) return null;
  return (
    <div className="notice notice-error flag-banner" role="alert">
      <strong>{t("referrals.flagBannerTitle")}</strong>
      <ul>
        {items.map((flag) => (
          <li key={flag.id}>
            {lang === "fil" ? flag.reason_fil : flag.reason_en}{" "}
            <Link to={`/referrals/new?flag=${encodeURIComponent(flag.id)}`}>{t("referrals.createReferral")}</Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

`frontend/src/pages/ReferralsPage.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { referralsApi } from "../api/modules";
import type { ReferralFlag } from "../api/types";
import { useApi } from "../api/useApi";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";
import { useListParams } from "../lib/useListParams";

export function ReferralsPage() {
  const { t, lang } = useI18n();
  const toast = useToast();
  const { params, update } = useListParams();
  const tab = params.get("tab") === "referrals" ? "referrals" : "flags";
  const flags = useApi(() => referralsApi.listFlags({ status: "open" }), []);
  const referrals = useApi(() => referralsApi.list({ limit: 100 }), []);
  const [dismissing, setDismissing] = useState<ReferralFlag | null>(null);

  async function dismiss() {
    if (!dismissing) return;
    const flag = dismissing;
    setDismissing(null);
    try {
      await referralsApi.dismissFlag(flag.id, null);
      toast(t("referrals.dismissed"));
      flags.reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  return (
    <>
      <div className="page-head"><h1>{t("referrals.title")}</h1></div>
      <p className="muted">{t("referrals.rulesNote")}</p>
      <div className="tabs" role="tablist" aria-label={t("referrals.title")}>
        <button type="button" role="tab" className="tab" aria-selected={tab === "flags"} onClick={() => update({ tab: undefined })}>
          {t("referrals.openFlags")}{flags.data ? ` (${flags.data.length})` : ""}
        </button>
        <button type="button" role="tab" className="tab" aria-selected={tab === "referrals"} onClick={() => update({ tab: "referrals" })}>
          {t("referrals.list")}
        </button>
      </div>
      {tab === "flags" ? (
        flags.error ? <LoadError error={flags.error} onRetry={flags.reload} /> : !flags.data ? <Loading /> :
          flags.data.length === 0 ? <p className="empty">{t("referrals.noFlags")}</p> : (
            <ul className="list">
              {flags.data.map((flag) => (
                <li key={flag.id} className="list-row">
                  <Link to={`/patients/${flag.patient_id}`}><strong>{flag.patient_name}</strong></Link>
                  <span>{lang === "fil" ? flag.reason_fil : flag.reason_en}</span>
                  <span className={`badge badge-${flag.urgency}`}>{t(`referrals.urgency.${flag.urgency}`)}</span>
                  <span className="muted">{t("referrals.visitOn", { date: flag.visit_date })}</span>
                  <div className="row-actions">
                    <Link className="btn btn-small btn-primary" to={`/referrals/new?flag=${encodeURIComponent(flag.id)}`}>
                      {t("referrals.createReferral")}
                    </Link>
                    <button type="button" className="btn btn-small" onClick={() => setDismissing(flag)}>{t("referrals.dismiss")}</button>
                  </div>
                </li>
              ))}
            </ul>
          )
      ) : (
        referrals.error ? <LoadError error={referrals.error} onRetry={referrals.reload} /> : !referrals.data ? <Loading /> :
          referrals.data.items.length === 0 ? <p className="empty">{t("referrals.noReferrals")}</p> : (
            <ul className="list">
              {referrals.data.items.map((r) => (
                <li key={r.id}>
                  <Link to={`/referrals/${r.id}/slip`} className="list-row">
                    <span>{r.created_at.slice(0, 10)}</span>
                    <strong>{r.patient_name}</strong>
                    <span>{r.facility}</span>
                    <span className="muted">{r.reason}</span>
                    <span className={`badge badge-${r.status}`}>{t(`referrals.status.${r.status}`)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )
      )}
      <ConfirmDialog open={dismissing !== null} title={t("referrals.dismissTitle")} body={t("referrals.dismissBody")}
        confirmLabel={t("referrals.dismiss")} onConfirm={() => void dismiss()} onCancel={() => setDismissing(null)} />
    </>
  );
}
```

`frontend/src/pages/ReferralNewPage.tsx`:

```tsx
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { referralsApi } from "../api/modules";
import type { PatientSummary, ReferralFlag, Urgency } from "../api/types";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { errorText } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

export function ReferralNewPage() {
  const [params] = useSearchParams();
  const flagId = params.get("flag");
  const patientParam = params.get("patient");
  const loader = useApi(async () => {
    const flag = flagId ? await referralsApi.getFlag(flagId) : null;
    const patient = await api.getPatient(flag?.patient_id ?? patientParam ?? "");
    return { flag, patient };
  }, [flagId, patientParam]);
  if (loader.error) return <LoadError error={loader.error} onRetry={loader.reload} />;
  if (!loader.data) return <Loading />;
  return <ReferralForm key={loader.data.flag?.id ?? loader.data.patient.id} {...loader.data} />;
}

function ReferralForm({ flag, patient }: { flag: ReferralFlag | null; patient: PatientSummary }) {
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const [facility, setFacility] = useState("");
  const [reason, setReason] = useState(flag ? (lang === "fil" ? flag.reason_fil : flag.reason_en) : "");
  const [urgency, setUrgency] = useState<Urgency>(flag?.urgency ?? "routine");
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setErrors([]);
    try {
      const created = await referralsApi.create({
        patient_id: patient.id, flag_id: flag?.id ?? null, facility: facility.trim(), reason: reason.trim(),
        urgency, notes: notes.trim() || null,
      });
      navigate(`/referrals/${created.id}/slip`, { replace: true });
    } catch (failure) {
      setErrors(failure instanceof ApiError ? failure.messages : [errorText(failure, t)]);
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={submit}>
      <div>
        <h1>{t("referrals.newTitle")}</h1>
        <p className="eyebrow"><Link to={`/patients/${patient.id}`}>{patient.full_name}</Link></p>
        {flag && (
          <p className="notice">
            {t("referrals.fromFlag", { reason: lang === "fil" ? flag.reason_fil : flag.reason_en })} ·{" "}
            {t("referrals.visitOn", { date: flag.visit_date })}
          </p>
        )}
      </div>
      <label className="stack">{t("referrals.facility")}
        <input required maxLength={200} value={facility} onChange={(e) => setFacility(e.target.value)} />
      </label>
      <label className="stack">{t("referrals.reason")}
        <textarea required rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <label className="stack">{t("referrals.urgency")}
        <select value={urgency} onChange={(e) => setUrgency(e.target.value as Urgency)}>
          <option value="urgent">{t("referrals.urgency.urgent")}</option>
          <option value="routine">{t("referrals.urgency.routine")}</option>
        </select>
      </label>
      <label className="stack">{t("referrals.notes")}
        <textarea rows={3} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      {errors.length > 0 && <div className="notice notice-error" role="alert">{errors.map((m) => <p key={m}>{m}</p>)}</div>}
      <div className="actions">
        <Link className="btn" to="/referrals">{t("common.cancel")}</Link>
        <button type="submit" className="btn btn-primary" disabled={busy}>{t("referrals.save")}</button>
      </div>
    </form>
  );
}
```

`frontend/src/pages/ReferralSlipPage.tsx`:

```tsx
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { referralsApi } from "../api/modules";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { displayValue } from "../forms/FormRenderer";
import { pick, useI18n } from "../i18n/i18n";

export function ReferralSlipPage() {
  const { referralId = "" } = useParams();
  const { t, lang } = useI18n();
  const referral = useApi(() => referralsApi.get(referralId), [referralId]);
  const formType = referral.data?.visit?.form_type;
  const form = useApi(async () => (formType ? api.getForm(formType) : null), [formType]);
  if (referral.error) return <LoadError error={referral.error} onRetry={referral.reload} />;
  if (!referral.data) return <Loading />;
  const r = referral.data;
  const visit = r.visit;
  return (
    <>
      <div className="page-head no-print">
        <Link to="/referrals?tab=referrals">{t("slip.back")}</Link>
        <button type="button" className="btn btn-primary" onClick={() => window.print()}>{t("slip.print")}</button>
      </div>
      <article className="card slip">
        <h1>{t("slip.title")}</h1>
        <p className="muted">{t("slip.draftNote")}</p>
        <dl className="slip-grid">
          <dt>{t("slip.date")}</dt><dd>{r.created_at.slice(0, 10)}</dd>
          <dt>{t("slip.patient")}</dt><dd>{r.patient_name}</dd>
          <dt>{t("slip.birthDate")}</dt><dd>{r.birth_date ?? "—"}</dd>
          <dt>{t("slip.sex")}</dt><dd>{r.sex ? t(`member.sex.${r.sex}`) : "—"}</dd>
          <dt>{t("slip.address")}</dt><dd>{[r.sitio, r.barangay].filter(Boolean).join(", ")}</dd>
          <dt>{t("referrals.facility")}</dt><dd>{r.facility}</dd>
          <dt>{t("referrals.urgency")}</dt><dd>{t(`referrals.urgency.${r.urgency}`)}</dd>
          <dt>{t("referrals.reason")}</dt><dd>{r.reason}</dd>
          {r.notes && (<><dt>{t("referrals.notes")}</dt><dd>{r.notes}</dd></>)}
          <dt>{t("slip.referredBy")}</dt><dd>{r.created_by_name}</dd>
          <dt>{t("slip.status")}</dt><dd>{t(`referrals.status.${r.status}`)}</dd>
        </dl>
        {visit && form.data && (
          <section>
            <h2>{t("slip.findings", { date: visit.visit_date })}</h2>
            <div className="table-wrap">
              <table className="table">
                <tbody>
                  {form.data.fields.filter((f) => visit.values[f.name] != null).map((f) => (
                    <tr key={f.name}>
                      <th scope="row">{pick(f.label, lang)}</th>
                      <td>{displayValue(visit.values[f.name], t)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        <p className="slip-sign">{t("slip.receivedBy")}: ______________________________</p>
      </article>
    </>
  );
}
```

In `frontend/src/routes.tsx`, import the three pages and add these children before `"*"`:

```tsx
      { path: "referrals", element: <ReferralsPage /> },
      { path: "referrals/new", element: <ReferralNewPage /> },
      { path: "referrals/:referralId/slip", element: <ReferralSlipPage /> },
```

In `frontend/src/pages/CheckupPage.tsx`:
- Import `FlagBanner` from `"../components/FlagBanner"`.
- After the line `{readOnly && <p className="notice">{t("checkup.readOnly")}</p>}`, add:

```tsx
      {visit?.status === "final" && <FlagBanner visitId={visit.id} />}
```

In `frontend/src/pages/PatientPage.tsx`:
- Import `FlagBanner`.
- After the closing `</div>` of `page-head`, add `<FlagBanner patientId={p.id} />`.
- Inside the `page-head`'s first `<div>`, after the household link, add:

```tsx
          {" · "}<Link to={`/referrals/new?patient=${encodeURIComponent(p.id)}`}>{t("referrals.refer")}</Link>
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `npx vitest run src/pages/referrals.test.tsx`

Expected: 3 tests pass.

Run: `npx vitest run`

Expected: all pass.

- [ ] **Step 5: Stop. No git operations.**

---

### Task 7: Medicine and supplies tab (frontend)

**Files:**
- Create: `frontend/src/pages/SuppliesPage.tsx`, `SupplyItemPage.tsx`, `SupplyRequestPage.tsx`, `supplies.test.tsx`
- Modify: `frontend/src/routes.tsx`

**Interfaces:**
- Consumes: `suppliesApi`, `toCsv`, `downloadFile` and `todayIso`.
- Produces: the routes `supplies`, `supplies/request-list` and `supplies/:itemId`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/pages/supplies.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import type { SupplyItem } from "../api/types";
import { todayIso } from "../lib/dates";
import { admin, page } from "../test/fixtures";
import { callsTo, mockApi, signedInAs } from "../test/http";
import { renderApp } from "../test/render";
import { readText } from "../lib/download";

const ors: SupplyItem = {
  id: "s1", name: "ORS sachets", unit: "sachets", low_stock_threshold: 50, target_level: 200, active: true,
  on_hand: 40, low: true, created_at: "2026-10-01", updated_at: "2026-10-01",
};

describe("supplies", () => {
  it("shows stock with a low-stock badge", async () => {
    mockApi({ ...signedInAs(admin), "GET /supplies": [200, [ors]] });
    renderApp("/supplies", { signedIn: true });
    expect(await screen.findByText("ORS sachets")).toBeInTheDocument();
    expect(screen.getByText("40 sachets on hand")).toBeInTheDocument();
    expect(screen.getByText("Low stock")).toBeInTheDocument();
  });

  it("records a distribution and shows the server's stock check", async () => {
    let posts = 0;
    const { calls } = mockApi({
      ...signedInAs(admin),
      "GET /supplies/s1": [200, ors],
      "GET /supplies/s1/movements": [200, page([])],
      "POST /supplies/s1/movements": () => (++posts === 1
        ? [201, { id: "m1" }]
        : [422, { detail: ["quantity: only 30 sachets in stock"] }]),
    });
    const { user } = renderApp("/supplies/s1", { signedIn: true });
    await user.selectOptions(await screen.findByLabelText("Type"), "distributed");
    await user.type(screen.getByLabelText("Quantity"), "10");
    await user.click(screen.getByRole("button", { name: "Record stock movement" }));
    expect(await screen.findByText("Stock movement recorded")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/supplies/s1/movements")[0].body).toEqual({
      kind: "distributed", quantity: 10, movement_date: todayIso(), note: null,
    });
    await user.type(screen.getByLabelText("Quantity"), "99");
    await user.click(screen.getByRole("button", { name: "Record stock movement" }));
    expect(await screen.findByText("quantity: only 30 sachets in stock")).toBeInTheDocument();
  });

  it("exports the request list as CSV", async () => {
    mockApi({ ...signedInAs(admin), "GET /supplies/request-list": [200, [{ ...ors, request_quantity: 160 }]] });
    const { user } = renderApp("/supplies/request-list", { signedIn: true });
    expect(await screen.findByText("160")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Export CSV" }));
    const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls.at(-1)![0] as Blob;
    expect(await readText(blob)).toContain("ORS sachets,sachets,40,200,160");
  });
});
```

- [ ] **Step 2: Run them and check they fail**

Run: `npx vitest run src/pages/supplies.test.tsx`

Expected: FAIL, because the routes are missing.

- [ ] **Step 3: Implement**

`frontend/src/pages/SuppliesPage.tsx`:

```tsx
import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { suppliesApi } from "../api/modules";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";

const EMPTY = { name: "", unit: "", low: "", target: "" };

export function SuppliesPage() {
  const { t } = useI18n();
  const toast = useToast();
  const items = useApi(suppliesApi.list, []);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(EMPTY);

  async function add(event: FormEvent) {
    event.preventDefault();
    try {
      await suppliesApi.create({ name: draft.name.trim(), unit: draft.unit.trim(),
        low_stock_threshold: Number(draft.low), target_level: Number(draft.target) });
      toast(t("supplies.itemAdded"));
      setDraft(EMPTY);
      setAdding(false);
      items.reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  const field = (key: keyof typeof EMPTY) => ({
    value: draft[key], onChange: (e: ChangeEvent<HTMLInputElement>) => setDraft({ ...draft, [key]: e.target.value }),
  });

  return (
    <>
      <div className="page-head">
        <h1>{t("supplies.title")}</h1>
        <div className="row-actions">
          <Link className="btn" to="/supplies/request-list">{t("supplies.requestList")}</Link>
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>{t("supplies.addItem")}</button>
        </div>
      </div>
      {adding && (
        <form className="card" onSubmit={add}>
          <div className="inline-fields">
            <label className="stack">{t("supplies.name")}<input required maxLength={120} {...field("name")} /></label>
            <label className="stack">{t("supplies.unit")}<input required maxLength={40} {...field("unit")} /></label>
            <label className="stack">{t("supplies.threshold")}<input type="number" required min={0} step={1} {...field("low")} /></label>
            <label className="stack">{t("supplies.target")}<input type="number" required min={0} step={1} {...field("target")} /></label>
          </div>
          <div className="actions">
            <button type="button" className="btn" onClick={() => setAdding(false)}>{t("common.cancel")}</button>
            <button type="submit" className="btn btn-primary">{t("common.save")}</button>
          </div>
        </form>
      )}
      {items.error ? <LoadError error={items.error} onRetry={items.reload} /> : !items.data ? <Loading /> :
        items.data.length === 0 ? <p className="empty">{t("supplies.none")}</p> : (
          <div className="bento">
            {items.data.map((item) => (
              <Link key={item.id} to={`/supplies/${item.id}`} className={`bento-card${item.low ? " tone-alert" : ""}`}>
                <h2 className="bento-title">{item.name}</h2>
                <p className="bento-note">{t("supplies.onHand", { count: item.on_hand, unit: item.unit })}</p>
                {item.low && <span className="badge badge-overdue">{t("supplies.low")}</span>}
              </Link>
            ))}
          </div>
        )}
    </>
  );
}
```

`frontend/src/pages/SupplyItemPage.tsx`:

```tsx
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { suppliesApi } from "../api/modules";
import type { MovementKind } from "../api/types";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";
import { todayIso } from "../lib/dates";

const KINDS: MovementKind[] = ["received", "distributed", "adjusted"];

export function SupplyItemPage() {
  const { itemId = "" } = useParams();
  const { t } = useI18n();
  const toast = useToast();
  const item = useApi(() => suppliesApi.get(itemId), [itemId]);
  const movements = useApi(() => suppliesApi.movements(itemId, { limit: 100 }), [itemId]);
  const [kind, setKind] = useState<MovementKind>("received");
  const [quantity, setQuantity] = useState("");
  const [movementDate, setMovementDate] = useState(todayIso());
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [levels, setLevels] = useState<{ low: string; target: string } | null>(null);

  async function record(event: FormEvent) {
    event.preventDefault();
    setErrors([]);
    try {
      await suppliesApi.addMovement(itemId, { kind, quantity: Number(quantity), movement_date: movementDate,
        note: note.trim() || null });
      toast(t("supplies.recorded"));
      setQuantity("");
      setNote("");
      item.reload();
      movements.reload();
    } catch (failure) {
      setErrors(failure instanceof ApiError ? failure.messages : [errorText(failure, t)]);
    }
  }

  async function saveLevels(event: FormEvent) {
    event.preventDefault();
    if (!levels) return;
    try {
      await suppliesApi.update(itemId, { low_stock_threshold: Number(levels.low), target_level: Number(levels.target) });
      toast(t("supplies.saved"));
      setLevels(null);
      item.reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  if (item.error) return <LoadError error={item.error} onRetry={item.reload} />;
  if (!item.data) return <Loading />;
  const it = item.data;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow"><Link to="/supplies">{t("supplies.title")}</Link></p>
          <h1>{it.name}</h1>
          <p>{t("supplies.onHand", { count: it.on_hand, unit: it.unit })}
            {it.low && <> <span className="badge badge-overdue">{t("supplies.low")}</span></>}</p>
        </div>
      </div>
      <form className="card" onSubmit={record}>
        <h2>{t("supplies.recordMovement")}</h2>
        <div className="inline-fields">
          <label className="stack">{t("supplies.kind")}
            <select value={kind} onChange={(e) => setKind(e.target.value as MovementKind)}>
              {KINDS.map((k) => <option key={k} value={k}>{t(`supplies.kind.${k}`)}</option>)}
            </select>
          </label>
          <label className="stack">{t("supplies.quantity")}
            <input type="number" required step={1} min={kind === "adjusted" ? undefined : 1} value={quantity}
              onChange={(e) => setQuantity(e.target.value)} />
          </label>
          <label className="stack">{t("supplies.date")}
            <input type="date" required max={todayIso()} value={movementDate} onChange={(e) => setMovementDate(e.target.value)} />
          </label>
          <label className="stack">{t("supplies.note")}
            <input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
        </div>
        {kind === "adjusted" && <p className="hint">{t("supplies.adjustHint")}</p>}
        {errors.length > 0 && <div className="notice notice-error" role="alert">{errors.map((m) => <p key={m}>{m}</p>)}</div>}
        <div className="actions"><button type="submit" className="btn btn-primary">{t("supplies.recordMovement")}</button></div>
      </form>
      <section className="card">
        <div className="card-head">
          <h2>{t("supplies.settings")}</h2>
          {!levels && (
            <button type="button" className="btn btn-small"
              onClick={() => setLevels({ low: String(it.low_stock_threshold), target: String(it.target_level) })}>
              {t("common.save")}
            </button>
          )}
        </div>
        {levels ? (
          <form className="inline-form" onSubmit={saveLevels}>
            <label className="stack">{t("supplies.threshold")}
              <input type="number" min={0} step={1} required value={levels.low} onChange={(e) => setLevels({ ...levels, low: e.target.value })} />
            </label>
            <label className="stack">{t("supplies.target")}
              <input type="number" min={0} step={1} required value={levels.target} onChange={(e) => setLevels({ ...levels, target: e.target.value })} />
            </label>
            <button type="submit" className="btn btn-primary btn-small">{t("common.save")}</button>
            <button type="button" className="btn btn-small" onClick={() => setLevels(null)}>{t("common.cancel")}</button>
          </form>
        ) : (
          <p className="muted">{t("supplies.threshold")}: {it.low_stock_threshold} · {t("supplies.target")}: {it.target_level}</p>
        )}
      </section>
      <section className="card">
        <h2>{t("supplies.history")}</h2>
        {movements.data && movements.data.items.length === 0 && <p className="empty">{t("supplies.noHistory")}</p>}
        {movements.data && movements.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead><tr>
                <th scope="col">{t("supplies.date")}</th><th scope="col">{t("supplies.kind")}</th>
                <th scope="col">{t("supplies.quantity")}</th><th scope="col">{t("supplies.by")}</th>
                <th scope="col">{t("supplies.note")}</th>
              </tr></thead>
              <tbody>
                {movements.data.items.map((m) => (
                  <tr key={m.id}>
                    <td>{m.movement_date}</td><td>{t(`supplies.kind.${m.kind}`)}</td>
                    <td>{m.quantity > 0 ? `+${m.quantity}` : m.quantity}</td><td>{m.recorded_by_name}</td><td>{m.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
```

`frontend/src/pages/SupplyRequestPage.tsx`:

```tsx
import { Link } from "react-router-dom";
import { suppliesApi } from "../api/modules";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { useI18n } from "../i18n/i18n";
import { todayIso } from "../lib/dates";
import { downloadFile, toCsv } from "../lib/download";

export function SupplyRequestPage() {
  const { t } = useI18n();
  const list = useApi(suppliesApi.requestList, []);
  if (list.error) return <LoadError error={list.error} onRetry={list.reload} />;
  if (!list.data) return <Loading />;
  const rows = list.data;

  function exportCsv() {
    const csv = toCsv([
      [t("supplies.name"), t("supplies.unit"), t("supplies.quantity"), t("supplies.target"), t("supplies.request")],
      ...rows.map((r) => [r.name, r.unit, r.on_hand, r.target_level, r.request_quantity]),
    ]);
    downloadFile(`supply-request-${todayIso()}.csv`, csv, "text/csv");
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow no-print"><Link to="/supplies">{t("supplies.title")}</Link></p>
          <h1>{t("supplies.requestTitle")}</h1>
          <p className="muted">{t("supplies.requestIntro")} {todayIso()}</p>
        </div>
        <div className="row-actions no-print">
          <button type="button" className="btn" onClick={() => window.print()}>{t("supplies.print")}</button>
          <button type="button" className="btn btn-primary" disabled={rows.length === 0} onClick={exportCsv}>
            {t("supplies.exportCsv")}
          </button>
        </div>
      </div>
      {rows.length === 0 ? <p className="empty">{t("supplies.requestNone")}</p> : (
        <div className="card table-wrap">
          <table className="table">
            <thead><tr>
              <th scope="col">{t("supplies.name")}</th><th scope="col">{t("supplies.quantity")}</th>
              <th scope="col">{t("supplies.target")}</th><th scope="col">{t("supplies.request")}</th>
            </tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.name} ({r.unit})</td><td>{r.on_hand}</td><td>{r.target_level}</td><td><strong>{r.request_quantity}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
```

In `frontend/src/routes.tsx`, import the three pages and add these children before `"*"`:

```tsx
      { path: "supplies", element: <SuppliesPage /> },
      { path: "supplies/request-list", element: <SupplyRequestPage /> },
      { path: "supplies/:itemId", element: <SupplyItemPage /> },
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `npx vitest run src/pages/supplies.test.tsx`

Expected: 3 tests pass.

- [ ] **Step 5: Stop. No git operations.**

---

### Task 8: Reports tab with AI draft (frontend)

**Files:**
- Create: `frontend/src/pages/ReportsPage.tsx`, `frontend/src/pages/reports.test.tsx`
- Modify: `frontend/src/routes.tsx`

**Interfaces:**
- Consumes: `reportsApi`, `api.aiStatus`, `api.listForms`, `useListParams`, `toCsv`, `downloadFile` and `todayIso`.
- Produces: the route `reports` (`?period=week|month&date=`).

- [ ] **Step 1: Write the failing tests**

`frontend/src/pages/reports.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import type { ReportDraft, ReportFigures, ReportSummary } from "../api/types";
import { admin, bpForm } from "../test/fixtures";
import { callsTo, mockApi, signedInAs, type Route } from "../test/http";
import { renderApp } from "../test/render";

const figures = (visits: number): ReportFigures => ({
  start: "2026-10-05", end: "2026-10-11", visits: { total: visits, final: visits, by_form: { bp_followup: visits } },
  new_households: 1, new_patients: 2, follow_ups_completed: 0, follow_ups_overdue: 1, referral_flags: 1,
  referrals_issued: 1, referrals_by_reason: { "Very high BP": 1 },
  supplies: [{ name: "ORS", unit: "sachets", received: 20, distributed: 15 }], low_stock_items: ["ORS"],
});
const summary: ReportSummary = { period: "week", current: figures(7), previous: figures(3), unsynced_records: 4 };
const draft: ReportDraft = {
  id: "d1", period: "week", start_date: "2026-10-05", end_date: "2026-10-11", figures: summary,
  text: "Consider a BP screening day.", status: "draft", model: "fake", created_by: "u1", approved_by: null,
  created_at: "2026-10-10", updated_at: "2026-10-10",
};

function backend(extra: Record<string, Route> = {}) {
  return mockApi({
    ...signedInAs(admin),
    "GET /reports/summary": [200, summary],
    "GET /reports/drafts": [200, []],
    "GET /ai/status": [200, { available: true, model: "Qwen" }],
    "GET /forms": [200, [bpForm]],
    ...extra,
  });
}

describe("reports", () => {
  it("compares with the previous period and warns about unsynced records", async () => {
    const { calls, } = backend();
    const { user } = renderApp("/reports?date=2026-10-10", { signedIn: true });
    expect(await screen.findByText("4 records are not yet transferred to the RHU, so RHU figures may differ.")).toBeInTheDocument();
    const visitsCard = () => screen.getByRole("heading", { name: "Visits" }).closest("section")!;
    expect(within(visitsCard()).getByText("previous: 3")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Period"), "month");
    await screen.findAllByText("previous: 3");
    expect(calls.map((c) => c.path)).toContain("/reports/summary?period=month&date=2026-10-10");
  });

  it("generates, edits and approves an AI draft", async () => {
    const { calls } = backend({
      "POST /reports/drafts": [201, draft],
      "PATCH /reports/drafts/d1": [200, { ...draft, status: "approved", text: "Edited." }],
    });
    const { user } = renderApp("/reports?date=2026-10-10", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Generate AI draft" }));
    const text = await screen.findByLabelText("Draft text");
    expect(text).toHaveValue("Consider a BP screening day.");
    await user.clear(text);
    await user.type(text, "Edited.");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Summary approved")).toBeInTheDocument();
    expect(callsTo(calls, "PATCH", "/reports/drafts/d1")[0].body).toEqual({ text: "Edited.", status: "approved" });
  });

  it("falls back to writing by hand when the AI is unavailable", async () => {
    const { calls } = backend({
      "POST /reports/drafts": [503, { detail: "AI assistant unavailable — please fill in the form manually" }],
      "POST /reports/drafts/manual": [201, { ...draft, id: "d2", model: null, text: "Hand written." }],
      "PATCH /reports/drafts/d2": [200, { ...draft, id: "d2", status: "approved" }],
    });
    const { user } = renderApp("/reports?date=2026-10-10", { signedIn: true });
    await user.click(await screen.findByRole("button", { name: "Generate AI draft" }));
    expect(await screen.findByText("AI assistant unavailable — write the summary by hand.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Write without AI" }));
    await user.type(screen.getByLabelText("Draft text"), "Hand written.");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText("Summary approved");
    expect(callsTo(calls, "POST", "/reports/drafts/manual")[0].body).toEqual({
      period: "week", date: "2026-10-10", text: "Hand written.",
    });
  });
});
```

- [ ] **Step 2: Run them and check they fail**

Run: `npx vitest run src/pages/reports.test.tsx`

Expected: FAIL, because the route is missing.

- [ ] **Step 3: Implement**

`frontend/src/pages/ReportsPage.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { reportsApi } from "../api/modules";
import type { Period, ReportDraft, ReportFigures } from "../api/types";
import { useApi } from "../api/useApi";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { pick, useI18n } from "../i18n/i18n";
import { todayIso } from "../lib/dates";
import { downloadFile, toCsv } from "../lib/download";
import { useListParams } from "../lib/useListParams";

type Metric = { key: string; value: (f: ReportFigures) => number };
const METRICS: Metric[] = [
  { key: "reports.visits", value: (f) => f.visits.total },
  { key: "reports.finalVisits", value: (f) => f.visits.final },
  { key: "reports.newHouseholds", value: (f) => f.new_households },
  { key: "reports.newPatients", value: (f) => f.new_patients },
  { key: "reports.followUpsCompleted", value: (f) => f.follow_ups_completed },
  { key: "reports.followUpsOverdue", value: (f) => f.follow_ups_overdue },
  { key: "reports.referralFlags", value: (f) => f.referral_flags },
  { key: "reports.referralsIssued", value: (f) => f.referrals_issued },
];

export function ReportsPage() {
  const { t, lang } = useI18n();
  const { params, update } = useListParams();
  const period: Period = params.get("period") === "month" ? "month" : "week";
  const day = params.get("date") || todayIso();
  const summary = useApi(() => reportsApi.summary(period, day), [period, day]);
  const drafts = useApi(() => reportsApi.drafts(period, day), [period, day]);
  const ai = useApi(api.aiStatus, []);
  const forms = useApi(api.listForms, []);
  const formTitle = (type: string) => {
    const form = forms.data?.find((f) => f.form_type === type);
    return form ? pick(form.title, lang) : type;
  };

  function exportCsv() {
    if (!summary.data) return;
    const { current, previous } = summary.data;
    const csv = toCsv([
      [t("reports.metric"), t("reports.current"), t("reports.previousPeriod")],
      ...METRICS.map((m) => [t(m.key), m.value(current), m.value(previous)]),
      [],
      [t("reports.byForm"), t("reports.current"), t("reports.previousPeriod")],
      ...Object.keys({ ...current.visits.by_form, ...previous.visits.by_form }).map((type) =>
        [formTitle(type), current.visits.by_form[type] ?? 0, previous.visits.by_form[type] ?? 0]),
      [],
      [t("reports.suppliesMoved"), t("reports.received"), t("reports.distributed")],
      ...current.supplies.map((s) => [`${s.name} (${s.unit})`, s.received, s.distributed]),
    ]);
    downloadFile(`report-${period}-${current.start}.csv`, csv, "text/csv");
  }

  return (
    <>
      <div className="page-head">
        <h1>{t("reports.title")}</h1>
        <button type="button" className="btn no-print" disabled={!summary.data} onClick={exportCsv}>{t("reports.exportCsv")}</button>
      </div>
      <div className="controls no-print">
        <label className="stack">{t("reports.period")}
          <select value={period} onChange={(e) => update({ period: e.target.value })}>
            <option value="week">{t("reports.week")}</option>
            <option value="month">{t("reports.month")}</option>
          </select>
        </label>
        <label className="stack">{t("reports.date")}
          <input type="date" value={day} onChange={(e) => update({ date: e.target.value })} />
        </label>
      </div>
      {summary.error ? <LoadError error={summary.error} onRetry={summary.reload} /> : !summary.data ? <Loading /> : (
        <>
          <p className="muted">{t("reports.range", { start: summary.data.current.start, end: summary.data.current.end })}</p>
          {summary.data.unsynced_records > 0 && (
            <p className="notice">
              {t("reports.unsynced", { count: summary.data.unsynced_records })} <Link to="/sync">{t("nav.sync")}</Link>
            </p>
          )}
          <div className="bento">
            {METRICS.map((m) => (
              <section key={m.key} className="bento-card">
                <h2 className="bento-title">{t(m.key)}</h2>
                <p className="bento-value">{m.value(summary.data!.current)}</p>
                <p className="report-compare">{t("reports.previous", { value: m.value(summary.data!.previous) })}</p>
              </section>
            ))}
          </div>
          <div className="two-col" style={{ marginTop: 16 }}>
            <section className="card">
              <h2>{t("reports.byForm")}</h2>
              <Breakdown rows={Object.entries(summary.data.current.visits.by_form).map(([k, v]) => [formTitle(k), v])} />
              <h2>{t("reports.byReason")}</h2>
              <Breakdown rows={Object.entries(summary.data.current.referrals_by_reason)} />
            </section>
            <section className="card">
              <h2>{t("reports.suppliesMoved")}</h2>
              {summary.data.current.supplies.length === 0 ? <p className="empty">{t("reports.nothing")}</p> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th scope="col">{t("supplies.name")}</th><th scope="col">{t("reports.received")}</th>
                      <th scope="col">{t("reports.distributed")}</th></tr></thead>
                    <tbody>
                      {summary.data.current.supplies.map((s) => (
                        <tr key={s.name}><td>{s.name} ({s.unit})</td><td>{s.received}</td><td>{s.distributed}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <h2>{t("reports.lowStock")}</h2>
              {summary.data.current.low_stock_items.length === 0 ? <p className="empty">{t("reports.nothing")}</p> :
                <p>{summary.data.current.low_stock_items.join(", ")}</p>}
            </section>
          </div>
          <DraftPanel key={`${period}:${day}`} period={period} day={day} aiAvailable={Boolean(ai.data?.available)}
            drafts={drafts.data ?? []} onChanged={drafts.reload} />
        </>
      )}
    </>
  );
}

function Breakdown({ rows }: { rows: [string, number][] }) {
  const { t } = useI18n();
  if (rows.length === 0) return <p className="empty">{t("reports.nothing")}</p>;
  return (
    <div className="table-wrap">
      <table className="table"><tbody>
        {rows.map(([label, value]) => <tr key={label}><th scope="row">{label}</th><td>{value}</td></tr>)}
      </tbody></table>
    </div>
  );
}

type Props = { period: Period; day: string; aiAvailable: boolean; drafts: ReportDraft[]; onChanged: () => void };

function DraftPanel({ period, day, aiAvailable, drafts, onChanged }: Props) {
  const { t } = useI18n();
  const toast = useToast();
  const [editing, setEditing] = useState<{ id: string | null; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const open = drafts.find((d) => d.status === "draft");
  const approved = drafts.filter((d) => d.status === "approved");

  async function generate() {
    setBusy(true);
    setAiError(null);
    try {
      const created = await reportsApi.createAiDraft(period, day);
      setEditing({ id: created.id, text: created.text });
      onChanged();
    } catch (failure) {
      setAiError(failure instanceof ApiError && failure.status === 503 ? t("reports.aiUnavailable") : errorText(failure, t));
    } finally {
      setBusy(false);
    }
  }

  async function save(approve: boolean) {
    if (!editing) return;
    setBusy(true);
    try {
      let draftId = editing.id;
      if (!draftId) draftId = (await reportsApi.createManualDraft(period, day, editing.text)).id;
      await reportsApi.updateDraft(draftId, approve ? { text: editing.text, status: "approved" } : { text: editing.text });
      toast(t(approve ? "reports.approved" : "reports.draftSaved"));
      setEditing(approve ? null : { id: draftId, text: editing.text });
      onChanged();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" style={{ marginTop: 16 }}>
      <h2>{t("reports.draftTitle")}</h2>
      <p className="muted">{t("reports.draftNote")}</p>
      {!editing && (
        <div className="row-actions" style={{ marginLeft: 0 }}>
          <button type="button" className="btn btn-gold" disabled={!aiAvailable || busy} onClick={() => void generate()}>
            {t("reports.generate")}
          </button>
          <button type="button" className="btn" onClick={() => setEditing({ id: null, text: "" })}>{t("reports.writeManually")}</button>
          {open && (
            <button type="button" className="btn" onClick={() => setEditing({ id: open.id, text: open.text })}>
              {t("reports.continue")}
            </button>
          )}
        </div>
      )}
      {busy && !editing && <p className="muted" role="status">{t("reports.generating")}</p>}
      {aiError && <p className="notice notice-error" role="alert">{aiError}</p>}
      {editing && (
        <>
          <label className="stack">{t("reports.draftText")}
            <textarea rows={8} maxLength={5000} value={editing.text} onChange={(e) => setEditing({ ...editing, text: e.target.value })} />
          </label>
          <div className="actions">
            <button type="button" className="btn" disabled={busy || !editing.text.trim()} onClick={() => void save(false)}>
              {t("reports.saveDraft")}
            </button>
            <button type="button" className="btn btn-primary" disabled={busy || !editing.text.trim()} onClick={() => void save(true)}>
              {t("reports.approve")}
            </button>
          </div>
        </>
      )}
      {approved.map((d) => (
        <article key={d.id} className="notice">
          <p className="muted">{t("reports.approvedOn", { date: d.updated_at.slice(0, 10) })}</p>
          <p className="draft-text">{d.text}</p>
        </article>
      ))}
    </section>
  );
}
```

In `frontend/src/routes.tsx`, import `ReportsPage` and add `{ path: "reports", element: <ReportsPage /> },` before `"*"`.

- [ ] **Step 4: Run the tests and check they pass**

Run: `npx vitest run src/pages/reports.test.tsx`

Expected: 3 tests pass.

- [ ] **Step 5: Stop. No git operations.**

---

### Task 9: Sync tab (frontend)

**Files:**
- Create: `frontend/src/pages/SyncPage.tsx`, `frontend/src/pages/sync.test.tsx`
- Modify: `frontend/src/routes.tsx`

**Interfaces:**
- Consumes: `syncApi`, `useAuth`, `downloadFile` and `errorText`.
- Produces: the route `sync`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/pages/sync.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import type { SyncStatus } from "../api/types";
import { admin, volunteer } from "../test/fixtures";
import { callsTo, mockApi, signedInAs, type Route } from "../test/http";
import { renderApp } from "../test/render";
import { readText } from "../lib/download";

const counts = (pending: number, awaiting = 0, synced = 0) => ({ pending, awaiting, synced });
const status: SyncStatus = {
  station_id: "station-ab12cd34", passphrase_set: true, last_acknowledged_at: null, open_bundles: 1,
  records: { household: counts(1), patient: counts(2), visit: counts(3, 1), follow_up: counts(0),
    referral: counts(1), supply_item: counts(0), supply_movement: counts(0) },
};
const openBundle = { id: "b1", record_count: 4, created_at: "2026-10-10 08:00:00", acknowledged_at: null, created_by_name: "Ada Admin" };

function backend(user = admin, extra: Record<string, Route> = {}) {
  return mockApi({
    ...signedInAs(user),
    "GET /sync/status": [200, status],
    "GET /sync/bundles": [200, [openBundle]],
    "POST /sync/bundles": [201, { bundle_id: "b2", station_id: "station-ab12cd34", record_count: 7, payload: [] }],
    ...extra,
  });
}

describe("sync", () => {
  it("creates and downloads a transfer file", async () => {
    const { calls } = backend();
    const { user } = renderApp("/sync", { signedIn: true });
    expect(await screen.findByText("Finalized visits")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create transfer file" }));
    expect(await screen.findByText("Transfer file created with 7 records. Give it to the RHU.")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/sync/bundles")).toHaveLength(1);
    const blob = (URL.createObjectURL as ReturnType<typeof vi.fn>).mock.calls.at(-1)![0] as Blob;
    expect(JSON.parse(await readText(blob)).bundle_id).toBe("b2");
  });

  it("imports a receipt and shows a clear error for a bad one", async () => {
    let attempt = 0;
    const { calls } = backend(admin, {
      "POST /sync/receipts": () => (++attempt === 1
        ? [422, { detail: ["signature: this receipt was not signed with this device's RHU passphrase"] }]
        : [200, { ...openBundle, acknowledged_at: "2026-10-10 09:00:00" }]),
    });
    const { user } = renderApp("/sync", { signedIn: true });
    const input = await screen.findByLabelText("Receipt file from the RHU");
    const receipt = { format: "gitkeepers-receipt-v1", bundle_id: "b1", record_count: 4, signature: "x" };
    await user.upload(input, new File([JSON.stringify(receipt)], "r.json", { type: "application/json" }));
    expect(await screen.findByText("signature: this receipt was not signed with this device's RHU passphrase"))
      .toBeInTheDocument();
    await user.upload(input, new File([JSON.stringify(receipt)], "r.json", { type: "application/json" }));
    expect(await screen.findByText("Receipt accepted: records marked as synced")).toBeInTheDocument();
    expect(callsTo(calls, "POST", "/sync/receipts")[1].body).toEqual(receipt);
    await user.upload(input, new File(["not json"], "r.json", { type: "application/json" }));
    expect(await screen.findByText("This file is not a receipt (not valid JSON).")).toBeInTheDocument();
  });

  it("shows volunteers the status but not the admin actions", async () => {
    backend(volunteer);
    renderApp("/sync", { signedIn: true });
    expect(await screen.findByText("Only an admin can create transfer files and import receipts.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create transfer file" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run them and check they fail**

Run: `npx vitest run src/pages/sync.test.tsx`

Expected: FAIL, because the route is missing.

- [ ] **Step 3: Implement**

`frontend/src/pages/SyncPage.tsx`:

```tsx
import { useState, type ChangeEvent, type FormEvent } from "react";
import { syncApi } from "../api/modules";
import type { SyncBundle } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthProvider";
import { BentoCard } from "../components/BentoCard";
import { LoadError, Loading } from "../components/Status";
import { errorText, useToast } from "../components/Toast";
import { useI18n } from "../i18n/i18n";
import { downloadFile, readText } from "../lib/download";

const TYPES = ["household", "patient", "visit", "follow_up", "referral", "supply_item", "supply_movement"];

function saveBundle(bundle: SyncBundle) {
  downloadFile(`gitkeepers-${bundle.station_id}-${bundle.bundle_id}.json`, JSON.stringify(bundle, null, 2), "application/json");
}

export function SyncPage() {
  const { t } = useI18n();
  const toast = useToast();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const status = useApi(syncApi.status, []);
  const bundles = useApi(syncApi.bundles, []);
  const [busy, setBusy] = useState(false);
  const [receiptError, setReceiptError] = useState<string | null>(null);
  const [passphrase, setPassphrase] = useState("");
  const reload = () => {
    status.reload();
    bundles.reload();
  };

  async function createBundle() {
    setBusy(true);
    try {
      const bundle = await syncApi.createBundle();
      saveBundle(bundle);
      toast(t("sync.bundleCreated", { count: bundle.record_count }));
      reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    } finally {
      setBusy(false);
    }
  }

  async function downloadAgain(bundleId: string) {
    try {
      saveBundle(await syncApi.getBundle(bundleId));
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  async function importReceipt(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // allow picking the same file again
    if (!file) return;
    let receipt: unknown;
    try {
      receipt = JSON.parse(await readText(file));
    } catch {
      setReceiptError(t("sync.notJson"));
      return;
    }
    try {
      await syncApi.sendReceipt(receipt);
      setReceiptError(null);
      toast(t("sync.receiptAccepted"));
      reload();
    } catch (failure) {
      setReceiptError(errorText(failure, t));
    }
  }

  async function savePassphrase(event: FormEvent) {
    event.preventDefault();
    try {
      await syncApi.setPassphrase(passphrase);
      setPassphrase("");
      toast(t("sync.passphraseSaved"));
      reload();
    } catch (failure) {
      toast(errorText(failure, t), "error");
    }
  }

  if (status.error) return <LoadError error={status.error} onRetry={status.reload} />;
  if (!status.data) return <Loading />;
  const s = status.data;
  const total = (key: "pending" | "awaiting") => Object.values(s.records).reduce((sum, c) => sum + c[key], 0);
  const open = (bundles.data ?? []).filter((b) => !b.acknowledged_at);
  const done = (bundles.data ?? []).filter((b) => b.acknowledged_at);

  return (
    <>
      <div className="page-head"><h1>{t("sync.title")}</h1></div>
      <p className="muted">{t("sync.manualNote")}</p>
      <div className="bento">
        <BentoCard title={t("sync.pending")} value={total("pending")} tone={total("pending") ? "gold" : undefined} />
        <BentoCard title={t("sync.awaiting")} value={total("awaiting")} />
        <BentoCard title={t("sync.lastReceipt")} value={s.last_acknowledged_at?.slice(0, 10) ?? t("sync.never")} note={s.station_id} />
      </div>
      <section className="card" style={{ marginTop: 16 }}>
        <div className="table-wrap">
          <table className="table">
            <thead><tr>
              <th scope="col">{t("sync.type")}</th><th scope="col">{t("sync.pending")}</th>
              <th scope="col">{t("sync.awaiting")}</th><th scope="col">{t("sync.synced")}</th>
            </tr></thead>
            <tbody>
              {TYPES.filter((type) => s.records[type]).map((type) => (
                <tr key={type}>
                  <th scope="row">{t(`sync.type.${type}`)}</th>
                  <td>{s.records[type].pending}</td><td>{s.records[type].awaiting}</td><td>{s.records[type].synced}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {isAdmin ? (
          <div className="actions">
            {!s.passphrase_set && <p className="muted">{t("sync.needPassphrase")}</p>}
            <button type="button" className="btn btn-primary" disabled={busy || !s.passphrase_set || total("pending") === 0}
              onClick={() => void createBundle()}>
              {t("sync.createBundle")}
            </button>
          </div>
        ) : <p className="notice">{t("sync.adminOnly")}</p>}
      </section>
      <section className="card">
        <h2>{t("sync.awaitingFiles")}</h2>
        {open.length === 0 ? <p className="empty">{t("sync.noAwaiting")}</p> : (
          <ul className="list">
            {open.map((b) => (
              <li key={b.id} className="list-row">
                <span>{t("sync.fileLine", { date: b.created_at.slice(0, 16), count: b.record_count })}</span>
                {isAdmin && (
                  <div className="row-actions">
                    <button type="button" className="btn btn-small" onClick={() => void downloadAgain(b.id)}>{t("sync.downloadAgain")}</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {isAdmin && (
          <>
            <h2>{t("sync.importReceipt")}</h2>
            <label className="stack">{t("sync.receiptFile")}
              <input type="file" accept=".json,application/json" onChange={(e) => void importReceipt(e)} />
            </label>
            {receiptError && <p className="notice notice-error" role="alert">{receiptError}</p>}
          </>
        )}
      </section>
      {done.length > 0 && (
        <section className="card">
          <h2>{t("sync.history")}</h2>
          <ul className="list">
            {done.map((b) => (
              <li key={b.id} className="list-row">
                <span>{t("sync.fileLine", { date: b.acknowledged_at!.slice(0, 16), count: b.record_count })}</span>
                <span className="badge badge-final">{t("sync.synced")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {isAdmin && (
        <form className="card" onSubmit={savePassphrase}>
          <h2>{t("sync.passphraseTitle")}</h2>
          <p className="muted">{t("sync.passphraseHint")}</p>
          {s.passphrase_set && <p>{t("sync.passphraseSet")}</p>}
          <div className="inline-form">
            <label className="stack">{t("sync.passphrase")}
              <input type="password" autoComplete="new-password" required minLength={12} maxLength={200}
                value={passphrase} onChange={(e) => setPassphrase(e.target.value)} />
            </label>
            <button type="submit" className="btn btn-primary">{t("common.save")}</button>
          </div>
        </form>
      )}
    </>
  );
}
```

In `frontend/src/routes.tsx`, import `SyncPage` and add `{ path: "sync", element: <SyncPage /> },` before `"*"`.

- [ ] **Step 4: Run all frontend tests and the build**

Run: `npx vitest run`

Expected: all pass.

Run: `npm run build`

Expected: no TypeScript errors.

- [ ] **Step 5: Stop. No git operations.**

---

### Task 10: Docs, full verification and live smoke test

**Files:**
- Modify: `README.md` and `LOG.md`

- [ ] **Step 1: Document**

In `README.md`, add this block after the "Checkup forms…" table paragraph that ends with `422 { "detail": [...] }`:

```markdown
Referrals, supplies, reports and sync:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/referral-rules` | Referral rules per form (`backend/referral_rules/*.json`, draft pending professional review). Finalizing a visit records a flag for every rule it meets; the AI is never involved |
| `GET` | `/api/v1/referral-flags?status=open&patient_id=&visit_id=` | Flags; `POST /referral-flags/{id}/dismiss` closes one |
| `POST` / `GET` | `/api/v1/referrals`, `/api/v1/referrals/{id}` | Create (optionally from a flag) and read referral slips |
| `GET` / `POST` | `/api/v1/supplies`, `/api/v1/supplies/{id}/movements` | Items with on-hand stock (sum of movements) and low-stock flag; record received / distributed / adjusted |
| `GET` | `/api/v1/supplies/request-list` | Low items with the quantity needed to reach the target |
| `GET` | `/api/v1/reports/summary?period=week\|month&date=` | Counts for the period and the previous one, plus unsynced records |
| `POST` | `/api/v1/reports/drafts` / `/reports/drafts/manual` | AI draft from aggregated numbers only (503 when the model is off) or a hand-written draft; `PATCH /reports/drafts/{id}` edits or approves |
| `GET` | `/api/v1/sync/status` | Pending / awaiting receipt / synced counts per record type |
| `PUT` | `/api/v1/sync/settings` | Admin: RHU passphrase (12+ characters) |
| `POST` | `/api/v1/sync/bundles` | Admin: encrypted, de-identified transfer file of all pending records |
| `POST` | `/api/v1/sync/receipts` | Admin: RHU receipt (signed with the passphrase); only then are records marked synced |

At the RHU, `RHU_PASSPHRASE=... python -m scripts.rhu_receipt transfer.json` checks a transfer
file and writes the receipt to import back on the device.
```

Append a `LOG.md` entry using the actual date and time:

```markdown
## <date time>
- Referrals (rule files + flags on finalize + slips), medicine and supply tracking, weekly/monthly reports with editable AI drafts from aggregated numbers, and manual sync (encrypted transfer file + signed RHU receipt); the four "Coming soon" tabs are now live
```

- [ ] **Step 2: Run both suites and the build**

Run (`backend/`): `.venv/Scripts/python -m unittest discover -s tests`

Expected: OK, apart from the known pseudonymize marker test if it is still pending.

Run (`frontend/`): `npx vitest run`, then `npm run build`.

Expected: all pass, and the build is clean.

- [ ] **Step 3: Run the live smoke test on a throwaway database**

Start the backend on port 8799 with `APP_DATA_DIR` set to a new folder in the scratchpad. Then, with a scratchpad script using `httpx`:
1. Sign up an admin and register a patient.
2. Finalize a `bp_followup` visit with BP 190/100, and check that one flag is open.
3. Create a referral from that flag.
4. Add a supply item, receive 20 and distribute 5, and check `on_hand` is 15.
5. Get the report summary.
6. Set the passphrase and create a transfer file.
7. Write the receipt with `scripts.rhu_receipt.write_receipt`, post it, and check `/sync/status` shows no pending or awaiting records and that the referral is `sent`.

Stop the server.

- [ ] **Step 4: Stop. No git operations. Report.**
