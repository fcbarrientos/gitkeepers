# Checkup Visits, AI-Assisted Entry & Follow-Ups — Design

**Sub-project 2 of 7** for the GitKeepers offline-first rural healthcare system.
It covers these functional requirements:

- FR-04 AI-Assisted Data Entry
- FR-06 Structured Checkup Forms
- FR-08 Patient Follow-Up Tracking
- FR-16 Manual Workflow Fallback
- FR-18 AI Suggestion Review
- the "pseudonymize before the local AI" part of FR-15

Acceptance criteria: AC-04, AC-06, AC-08, AC-16, and the AI items of AC-12 and AC-14.

It builds on sub-project 1 (`docs/superpowers/specs/2026-10-10-auth-roles-design.md`).
Every endpoint here requires a signed-in active user (`signed_in` in `api.py`), and both
roles may use all of them.

## Context

These parts already exist:

- `core/extraction.py` turns a Filipino, Taglish, or English note into validated
  suggestions for 19 fields (`PRENATAL_FIELDS`). Unmentioned fields come back as `null`.
  It has few-shot prompts in `prompts/` and a 25-case eval set in `evals/`.
- `core/pseudonymize.py` (`Pseudonymizer.pseudonymize_text(text, known_entities)`)
  replaces names, phone numbers, PhilHealth numbers, and locations with deterministic
  tokens.
- `core/inference.py` has `LlamaCppLLM.chat_json(messages, schema, max_tokens)`.
  `MockLLM` has no `chat_json`. `api.get_llm()` falls back to `MockLLM` when the model
  file is missing.

These parts are missing:

- visits and checkup forms
- an HTTP endpoint for extraction
- extraction of child-growth and BP follow-up fields
- pseudonymizing a note before extraction
- follow-ups

## Decisions

| Topic | Decision |
|---|---|
| Form field source | Drafted from public DOH material: the Mother and Child Book, the EPI schedule, and common BP follow-up items. Each form file carries `"verification": "pending DOH review"`. A health professional can correct a form by editing JSON, with no code changes. |
| AI coverage | All three forms. Each field declares `"ai": true/false`. |
| Suggestion flow | Stateless suggestion call plus an audit record. The client submits the confirmed values together with the `suggestion_id` and the list of fields it accepted from the AI. The server records where each field's value came from. |
| Value storage | JSON per visit, validated against the form definition. Forms will change after DOH review, so fixed columns would mean a migration for every correction. SQLite `json_extract` can still query the values for reports. |
| Draft vs final | Drafts can be edited. Final visits are read-only (corrections are out of scope). Required fields are enforced only when a visit is finalized. |
| AI unavailable | The endpoint returns `503`. It never returns mock values. Manual entry keeps working. |

## Form definitions — `backend/forms/<form_type>.json`

There are three files: `prenatal.json`, `child_growth.json`, and `bp_followup.json`.

```json
{
  "form_type": "prenatal",
  "title": {"en": "Prenatal checkup", "fil": "Prenatal na checkup"},
  "verification": "pending DOH review",
  "default_follow_up_days": 28,
  "fields": [
    {"name": "bp_systolic", "type": "integer", "min": 50, "max": 260,
     "label": {"en": "BP systolic (mmHg)", "fil": "BP systolic (mmHg)"},
     "required": true, "ai": true},
    {"name": "td_dose", "type": "choice", "options": ["Td1", "Td2", "Td3", "Td4", "Td5"],
     "label": {"en": "Td dose given", "fil": "Ibinigay na Td dose"},
     "required": false, "ai": true}
  ]
}
```

Field types:

- `integer` and `number`, both with an optional `min`/`max`
- `boolean`
- `choice`: one value from `options`
- `choices`: a list of unique values from `options`

`null` (or omitting a field) means "not recorded".

### Field sets (draft, pending DOH review)

**prenatal** (default follow-up: 28 days). It includes every field in
`PRENATAL_FIELDS`, so the existing evals stay valid.

| name | type | range / options | required |
|---|---|---|---|
| weeks_pregnant | integer | 1–45 | yes |
| bp_systolic | integer | 50–260 | yes |
| bp_diastolic | integer | 30–160 | yes |
| weight_kg | number | 25–200 | |
| temperature_c | number | 30–45 | |
| fundal_height_cm | number | 5–50 | |
| fetal_heart_rate_bpm | integer | 60–220 | |
| td_dose | choice | Td1–Td5 | |
| iron_folic_acid_given | boolean | | |
| baby_moving, fever, bleeding, headache, dizziness, vomiting, cough, colds, sore_throat, shortness_of_breath, chest_pain, abdominal_pain, diarrhea, rash, body_pain | boolean | | |

**child_growth** (default follow-up: 28 days)

| name | type | range / options | required |
|---|---|---|---|
| weight_kg | number | 0.5–60 | yes |
| length_height_cm | number | 30–180 | |
| muac_cm | number | 5–30 | |
| temperature_c | number | 30–45 | |
| vaccines_given | choices | BCG, HepB, Penta1, Penta2, Penta3, OPV1, OPV2, OPV3, IPV, PCV1, PCV2, PCV3, MMR1, MMR2 | |
| vitamin_a_given | boolean | | |
| breastfeeding | choice | exclusive, partial, none | |
| fever, cough, colds, diarrhea, vomiting, rash | boolean | | |

**bp_followup** (default follow-up: 30 days)

| name | type | range / options | required |
|---|---|---|---|
| bp_systolic | integer | 50–260 | yes |
| bp_diastolic | integer | 30–160 | yes |
| pulse_bpm | integer | 30–220 | |
| weight_kg | number | 25–250 | |
| on_maintenance_meds | boolean | | |
| took_meds_today | boolean | | |
| headache, dizziness, chest_pain, shortness_of_breath, blurred_vision | boolean | | |

Every field in all three forms has `"ai": true`. Each field has English and Filipino
labels. The Filipino labels are drafts and should be reviewed together with the DOH
fields.

## Code layout

```
backend/
  forms/{prenatal,child_growth,bp_followup}.json
  core/forms.py        load + check form files at import; list_forms(), get_form(form_type),
                       validate_values(form, values, require_complete) -> list[str],
                       extraction_fields(form) -> dict  (the shape core.extraction expects)
  core/extraction.py   + "choice"/"choices" types; per-form few-shot file
  core/assist.py       suggest(conn, llm, patient, form, note, user_id) -> dict
                       (pseudonymize -> extract -> store ai_suggestions row)
  core/visits.py       create/get/list/update visits, provenance
  core/follow_ups.py   create/list/update/complete follow-ups, derived state
  routes/forms.py      GET /forms, GET /ai/status
  routes/visits.py     suggestions + visits endpoints
  routes/follow_ups.py follow-up endpoints
  migrations/004_visits_follow_ups.sql
  prompts/child_growth_fewshot.json, prompts/bp_followup_fewshot.json
  evals/samples_child_growth.jsonl, evals/samples_bp_followup.jsonl  (12 cases each)
  evals/scoring.py, evals/run_eval.py  (choice scoring, --form, --pseudonymize)
  tests/test_forms.py, tests/test_visits.py, tests/test_follow_ups.py
```

### Extraction changes (`core/extraction.py`)

- The field map keeps its shape: `name -> (type, extra)`. `extra` is the `(min, max)`
  range for numbers, `None` for booleans, and a tuple of options for `choice`/`choices`.
  `PRENATAL_FIELDS` is unchanged.
- `_check` accepts the new types:
  - `choice`: a string that is one of the options.
  - `choices`: a list of strings, each one of the options. Duplicates are removed and
    order is kept. Any invalid member rejects the whole value and records a problem.
- `schema_for` emits `enum` for `choice` and an array of enum items for `choices`.
- `build_messages(note, fields, fewshot=None, glossary=None, fewshot_file="prenatal_fewshot.json")`
  appends one line per option field to the system prompt: `"- <name>: one of [..]"` or
  `"- <name>: list of any of [..]"`.
- `extract(...)` gains `fewshot_file`, which it passes through to `build_messages`.
  Existing callers keep the prenatal default.

### Privacy (`core/assist.py`)

The note is masked in two passes before it is sent to the model:

1. **Known details, as whole words only.** The patient's full name and each name part of
   3+ characters (`"PATIENT"`), the patient and household contact numbers, including
   spaced variants (`"PHONE"`), and the household `barangay`, `sitio`, and
   `address_line` (`"LOCATION"`) are each replaced, case-insensitively, with a
   `Pseudonymizer` token. Patient "Ana" must not alter "Nanay" or "kanang".
   `pseudonymize_text`'s own `known_entities` isn't used, because it matches substrings
   and allows only one value per type.
2. **Pattern detection.** The masked text then goes through
   `Pseudonymizer().pseudonymize_text`. Its marker words (`si/ni/kay/kina`) become
   case-insensitive, so a sentence-initial "Si Maria" is caught.

Extracted values are only numbers, booleans, and options, so nothing needs to be
reversed. The original note is never sent to the model and never stored in
`ai_suggestions`.

### AI availability (`api.py`, `routes/forms.py`)

- A new dependency `get_assist_llm()` returns the loaded `LlamaCppLLM`, or raises
  `AIUnavailable` (an exception class defined in `core/assist.py`) when:
  - the model file is missing, or
  - loading the model raises an exception.

  An exception handler turns this into `503 {"detail": "AI assistant unavailable — please
  fill in the form manually"}`. Tests replace this dependency through
  `app.dependency_overrides`.
- If generation raises an exception, the response is `503` with the same message.
- If the model replies with output that can't be parsed (`ok: false`), the response is
  `200` with all values `null` and the problems listed. The UI shows "couldn't read the
  note".
- One module-level `Lock` serializes every model call, both chat and extraction, because
  llama.cpp isn't thread-safe.
- `GET /api/v1/ai/status` returns `{ "available": bool, "model": "<file name>" | null }`.
  It reports `available: true` only when the model file exists. It doesn't load the
  model.

## Data model — `migrations/004_visits_follow_ups.sql`

```sql
CREATE TABLE ai_suggestions (
    id            TEXT PRIMARY KEY,
    patient_id    TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    form_type     TEXT NOT NULL,
    values_json   TEXT NOT NULL,        -- suggested values, null = not suggested
    problems_json TEXT NOT NULL,        -- validation problems from the model output
    model         TEXT NOT NULL,
    duration_ms   INTEGER NOT NULL,
    created_by    TEXT NOT NULL REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE visits (
    id             TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    form_type      TEXT NOT NULL,
    visit_date     TEXT NOT NULL,       -- YYYY-MM-DD
    status         TEXT NOT NULL CHECK (status IN ('draft', 'final')),
    values_json    TEXT NOT NULL,
    sources_json   TEXT NOT NULL,       -- {field: "manual" | "ai_accepted" | "ai_edited"}
    note           TEXT,                -- original note, preserved verbatim
    suggestion_id  TEXT REFERENCES ai_suggestions(id),
    recorded_by    TEXT NOT NULL REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    finalized_at   TEXT
);
CREATE INDEX idx_visits_patient ON visits(patient_id, visit_date DESC);

CREATE TABLE follow_ups (
    id                  TEXT PRIMARY KEY,
    patient_id          TEXT NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    source_visit_id     TEXT REFERENCES visits(id),
    form_type           TEXT,           -- which form the follow-up visit should use
    due_date            TEXT NOT NULL,  -- YYYY-MM-DD
    reason              TEXT,
    status              TEXT NOT NULL CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    completed_visit_id  TEXT REFERENCES visits(id),
    completed_at        TEXT,
    created_by          TEXT NOT NULL REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_follow_ups_due ON follow_ups(status, due_date);
CREATE INDEX idx_follow_ups_patient ON follow_ups(patient_id);
```

## Rules

1. **Value validation** (`validate_values`):
   - Unknown keys are errors.
   - Values must match their type and range or options. A float with a whole value is
     accepted for `integer`.
   - If `require_complete` is set, every required field must be non-null.

   All errors are returned at once as `422 {"detail": ["<field>: <problem>", ...]}`.
2. **Visit dates.** `visit_date` cannot be in the future (by the device's local date).
   `note` is at most 5000 characters.
3. **Provenance.** On save, each non-null field gets a source:
   - The field is in `ai_accepted_fields` and its value equals the suggestion's value →
     `ai_accepted`.
   - The field is in `ai_accepted_fields` but the user changed the value → `ai_edited`.
   - Otherwise → `manual`.

   `ai_accepted_fields` must be a subset of the fields the suggestion actually filled
   (non-null), or the request fails with `422`. If a `suggestion_id` is given, it must
   exist and match the visit's patient and form type, or the request fails with `422`.
   `ai_accepted_fields` without a `suggestion_id` is also `422`.
4. **Draft and final.**
   - A visit is created as `draft` or `final`.
   - `PATCH` works only on drafts and may change `visit_date`, `values`, `note`,
     `suggestion_id`, and `ai_accepted_fields`. Provenance is recalculated.
   - Setting `status: "final"` validates with `require_complete`, sets `finalized_at`,
     and makes the visit read-only. Any later `PATCH` returns
     `409 "Finalized visits cannot be edited"`.
5. **Follow-ups attached to finalizing.** Two options, `follow_up {due_date, reason?}`
   and `completes_follow_up_id`, are accepted only on the request that makes the visit
   `final` (either create-as-final or the finalizing `PATCH`). On a draft they return
   `422`.
   - `follow_up` creates a scheduled follow-up for the same patient and form type. Its
     `source_visit_id` is set to this visit. `due_date` must be after `visit_date`.
   - `completes_follow_up_id` marks that follow-up `completed` and links it to this
     visit. The follow-up must belong to the same patient and must be `scheduled`,
     otherwise `409`.
   - Everything happens in one transaction with the visit write.
6. **Derived follow-up state** (`today` = the device's local date, which tests can patch):
   - `completed`: status completed
   - `cancelled`: status cancelled
   - `overdue`: scheduled and due before today
   - `due`: scheduled and due today
   - `upcoming`: scheduled and due after today
7. **Standalone follow-ups.**
   - `POST /patients/{id}/follow-ups` with `{due_date, reason?, form_type?}`. The due date
     must be today or later.
   - `PATCH /follow-ups/{id}` with `{due_date?, reason?, status?: "cancelled"}`. Only
     scheduled follow-ups can be changed (otherwise `409`).
   - `POST /follow-ups/{id}/complete` with `{visit_id?}` marks a scheduled follow-up
     completed. A given `visit_id` must be a final visit of the same patient.

## API

All paths are under `/api/v1` and require a signed-in user.

| Method | Path | Purpose |
|---|---|---|
| GET | `/forms` | All form definitions |
| GET | `/forms/{form_type}` | One form definition (`404` if unknown) |
| GET | `/ai/status` | `{available, model}` |
| POST | `/patients/{id}/suggestions` | `{form_type, note}` → `{suggestion_id, form_type, values, missing, problems}`. `missing` lists the AI-enabled fields left null. `503` if the AI is unavailable. |
| POST | `/patients/{id}/visits` | Create a visit (rules 1–5). Returns `201 Visit`. |
| GET | `/patients/{id}/visits?form_type=&limit=&offset=` | The visit timeline, newest first |
| GET | `/visits/{id}` | One visit |
| PATCH | `/visits/{id}` | Edit or finalize a draft |
| GET | `/follow-ups?state=&patient_id=&q=&limit=&offset=` | Paged list, sorted by due date, including patient name and barangay. `q` searches patient names. |
| POST | `/patients/{id}/follow-ups` | Create a standalone follow-up |
| PATCH | `/follow-ups/{id}` | Reschedule or cancel |
| POST | `/follow-ups/{id}/complete` | Mark completed |

The `Visit` response contains:

- `{ id, patient_id, form_type, visit_date, status, values, sources, note, suggestion_id,
  recorded_by, created_at, updated_at, finalized_at }`
- `follow_up_created`: the follow-up created by this request, or `null`

The `FollowUp` response contains:

- `{ id, patient_id, patient_name, barangay, source_visit_id, form_type, due_date, reason,
  status, state, completed_visit_id, completed_at, created_at, updated_at }`

An unknown patient, visit, or follow-up returns `404`. An unknown `form_type` returns
`422`.

## Model evaluation (real model, in scope)

The new forms are only worth shipping with AI assistance if the real model reads them
reliably, so this sub-project runs and tunes the evals itself.

1. **Setup.**
   - Install `llama-cpp-python` into `backend/.venv`. Use the prebuilt CPU wheel index
     from the README.
   - Download the model with `python -m scripts.download_model` (Qwen3-4B Q4_K_M,
     ~2.5 GB) into `config.MODELS_DIR`.
   - If the install or download can't be completed, stop the evaluation work. Record
     why in `LOG.md` and hand the eval run back to the team. Everything else in this
     spec still ships.
2. **Eval tooling.**
   - `evals/scoring.values_match` gains string equality for `choice` and order-insensitive
     set equality for `choices`.
   - `evals/run_eval.py` gains:
     - `--form <form_type>` (default `prenatal`), which picks that form's AI fields,
       few-shot file, and default samples file
     - `--pseudonymize`, which runs each note through `Pseudonymizer` first, the same way
       production does
   - Existing invocations behave exactly as before.
3. **Baseline first.** Before changing `core/extraction.py`, run the prenatal eval (raw
   and `--pseudonymize`) and record `overall`, `exact_match`, `parse_fail`, and
   `avg_seconds` in `LOG.md`.
4. **New cases.**
   - Add 12 realistic Filipino/Taglish/English cases each to
     `evals/samples_child_growth.jsonl` and `evals/samples_bp_followup.jsonl`. They must
     include negations ("walang lagnat"), omitted fields, and multi-vaccine notes. Like
     the existing file, they are marked as fake scenarios.
   - Few-shot examples must never reuse an eval note. The existing overlap test is
     extended to the new files.
5. **Targets**, all measured with `--pseudonymize`:
   - New forms: `parse_fail` = 0% and `exact_match` ≥ 75% (9/12).
   - Prenatal: `exact_match` must not fall below its pseudonymized baseline.
   - To reach a target, tune only the few-shot files, the glossary, and the prompt's
     option lines. Make at most 3 tuning rounds per form.
   - If a target is still missed, record the per-field misses in `LOG.md` and report
     them. A miss doesn't block shipping, because the AI is optional and every value is
     reviewed.
6. **Record** each run's summary table in `LOG.md`, using the existing dated-entry style.

## Testing

All tests use a fake LLM (a class with `chat_json` that returns canned JSON and records
the messages it was given) through `app.dependency_overrides`. No real model is needed.

- **test_forms.py**
  - All three form files load and pass checks: unique names, valid types, `min < max`,
    options present for choice types.
  - The prenatal AI fields include every field in `PRENATAL_FIELDS`.
  - `validate_values` covers each type, unknown keys, required fields on complete, and a
    whole float accepted for an integer field.
  - Extraction: `_check` and `schema_for` handle `choice`/`choices`; `build_messages`
    lists the options; each new few-shot file uses only valid fields and values and
    doesn't overlap its eval samples.
- **test_visits.py**
  - Suggestion endpoint: the values come back, and the fake LLM's messages don't contain
    the patient's name, contact number, or barangay.
  - With no model, the response is `503` with the manual-entry message.
  - With a fake LLM that raises, the response is `503`.
  - With unparseable output, the response is `200` with every value null and the
    problems listed.
  - An `ai_suggestions` row is stored, and it doesn't contain the note.
  - Visits:
    - create a draft with missing required fields → OK
    - finalize with them still missing → `422` listing them
    - an out-of-range value → `422`
    - an unknown field → `422`
    - a future date → `422`
  - Provenance: accepted, edited, manual, an accepted field the suggestion didn't fill →
    `422`, and a suggestion for a different patient → `422`.
  - `PATCH` on a final visit → `409`.
  - The timeline is ordered newest first.
  - Every endpoint returns `401` without a token.
- **test_follow_ups.py**
  - The derived state for each case, with today patched.
  - Finalizing with `follow_up` creates one linked to the visit, in the same transaction.
  - `completes_follow_up_id` completes it. Reusing it gives `409`; using it on a draft
    gives `422`.
  - Standalone create, reschedule, and cancel; editing a completed follow-up gives `409`.
  - List filtering by state, patient, and name search, ordered by due date.

The existing `test_extraction.py` must pass unchanged. New unit tests cover
`values_match` for `choice`/`choices` and `run_eval`'s field and file selection for
`--form`. These tests use no model.

## Out of scope

- Referral rules, flags, and slips (sub-project 3). Visit values are stored so that
  sub-project 3 can evaluate rules against them.
- AI-generated summaries (sub-project 5).
- Editing or correcting finalized visits, and deleting visits or follow-ups.
- Verifying the form fields against official DOH forms (a team or health-professional
  task).
