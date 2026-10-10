# Checkup Visits, AI-Assisted Entry & Follow-Ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let health workers record prenatal, child-growth and BP follow-up checkups from data-defined forms, get AI field suggestions from a pseudonymized note (then confirm them with provenance recorded), and schedule and track follow-ups. Also run and tune the real-model evals for the new forms.

**Architecture:**
- Form definitions are JSON files in `backend/forms/`, loaded by `core/forms.py`. They drive both validation and the AI extraction field map.
- `core/extraction.py` gains `choice`/`choices` types and a per-form few-shot file.
- `core/assist.py` owns the shared model, its lock, note masking, and the `ai_suggestions` audit table.
- `core/visits.py` and `core/follow_ups.py` are service layers.
- `routes/forms.py`, `routes/visits.py` and `routes/follow_ups.py` expose `/api/v1` endpoints behind `signed_in`.
- A small `core/errors.ApiError` (now the base of `AuthError`) carries status and detail to one handler.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, sqlite3 (JSON columns), unittest. `llama-cpp-python` + Qwen3-4B-Q4_K_M are used only for the eval runs.

**Spec:** `docs/superpowers/specs/2026-10-10-visits-ai-followups-design.md` (builds on `docs/superpowers/specs/2026-10-10-auth-roles-design.md`)

## Global Constraints

- **Do not run `git commit`, `git push`, or create branches.** The user handles git.
- Work from `gitkeepers/backend/`. Run Python with `.venv/Scripts/python`.
- Test command: `.venv/Scripts/python -W ignore -m unittest discover -s tests`. Every task ends with this suite green. The pre-existing 81 tests must keep passing unchanged, and `tests/test_extraction.py` must not be edited.
- Every new endpoint is under `/api/v1` and uses `dependencies=signed_in`. Both roles may use them.
- Form files carry `"verification": "pending DOH review"`. Every field has `en` and `fil` labels.
- Field types are exactly `integer`, `number`, `boolean`, `choice`, `choices`. `null` means "not recorded".
- Error bodies:
  - service-level validation: `422 {"detail": ["<field>: <problem>", ...]}`
  - other service errors: `{"detail": "<message>"}`
- Exact messages:
  - `"AI assistant unavailable — please fill in the form manually"` (503)
  - `"Finalized visits cannot be edited"` (409)
  - `"Only scheduled follow-ups can be changed"` (409)
  - `"Follow-up is not scheduled"` (409)
  - `"Patient not found"`, `"Visit not found"`, `"Follow-up not found"`, `"Form not found"` (404)
  - 422 items: `"<name>: required"`, `"<name>: unknown field"`, `"visit_date: cannot be in the future"`, `"form_type: unknown form"`, `"follow_up: only allowed when finalizing"`, `"follow_up.due_date: must be after visit_date"`, `"ai_accepted_fields: requires suggestion_id"`, `"suggestion_id: does not match this patient and form"`, `"<name>: the AI did not suggest a value"`, `"due_date: cannot be in the past"`, `"visit_id: must be a finalized visit of the same patient"`
- The original note is never sent to the model and never stored in `ai_suggestions`.
- Every model call (chat and extraction) runs under `core.assist.MODEL_LOCK`.
- Eval targets, measured with `--pseudonymize`:
  - new forms: `parse_fail` = 0% and `exact_match` ≥ 75%
  - prenatal: `exact_match` must not fall below its pseudonymized baseline
  - at most 3 tuning rounds per form, touching only few-shot files, the glossary and the prompt's option lines
- Record every eval run in `LOG.md` as a dated entry (`## DD/MM/YY HH:MM`, bullets), matching the existing style.

## Review Focus

- **The AI writes an option in another spelling** (`"penta 2"`, `"hepb"`, `"Exclusive"`) → normalized to the canonical option. Pinned in Task 2, `test_choice_values_are_normalized_to_canonical_spelling`.
- **Numbers sent as JSON strings** (`"bp_systolic": "120"`) → 422, never silently coerced. Pinned in Task 3, `test_validate_values_rejects_wrong_types`.
- **A patient's name appears inside other words** (patient "Ana", note says "kanang braso" / "Nanay") → only the whole name is masked, and other words stay intact. Pinned in Task 5, `test_mask_note_replaces_whole_words_only`.
- **Double-submit of a finalize** (finalize PATCH twice, or the same `completes_follow_up_id` twice) → the second gets 409, with no duplicate follow-up. Pinned in Task 6, `test_patch_on_final_visit_is_rejected`, and Task 7, `test_completing_twice_is_rejected`.
- **Search text with only punctuation** (`q=!!!`) on the follow-up list → an empty page, not a 500. Pinned in Task 7, `test_list_filters_and_ordering`.

---

### Task 1: Model setup, `--pseudonymize` eval flag, prenatal baseline

**Files:**
- Modify: `evals/run_eval.py` (`evaluate` signature and `main` args)
- Create: `tests/test_eval_tools.py`
- Modify: `LOG.md` (repo root)

**Interfaces:**
- Produces: `evals.run_eval.evaluate(llm, samples, fields=PRENATAL_FIELDS, fewshot=None, glossary=None, on_sample=None, pseudonymize=False) -> dict` and the CLI flag `--pseudonymize`

- [ ] **Step 1: Start the model download in the background** (about 2.5 GB, so let it run while you work)

Run in the background: `.venv/Scripts/python -m scripts.download_model`
Expected (when done): it prints a path ending in `models\Qwen3-4B-Q4_K_M.gguf` under `C:\Users\Admin\AppData\Local\YourAppName\YourAppName\`.

- [ ] **Step 2: Install the prebuilt llama.cpp wheel**

Run: `.venv/Scripts/python -m pip install llama-cpp-python --only-binary llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu`
Expected: `Successfully installed llama-cpp-python-…`. If no wheel matches, **or** the download in Step 1 fails:
- record a `LOG.md` entry explaining why
- write the ledger ruling "eval work handed back to team"
- skip the real-model steps in Tasks 1, 4 and 5 (Task 1 Steps 6–7, Task 4 Steps 6–8, Task 5 Step 12), which are the only steps that need the model
- do everything else

- [ ] **Step 3: Write the failing test**

Create `tests/test_eval_tools.py`:
```python
import unittest

from evals.run_eval import evaluate


class RecordingLLM:
    """Records the note text each extraction call receives."""
    def __init__(self):
        self.notes = []

    def chat_json(self, messages, schema, max_tokens=512):
        self.notes.append(messages[-1]["content"])
        return "{}"


SAMPLE = [{"id": "x1", "note": "Buntis si Maria, 28 weeks. Tawagan sa 09171234567.",
           "expected": {"weeks_pregnant": 28}}]


class PseudonymizeFlagTests(unittest.TestCase):
    def test_notes_are_masked_only_when_asked(self):
        masked = RecordingLLM()
        evaluate(masked, SAMPLE, pseudonymize=True)
        self.assertNotIn("Maria", masked.notes[0])
        self.assertNotIn("09171234567", masked.notes[0])
        self.assertIn("28 weeks", masked.notes[0])
        raw = RecordingLLM()
        evaluate(raw, SAMPLE)
        self.assertIn("Maria", raw.notes[0])
```

- [ ] **Step 4: Run it to verify it fails**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_eval_tools -v`
Expected: ERROR `TypeError: evaluate() got an unexpected keyword argument 'pseudonymize'`.

- [ ] **Step 5: Implement**

In `evals/run_eval.py`, add `from core.pseudonymize import Pseudonymizer` below the existing `core` imports. Replace the start of `evaluate` with:
```python
def evaluate(llm, samples, fields=PRENATAL_FIELDS, fewshot=None, glossary=None, on_sample=None,
             pseudonymize=False) -> dict:
    results = []
    for s in samples:
        # --pseudonymize sends the note through the same masking production uses.
        note = Pseudonymizer().pseudonymize_text(s["note"]) if pseudonymize else s["note"]
        start = time.time()
        out = extract(llm, note, fields, fewshot, glossary)
```
(The rest of the loop body is unchanged.) In `main()`, add:
```python
    ap.add_argument("--pseudonymize", action="store_true",
                    help="mask names, phones and places in each note first, as production does")
```
and change the call to `out = evaluate(llm, samples, on_sample=progress, pseudonymize=args.pseudonymize)`.

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_eval_tools -v` → PASS. Then run the full suite → green.

- [ ] **Step 6: Run the prenatal baseline** (requires Steps 1–2 to be done)

Run both commands and keep their SUMMARY tables:
```bash
.venv/Scripts/python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf
.venv/Scripts/python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf --pseudonymize
```
Expected: two SUMMARY rows with `fields`, `exact`, `parse_fail` and `avg s`.

- [ ] **Step 7: Log the baseline**

Append to `LOG.md`:
```markdown

## DD/MM/YY HH:MM
- Prenatal extraction baseline before the visits/forms work (Qwen3-4B-Q4_K_M, 25 samples):
  - raw notes: fields <x>%, exact <y>%, parse_fail <z>%, avg <s>s
  - pseudonymized notes (`--pseudonymize`): fields <x>%, exact <y>%, parse_fail <z>%, avg <s>s
- Added `--pseudonymize` to `evals/run_eval.py` so evals see the same masked notes as production
```
(Fill in the real numbers and the current date and time.)

---

### Task 2: Extraction option types and option-aware scoring

**Files:**
- Modify: `core/extraction.py` (`_check`, `schema_for`, `build_messages`, `extract`, plus a new `check_value` alias)
- Modify: `evals/scoring.py` (`values_match`)
- Test: `tests/test_eval_tools.py` (append)

**Interfaces:**
- Produces:
  - `core.extraction.check_value(value, ftype, extra) -> (clean, problem|None)`, the public name for `_check`
  - field-map entries `("choice", options_tuple)` and `("choices", options_tuple)`
  - `build_messages(note, fields=PRENATAL_FIELDS, fewshot=None, glossary=None, fewshot_file="prenatal_fewshot.json")`
  - `extract(llm, note, fields=PRENATAL_FIELDS, fewshot=None, glossary=None, max_tokens=512, fewshot_file="prenatal_fewshot.json")`
  - `evals.scoring.values_match` handles strings (equality) and lists (set equality)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_eval_tools.py`:
```python
import json

from core.extraction import build_messages, check_value, parse_and_validate, schema_for
from evals.scoring import values_match

VACCINES = ("BCG", "HepB", "Penta1", "Penta2", "OPV1", "OPV2")
FEEDING = ("exclusive", "partial", "none")
OPTION_FIELDS = {"vaccines_given": ("choices", VACCINES), "breastfeeding": ("choice", FEEDING),
                 "weight_kg": ("number", (0.5, 60))}


class OptionTypeTests(unittest.TestCase):
    def test_choice_values_are_normalized_to_canonical_spelling(self):
        self.assertEqual(check_value("Exclusive", "choice", FEEDING), ("exclusive", None))
        self.assertEqual(check_value(["penta 2", "hepb", "Penta2"], "choices", VACCINES), (["Penta2", "HepB"], None))

    def test_invalid_options_are_rejected_whole(self):
        value, problem = check_value("sometimes", "choice", FEEDING)
        self.assertIsNone(value)
        self.assertIn("one of", problem)
        value, problem = check_value(["BCG", "Rabies"], "choices", VACCINES)
        self.assertIsNone(value)
        self.assertIn("Rabies", problem)
        self.assertEqual(check_value("BCG", "choices", VACCINES)[0], None)  # not a list

    def test_empty_choices_list_means_not_recorded(self):
        self.assertEqual(check_value([], "choices", VACCINES), (None, None))

    def test_schema_uses_enums(self):
        props = schema_for(OPTION_FIELDS)["properties"]
        self.assertEqual(props["breastfeeding"]["enum"], [*FEEDING, None])
        self.assertEqual(props["vaccines_given"]["items"]["enum"], list(VACCINES))
        self.assertEqual(props["weight_kg"], {"type": ["number", "null"]})

    def test_prompt_lists_options_and_uses_the_given_fewshot_file(self):
        shots = [{"note": "BCG given", "fields": {"vaccines_given": ["BCG"], "fever": True}}]
        messages = build_messages("Penta 1 today", OPTION_FIELDS, fewshot=shots, glossary={})
        system = messages[0]["content"]
        self.assertIn("- breastfeeding: one of ['exclusive', 'partial', 'none']", system)
        self.assertIn("- vaccines_given: list of any of", system)
        self.assertEqual(json.loads(messages[2]["content"]), {"vaccines_given": ["BCG"]})  # unknown field dropped

    def test_parse_and_validate_handles_option_fields(self):
        r = parse_and_validate('{"vaccines_given": ["OPV 1"], "breastfeeding": "partial"}', OPTION_FIELDS)
        self.assertEqual(r["fields"], {"vaccines_given": ["OPV1"], "breastfeeding": "partial", "weight_kg": None})


class OptionScoringTests(unittest.TestCase):
    def test_strings_and_lists(self):
        self.assertTrue(values_match("partial", "partial"))
        self.assertFalse(values_match("partial", "none"))
        self.assertTrue(values_match(["BCG", "HepB"], ["HepB", "BCG"]))
        self.assertFalse(values_match(["BCG"], ["BCG", "HepB"]))
        self.assertFalse(values_match(["BCG"], "BCG"))
        self.assertTrue(values_match(38, 38.0))  # numbers unchanged
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_eval_tools -v`
Expected: ERROR `ImportError: cannot import name 'check_value'`.

- [ ] **Step 3: Implement extraction changes**

In `core/extraction.py`, change the comment above `PRENATAL_FIELDS` to:
```python
# field -> (json type, extra). extra is the (min, max) sanity range for numbers, None for
# booleans, or the tuple of allowed options for "choice"/"choices".
# null always means "the note does not mention this".
```
Replace `schema_for` with:
```python
def _json_schema(ftype: str, extra) -> dict:
    if ftype == "choice":
        return {"type": ["string", "null"], "enum": [*extra, None]}
    if ftype == "choices":
        return {"type": ["array", "null"], "items": {"type": "string", "enum": list(extra)}}
    return {"type": [ftype, "null"]}


def schema_for(fields: dict) -> dict:
    return {
        "type": "object",
        "properties": {k: _json_schema(t, extra) for k, (t, extra) in fields.items()},
        "additionalProperties": False,
    }
```
In `build_messages`, change the signature to
`def build_messages(note: str, fields: dict = PRENATAL_FIELDS, fewshot=None, glossary=None, fewshot_file: str = "prenatal_fewshot.json") -> list:`
and change its first line to `fewshot = load_json(fewshot_file) if fewshot is None else fewshot`. After the `gloss = ...` line, add:
```python
    options = "".join(
        f"- {name}: one of {list(extra)}\n" if ftype == "choice" else f"- {name}: list of any of {list(extra)}\n"
        for name, (ftype, extra) in fields.items()
        if ftype in ("choice", "choices")
    )
    if options:
        options = "Fields with fixed options (copy the spelling exactly):\n" + options
```
Then insert `f"{options}"` into the `system` string directly before `f"Glossary (Filipino to English):\n{gloss}\n"`.

Replace `_check` with:
```python
def _canonical(value, options):
    """Match an option ignoring case, spaces, '-' and '_' ('penta 2' -> 'Penta2')."""
    if not isinstance(value, str):
        return None
    wanted = re.sub(r"[\s_-]", "", value).lower()
    return next((o for o in options if re.sub(r"[\s_-]", "", o).lower() == wanted), None)


def _check(value, ftype, rng):
    """Return (clean_value, problem_or_None)."""
    if value is None:
        return None, None
    if ftype == "boolean":
        return (value, None) if isinstance(value, bool) else (None, f"expected true/false, got {value!r}")
    if ftype == "choice":
        option = _canonical(value, rng)
        return (option, None) if option else (None, f"expected one of {list(rng)}, got {value!r}")
    if ftype == "choices":
        if not isinstance(value, list):
            return None, f"expected a list from {list(rng)}, got {value!r}"
        options = [_canonical(v, rng) for v in value]
        bad = [v for v, o in zip(value, options) if o is None]
        if bad:
            return None, f"{bad!r} not in {list(rng)}"
        return (list(dict.fromkeys(options)) or None), None  # [] means nothing recorded
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f"expected a number, got {value!r}"
    if ftype == "integer":
        if isinstance(value, float) and not value.is_integer():
            return None, f"expected a whole number, got {value!r}"
        value = int(value)
    else:
        value = float(value)
    if rng and not (rng[0] <= value <= rng[1]):
        return None, f"{value} is outside the plausible range {rng}"
    return value, None


check_value = _check  # public name for core.forms
```
Change `extract` to:
```python
def extract(llm, note: str, fields: dict = PRENATAL_FIELDS, fewshot=None, glossary=None,
            max_tokens: int = 512, fewshot_file: str = "prenatal_fewshot.json") -> dict:
    """llm must provide chat_json(messages, schema, max_tokens) -> str."""
    messages = build_messages(note, fields, fewshot, glossary, fewshot_file)
    raw = llm.chat_json(messages, schema_for(fields), max_tokens)
    return parse_and_validate(raw, fields)
```

- [ ] **Step 4: Implement scoring**

Replace `values_match` in `evals/scoring.py` with:
```python
def values_match(expected, got, tol: float = 0.05) -> bool:
    if expected is None or got is None:
        return expected is None and got is None
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected is got
    if isinstance(expected, list) or isinstance(got, list):  # "choices": order doesn't matter
        return isinstance(expected, list) and isinstance(got, list) and set(expected) == set(got)
    if isinstance(expected, str) or isinstance(got, str):    # "choice"
        return expected == got
    return abs(float(expected) - float(got)) <= tol
```

- [ ] **Step 5: Verify**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_eval_tools tests.test_extraction -v` → all PASS. Then the full suite → green.

---

### Task 3: Form definitions, `core/forms.py`, and `run_eval --form`

**Files:**
- Create: `forms/prenatal.json`, `forms/child_growth.json`, `forms/bp_followup.json`
- Create: `core/forms.py`
- Create: `tests/test_forms.py`
- Modify: `evals/run_eval.py` (`form_settings`, `--form`)

**Interfaces:**
- Consumes: `core.extraction.check_value`, `PRENATAL_FIELDS`
- Produces:
  - `core.forms.FORMS_DIR: Path` and `core.forms.FormError(ValueError)`
  - `core.forms.load_forms(forms_dir=FORMS_DIR) -> dict[str, dict]` and `core.forms.FORMS: dict[str, dict]`
  - `core.forms.list_forms() -> list[dict]` and `core.forms.get_form(form_type: str) -> dict | None`
  - `core.forms.extraction_fields(form: dict, ai_only: bool = True) -> dict` (field map)
  - `core.forms.validate_values(form: dict, values: dict, require_complete: bool) -> tuple[dict, list[str]]`. It returns a clean dict with **every** form field (None when not recorded) plus the problems. (The spec's `-> list[str]` is refined to also return the cleaned values, so callers don't re-parse.)
  - `evals.run_eval.form_settings(form_type: str) -> tuple[dict, str, Path]` (fields, few-shot file, samples path)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_forms.py`:
```python
import json
import tempfile
import unittest
from pathlib import Path

from core.extraction import PRENATAL_FIELDS
from core.forms import FormError, extraction_fields, get_form, list_forms, load_forms, validate_values
from evals.run_eval import form_settings


class FormFileTests(unittest.TestCase):
    def test_three_forms_load_with_required_metadata(self):
        self.assertEqual(sorted(f["form_type"] for f in list_forms()), ["bp_followup", "child_growth", "prenatal"])
        for form in list_forms():
            self.assertEqual(form["verification"], "pending DOH review")
            self.assertGreater(form["default_follow_up_days"], 0)
            for field in form["fields"]:
                self.assertTrue({"en", "fil"} <= set(field["label"]), field["name"])

    def test_prenatal_ai_fields_cover_the_original_extraction_fields(self):
        fields = extraction_fields(get_form("prenatal"))
        for name, spec in PRENATAL_FIELDS.items():
            self.assertEqual(fields[name][0], spec[0], name)

    def test_option_fields_map_to_extraction_types(self):
        fields = extraction_fields(get_form("child_growth"))
        self.assertEqual(fields["vaccines_given"][0], "choices")
        self.assertIn("Penta3", fields["vaccines_given"][1])
        self.assertEqual(fields["breastfeeding"], ("choice", ("exclusive", "partial", "none")))
        self.assertEqual(fields["weight_kg"], ("number", (0.5, 60)))

    def test_malformed_form_files_are_rejected(self):
        bad = [
            {"type": "decimal"},
            {"type": "choice"},
            {"type": "integer", "min": 10, "max": 5},
            {"type": "boolean", "label": {"en": "only english"}},
        ]
        for override in bad:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as tmp:
                field = {"name": "x", "type": "boolean", "label": {"en": "X", "fil": "X"}, **override}
                form = {"form_type": "t", "title": {"en": "T", "fil": "T"}, "verification": "pending DOH review",
                        "default_follow_up_days": 7, "fields": [field]}
                Path(tmp, "t.json").write_text(json.dumps(form), encoding="utf-8")
                with self.assertRaises(FormError):
                    load_forms(Path(tmp))

    def test_unknown_form_is_none(self):
        self.assertIsNone(get_form("dental"))


class ValidateValuesTests(unittest.TestCase):
    def setUp(self):
        self.form = get_form("bp_followup")

    def test_clean_values_include_every_field(self):
        clean, problems = validate_values(self.form, {"bp_systolic": 150.0, "headache": True}, False)
        self.assertEqual(problems, [])
        self.assertEqual(clean["bp_systolic"], 150)
        self.assertIs(clean["headache"], True)
        self.assertIsNone(clean["pulse_bpm"])
        self.assertEqual(set(clean), {f["name"] for f in self.form["fields"]})

    def test_validate_values_rejects_wrong_types(self):
        _, problems = validate_values(self.form, {"bp_systolic": "120", "headache": "yes", "pulse_bpm": 900}, False)
        self.assertEqual(len(problems), 3)
        self.assertTrue(problems[0].startswith("bp_systolic: "))

    def test_unknown_fields_and_required_on_complete(self):
        _, problems = validate_values(self.form, {"diagnosis": "HTN"}, True)
        self.assertIn("diagnosis: unknown field", problems)
        self.assertIn("bp_systolic: required", problems)
        self.assertIn("bp_diastolic: required", problems)
        _, draft_problems = validate_values(self.form, {}, False)
        self.assertEqual(draft_problems, [])

    def test_invalid_required_value_is_reported_once(self):
        _, problems = validate_values(self.form, {"bp_systolic": 999, "bp_diastolic": 90}, True)
        self.assertEqual([p for p in problems if p.startswith("bp_systolic")], [problems[0]])


class FormSettingsTests(unittest.TestCase):
    def test_settings_for_each_form(self):
        fields, fewshot_file, samples = form_settings("child_growth")
        self.assertIn("vaccines_given", fields)
        self.assertEqual(fewshot_file, "child_growth_fewshot.json")
        self.assertEqual(samples.name, "samples_child_growth.jsonl")
        self.assertEqual(form_settings("prenatal")[2].name, "samples.jsonl")
        with self.assertRaises(SystemExit):
            form_settings("dental")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_forms -v`
Expected: ERROR `ModuleNotFoundError: No module named 'core.forms'`.

- [ ] **Step 3: Write the form files**

Create `forms/prenatal.json`:
```json
{
  "form_type": "prenatal",
  "title": {"en": "Prenatal checkup", "fil": "Prenatal na checkup"},
  "verification": "pending DOH review",
  "default_follow_up_days": 28,
  "fields": [
    {"name": "weeks_pregnant", "type": "integer", "min": 1, "max": 45, "required": true, "ai": true,
     "label": {"en": "Age of gestation (weeks)", "fil": "Ilang linggo nang buntis"}},
    {"name": "bp_systolic", "type": "integer", "min": 50, "max": 260, "required": true, "ai": true,
     "label": {"en": "BP systolic (mmHg)", "fil": "BP systolic (mmHg)"}},
    {"name": "bp_diastolic", "type": "integer", "min": 30, "max": 160, "required": true, "ai": true,
     "label": {"en": "BP diastolic (mmHg)", "fil": "BP diastolic (mmHg)"}},
    {"name": "weight_kg", "type": "number", "min": 25, "max": 200, "ai": true,
     "label": {"en": "Weight (kg)", "fil": "Timbang (kg)"}},
    {"name": "temperature_c", "type": "number", "min": 30, "max": 45, "ai": true,
     "label": {"en": "Temperature (°C)", "fil": "Temperatura (°C)"}},
    {"name": "fundal_height_cm", "type": "number", "min": 5, "max": 50, "ai": true,
     "label": {"en": "Fundal height (cm)", "fil": "Taas ng tiyan / fundal height (cm)"}},
    {"name": "fetal_heart_rate_bpm", "type": "integer", "min": 60, "max": 220, "ai": true,
     "label": {"en": "Fetal heart rate (bpm)", "fil": "Tibok ng puso ng sanggol (bpm)"}},
    {"name": "td_dose", "type": "choice", "options": ["Td1", "Td2", "Td3", "Td4", "Td5"], "ai": true,
     "label": {"en": "Td dose given", "fil": "Ibinigay na Td dose"}},
    {"name": "iron_folic_acid_given", "type": "boolean", "ai": true,
     "label": {"en": "Iron-folic acid given", "fil": "Nabigyan ng iron-folic acid"}},
    {"name": "baby_moving", "type": "boolean", "ai": true, "label": {"en": "Baby moving", "fil": "Gumagalaw ang baby"}},
    {"name": "fever", "type": "boolean", "ai": true, "label": {"en": "Fever", "fil": "Lagnat"}},
    {"name": "bleeding", "type": "boolean", "ai": true, "label": {"en": "Bleeding", "fil": "Pagdurugo"}},
    {"name": "headache", "type": "boolean", "ai": true, "label": {"en": "Headache", "fil": "Sakit ng ulo"}},
    {"name": "dizziness", "type": "boolean", "ai": true, "label": {"en": "Dizziness", "fil": "Pagkahilo"}},
    {"name": "vomiting", "type": "boolean", "ai": true, "label": {"en": "Vomiting", "fil": "Pagsusuka"}},
    {"name": "cough", "type": "boolean", "ai": true, "label": {"en": "Cough", "fil": "Ubo"}},
    {"name": "colds", "type": "boolean", "ai": true, "label": {"en": "Colds", "fil": "Sipon"}},
    {"name": "sore_throat", "type": "boolean", "ai": true, "label": {"en": "Sore throat", "fil": "Masakit ang lalamunan"}},
    {"name": "shortness_of_breath", "type": "boolean", "ai": true, "label": {"en": "Shortness of breath", "fil": "Hirap huminga"}},
    {"name": "chest_pain", "type": "boolean", "ai": true, "label": {"en": "Chest pain", "fil": "Sakit ng dibdib"}},
    {"name": "abdominal_pain", "type": "boolean", "ai": true, "label": {"en": "Abdominal pain", "fil": "Sakit ng tiyan"}},
    {"name": "diarrhea", "type": "boolean", "ai": true, "label": {"en": "Diarrhea", "fil": "Pagtatae"}},
    {"name": "rash", "type": "boolean", "ai": true, "label": {"en": "Rash", "fil": "Pantal"}},
    {"name": "body_pain", "type": "boolean", "ai": true, "label": {"en": "Body pain", "fil": "Pananakit ng katawan"}}
  ]
}
```
Create `forms/child_growth.json`:
```json
{
  "form_type": "child_growth",
  "title": {"en": "Child growth and immunization", "fil": "Paglaki at bakuna ng bata"},
  "verification": "pending DOH review",
  "default_follow_up_days": 28,
  "fields": [
    {"name": "weight_kg", "type": "number", "min": 0.5, "max": 60, "required": true, "ai": true,
     "label": {"en": "Weight (kg)", "fil": "Timbang (kg)"}},
    {"name": "length_height_cm", "type": "number", "min": 30, "max": 180, "ai": true,
     "label": {"en": "Length/height (cm)", "fil": "Haba/taas (cm)"}},
    {"name": "muac_cm", "type": "number", "min": 5, "max": 30, "ai": true,
     "label": {"en": "MUAC (cm)", "fil": "MUAC (cm)"}},
    {"name": "temperature_c", "type": "number", "min": 30, "max": 45, "ai": true,
     "label": {"en": "Temperature (°C)", "fil": "Temperatura (°C)"}},
    {"name": "vaccines_given", "type": "choices", "ai": true,
     "options": ["BCG", "HepB", "Penta1", "Penta2", "Penta3", "OPV1", "OPV2", "OPV3", "IPV",
                 "PCV1", "PCV2", "PCV3", "MMR1", "MMR2"],
     "label": {"en": "Vaccines given today", "fil": "Mga bakunang ibinigay ngayon"}},
    {"name": "vitamin_a_given", "type": "boolean", "ai": true,
     "label": {"en": "Vitamin A given", "fil": "Nabigyan ng Vitamin A"}},
    {"name": "breastfeeding", "type": "choice", "options": ["exclusive", "partial", "none"], "ai": true,
     "label": {"en": "Breastfeeding", "fil": "Pagpapasuso"}},
    {"name": "fever", "type": "boolean", "ai": true, "label": {"en": "Fever", "fil": "Lagnat"}},
    {"name": "cough", "type": "boolean", "ai": true, "label": {"en": "Cough", "fil": "Ubo"}},
    {"name": "colds", "type": "boolean", "ai": true, "label": {"en": "Colds", "fil": "Sipon"}},
    {"name": "diarrhea", "type": "boolean", "ai": true, "label": {"en": "Diarrhea", "fil": "Pagtatae"}},
    {"name": "vomiting", "type": "boolean", "ai": true, "label": {"en": "Vomiting", "fil": "Pagsusuka"}},
    {"name": "rash", "type": "boolean", "ai": true, "label": {"en": "Rash", "fil": "Pantal"}}
  ]
}
```
Create `forms/bp_followup.json`:
```json
{
  "form_type": "bp_followup",
  "title": {"en": "Blood pressure follow-up", "fil": "Follow-up sa presyon ng dugo"},
  "verification": "pending DOH review",
  "default_follow_up_days": 30,
  "fields": [
    {"name": "bp_systolic", "type": "integer", "min": 50, "max": 260, "required": true, "ai": true,
     "label": {"en": "BP systolic (mmHg)", "fil": "BP systolic (mmHg)"}},
    {"name": "bp_diastolic", "type": "integer", "min": 30, "max": 160, "required": true, "ai": true,
     "label": {"en": "BP diastolic (mmHg)", "fil": "BP diastolic (mmHg)"}},
    {"name": "pulse_bpm", "type": "integer", "min": 30, "max": 220, "ai": true,
     "label": {"en": "Pulse (bpm)", "fil": "Pulso (bpm)"}},
    {"name": "weight_kg", "type": "number", "min": 25, "max": 250, "ai": true,
     "label": {"en": "Weight (kg)", "fil": "Timbang (kg)"}},
    {"name": "on_maintenance_meds", "type": "boolean", "ai": true,
     "label": {"en": "On maintenance medicine", "fil": "May maintenance na gamot"}},
    {"name": "took_meds_today", "type": "boolean", "ai": true,
     "label": {"en": "Took medicine today", "fil": "Nakainom ng gamot ngayon"}},
    {"name": "headache", "type": "boolean", "ai": true, "label": {"en": "Headache", "fil": "Sakit ng ulo"}},
    {"name": "dizziness", "type": "boolean", "ai": true, "label": {"en": "Dizziness", "fil": "Pagkahilo"}},
    {"name": "chest_pain", "type": "boolean", "ai": true, "label": {"en": "Chest pain", "fil": "Sakit ng dibdib"}},
    {"name": "shortness_of_breath", "type": "boolean", "ai": true, "label": {"en": "Shortness of breath", "fil": "Hirap huminga"}},
    {"name": "blurred_vision", "type": "boolean", "ai": true, "label": {"en": "Blurred vision", "fil": "Malabong paningin"}}
  ]
}
```

- [ ] **Step 4: Write `core/forms.py`**

```python
"""Checkup form definitions, loaded from backend/forms/*.json.

The JSON files are the source of truth for each form's fields, types, ranges, labels and
which fields the AI may fill in. They are drafts pending DOH review, so they are data a
health professional can correct without touching code.
"""
import json
from pathlib import Path

from core.config import MIGRATIONS_DIR
from core.extraction import check_value

FORMS_DIR = MIGRATIONS_DIR.parent / "forms"
FIELD_TYPES = {"integer", "number", "boolean", "choice", "choices"}


class FormError(ValueError):
    """A form definition file is malformed."""


def _check_form(form: dict) -> dict:
    names = [field["name"] for field in form["fields"]]
    if len(names) != len(set(names)):
        raise FormError(f"{form['form_type']}: duplicate field names")
    for field in form["fields"]:
        where = f"{form['form_type']}.{field['name']}"
        if field["type"] not in FIELD_TYPES:
            raise FormError(f"{where}: unknown type {field['type']!r}")
        if field["type"] in ("choice", "choices") and not field.get("options"):
            raise FormError(f"{where}: options are required")
        if ("min" in field) != ("max" in field) or ("min" in field and not field["min"] < field["max"]):
            raise FormError(f"{where}: needs both min and max, with min < max")
        if not {"en", "fil"} <= set(field.get("label", {})):
            raise FormError(f"{where}: needs en and fil labels")
    return form


def load_forms(forms_dir: Path = FORMS_DIR) -> dict[str, dict]:
    forms = {}
    for path in sorted(forms_dir.glob("*.json")):
        form = _check_form(json.loads(path.read_text(encoding="utf-8")))
        forms[form["form_type"]] = form
    return forms


FORMS = load_forms()


def list_forms() -> list[dict]:
    return list(FORMS.values())


def get_form(form_type: str) -> dict | None:
    return FORMS.get(form_type)


def extraction_fields(form: dict, ai_only: bool = True) -> dict:
    """The form's fields in core.extraction's shape: name -> (type, extra)."""
    fields = {}
    for field in form["fields"]:
        if ai_only and not field.get("ai"):
            continue
        if field["type"] in ("choice", "choices"):
            extra = tuple(field["options"])
        elif "min" in field:
            extra = (field["min"], field["max"])
        else:
            extra = None
        fields[field["name"]] = (field["type"], extra)
    return fields


def validate_values(form: dict, values: dict, require_complete: bool) -> tuple[dict, list[str]]:
    """Check submitted values against the form. Returns (clean values for every field, problems)."""
    spec = extraction_fields(form, ai_only=False)
    problems = [f"{key}: unknown field" for key in values if key not in spec]
    clean = {}
    for name, (ftype, extra) in spec.items():
        clean[name], problem = check_value(values.get(name), ftype, extra)
        if problem:
            problems.append(f"{name}: {problem}")
    if require_complete:
        invalid = {p.split(":", 1)[0] for p in problems}
        problems += [
            f"{field['name']}: required"
            for field in form["fields"]
            if field.get("required") and clean[field["name"]] is None and field["name"] not in invalid
        ]
    return clean, problems
```

- [ ] **Step 5: Add `--form` to the eval runner**

In `evals/run_eval.py`, add `from core.forms import extraction_fields, get_form` below the core imports. After `load_samples`, add:
```python
def form_settings(form_type: str) -> tuple[dict, str, Path]:
    """Fields, few-shot file and default samples file for a form's eval."""
    form = get_form(form_type)
    if form is None:
        raise SystemExit(f"unknown form: {form_type}")
    samples = HERE / ("samples.jsonl" if form_type == "prenatal" else f"samples_{form_type}.jsonl")
    return extraction_fields(form), f"{form_type}_fewshot.json", samples
```
Change `evaluate` to accept and pass `fewshot_file`:
```python
def evaluate(llm, samples, fields=PRENATAL_FIELDS, fewshot=None, glossary=None, on_sample=None,
             pseudonymize=False, fewshot_file="prenatal_fewshot.json") -> dict:
```
and inside the loop: `out = extract(llm, note, fields, fewshot, glossary, fewshot_file=fewshot_file)`.

In `main()`, change `--samples` to `default=None` and add:
```python
    ap.add_argument("--form", default=None,
                    help="evaluate a form's AI fields (prenatal, child_growth, bp_followup); "
                         "omit for the original 19-field prenatal eval")
```
Then, right after `args = ap.parse_args()`:
```python
    if args.form:
        fields, fewshot_file, default_samples = form_settings(args.form)
    else:
        fields, fewshot_file, default_samples = PRENATAL_FIELDS, "prenatal_fewshot.json", HERE / "samples.jsonl"
    samples = load_samples(args.samples or default_samples)
```
Delete the old `samples = load_samples(args.samples)` line. Change the evaluate call to
`out = evaluate(llm, samples, fields, on_sample=progress, pseudonymize=args.pseudonymize, fewshot_file=fewshot_file)`.
In the MISSES loop, replace `r['got'][f]` with `r['got'].get(f)`.

- [ ] **Step 6: Verify**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_forms -v` → all PASS. Then the full suite → green.

---

### Task 4: Few-shot examples, eval cases, and real-model tuning

**Files:**
- Create: `prompts/child_growth_fewshot.json`, `prompts/bp_followup_fewshot.json`
- Modify: `prompts/prenatal_fewshot.json` (append 2 examples), `prompts/glossary_fil.json` (add missing keys)
- Create: `evals/samples_child_growth.jsonl`, `evals/samples_bp_followup.jsonl`
- Test: `tests/test_forms.py` (append)
- Modify: `LOG.md`

**Interfaces:**
- Consumes: `form_settings`, `get_form`, `validate_values`, `load_samples`

- [ ] **Step 1: Write the failing data-integrity tests**

Append to `tests/test_forms.py`:
```python
from core.extraction import load_json
from evals.run_eval import load_samples


class PromptDataTests(unittest.TestCase):
    def test_fewshots_and_samples_are_valid_and_disjoint(self):
        for form_type in ("prenatal", "child_growth", "bp_followup"):
            with self.subTest(form=form_type):
                form = get_form(form_type)
                _, fewshot_file, samples_path = form_settings(form_type)
                shots = load_json(fewshot_file)
                samples = load_samples(samples_path)
                for shot in shots:
                    self.assertEqual(validate_values(form, shot["fields"], False)[1], [], shot["note"])
                for sample in samples:
                    self.assertEqual(validate_values(form, sample["expected"], False)[1], [], sample["id"])
                self.assertEqual({s["note"] for s in shots} & {s["note"] for s in samples}, set())
                if form_type != "prenatal":
                    self.assertGreaterEqual(len(shots), 8)
                    self.assertEqual(len(samples), 12)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_forms.PromptDataTests -v`
Expected: ERROR `FileNotFoundError` for `child_growth_fewshot.json`.

- [ ] **Step 3: Write the few-shot files**

Create `prompts/child_growth_fewshot.json`:
```json
[
  {"note": "Timbang ni baby 7.5 kilo, haba 68 cm. Binigyan ng Penta 2 at OPV 2 ngayon. Puro gatas ng ina pa rin.",
   "fields": {"weight_kg": 7.5, "length_height_cm": 68, "vaccines_given": ["Penta2", "OPV2"], "breastfeeding": "exclusive"}},
  {"note": "9 months na si bunso, MMR 1 ang bakuna ngayon at binigyan ng Vitamin A. 8.1 kg.",
   "fields": {"vaccines_given": ["MMR1"], "vitamin_a_given": true, "weight_kg": 8.1}},
  {"note": "May lagnat si baby, 38.2 ang temp, inuubo pero walang pagtatae.",
   "fields": {"fever": true, "temperature_c": 38.2, "cough": true, "diarrhea": false}},
  {"note": "Newborn checkup. BCG at Hepa B naibigay. 3.1 kilos.",
   "fields": {"vaccines_given": ["BCG", "HepB"], "weight_kg": 3.1}},
  {"note": "MUAC 12.8 cm, timbang 9.4 kg. Hindi na nagpapasuso, formula na.",
   "fields": {"muac_cm": 12.8, "weight_kg": 9.4, "breastfeeding": "none"}},
  {"note": "Weight 6.2 kg, length 62 cm. Mixed feeding, breastmilk plus formula. Walang sipon o ubo.",
   "fields": {"weight_kg": 6.2, "length_height_cm": 62, "breastfeeding": "partial", "colds": false, "cough": false}},
  {"note": "Dumating para sa checkup lang.",
   "fields": {}},
  {"note": "PCV 3 and IPV given today. No fever, no rash.",
   "fields": {"vaccines_given": ["PCV3", "IPV"], "fever": false, "rash": false}}
]
```
Create `prompts/bp_followup_fewshot.json`:
```json
[
  {"note": "BP niya ngayon 150/95, pulso 88. Umiinom ng maintenance pero hindi nakainom kaninang umaga.",
   "fields": {"bp_systolic": 150, "bp_diastolic": 95, "pulse_bpm": 88, "on_maintenance_meds": true, "took_meds_today": false}},
  {"note": "130 over 85 ang presyon. Walang sakit ng ulo, walang hilo.",
   "fields": {"bp_systolic": 130, "bp_diastolic": 85, "headache": false, "dizziness": false}},
  {"note": "Mang Pedro, 160/100, sumasakit ang ulo at malabo ang paningin.",
   "fields": {"bp_systolic": 160, "bp_diastolic": 100, "headache": true, "blurred_vision": true}},
  {"note": "Weight 72 kg, BP 128/82, nakainom na ng gamot kanina.",
   "fields": {"weight_kg": 72, "bp_systolic": 128, "bp_diastolic": 82, "took_meds_today": true}},
  {"note": "Hindi umiinom ng maintenance. BP 145/92. Kinakapos ng hininga pag naglalakad.",
   "fields": {"on_maintenance_meds": false, "bp_systolic": 145, "bp_diastolic": 92, "shortness_of_breath": true}},
  {"note": "Nag-follow up lang para sa BP check.",
   "fields": {}},
  {"note": "BP 118/76, pulse 72. No chest pain, no dizziness.",
   "fields": {"bp_systolic": 118, "bp_diastolic": 76, "pulse_bpm": 72, "chest_pain": false, "dizziness": false}},
  {"note": "May paninikip ng dibdib kagabi. 170/105 ngayon.",
   "fields": {"chest_pain": true, "bp_systolic": 170, "bp_diastolic": 105}}
]
```
Append these two objects to the array in `prompts/prenatal_fewshot.json` (before the closing `]`, with a comma after the previous last element):
```json
  {"note": "28 weeks, fundal height 27 cm, FHR 140. Binigyan ng Td2 at iron folic acid.",
   "fields": {"weeks_pregnant": 28, "fundal_height_cm": 27, "fetal_heart_rate_bpm": 140, "td_dose": "Td2", "iron_folic_acid_given": true}},
  {"note": "Timbang 58 kg, BP 110/70. Hindi pa nabigyan ng iron.",
   "fields": {"weight_kg": 58, "bp_systolic": 110, "bp_diastolic": 70, "iron_folic_acid_given": false}}
```
In `prompts/glossary_fil.json`, add each of these keys **if no existing key already covers the term** (read the file first; it's a flat JSON object):
```json
  "timbang": "weight",
  "haba / taas (ng bata)": "length / height",
  "bakuna / nabakunahan / naibigay": "vaccine / vaccinated / given",
  "Penta 1, OPV 2, PCV 3, Hepa B, MMR 1": "write vaccines exactly as options: Penta1, OPV2, PCV3, HepB, MMR1",
  "puro gatas ng ina / pinapasuso lang": "breastfeeding = exclusive",
  "may halong formula / mixed feeding": "breastfeeding = partial",
  "hindi na nagpapasuso / formula na / wala nang dede": "breastfeeding = none",
  "pantal": "rash",
  "sipon": "colds",
  "pagtatae / nagtatae": "diarrhea",
  "pulso": "pulse",
  "malabo ang paningin": "blurred vision",
  "kinakapos ng hininga / hirap huminga": "shortness of breath",
  "paninikip / sakit ng dibdib": "chest pain",
  "maintenance / gamot sa altapresyon": "maintenance medicine (on_maintenance_meds)",
  "nakainom na ng gamot": "took_meds_today = true"
```

- [ ] **Step 4: Write the eval cases**

Create `evals/samples_child_growth.jsonl`:
```
// FAKE SCENARIOS NOT REAL

{"id": "c01", "note": "Timbang ni baby ngayon 8.4 kilo, 71 cm ang haba. Nabakunahan ng Penta 3 at PCV 3.", "expected": {"weight_kg": 8.4, "length_height_cm": 71, "vaccines_given": ["Penta3", "PCV3"]}}
{"id": "c02", "note": "Si baby ay 6 weeks old, binigyan ng Penta 1, OPV 1 at PCV 1. Timbang 4.6 kg. Exclusive breastfeeding.", "expected": {"weight_kg": 4.6, "vaccines_given": ["Penta1", "OPV1", "PCV1"], "breastfeeding": "exclusive"}}
{"id": "c03", "note": "May sipon at ubo si bunso pero walang lagnat. 36.9 ang temp.", "expected": {"colds": true, "cough": true, "fever": false, "temperature_c": 36.9}}
{"id": "c04", "note": "Nagtatae po si baby simula kahapon, nagsusuka rin. Timbang 7.0 kg.", "expected": {"diarrhea": true, "vomiting": true, "weight_kg": 7.0}}
{"id": "c05", "note": "MUAC 11.2 cm lang, timbang 6.8 kg, 12 months old. Binigyan ng Vitamin A.", "expected": {"muac_cm": 11.2, "weight_kg": 6.8, "vitamin_a_given": true}}
{"id": "c06", "note": "Weight 10.2 kg, height 80 cm. MMR 2 given. Wala nang dede, kumakain na at formula.", "expected": {"weight_kg": 10.2, "length_height_cm": 80, "vaccines_given": ["MMR2"], "breastfeeding": "none"}}
{"id": "c07", "note": "Bagong panganak, 2.9 kilos. BCG at HepB ibinigay bago umuwi.", "expected": {"weight_kg": 2.9, "vaccines_given": ["BCG", "HepB"]}}
{"id": "c08", "note": "May pantal sa katawan si baby at mainit, 38.5 ang temperatura.", "expected": {"rash": true, "temperature_c": 38.5, "fever": true}}
{"id": "c09", "note": "Pinapasuso pa rin pero may halong formula. 5.9 kg, 63 cm.", "expected": {"breastfeeding": "partial", "weight_kg": 5.9, "length_height_cm": 63}}
{"id": "c10", "note": "Penta 2, OPV 2, PCV 2 today. Walang lagnat after. Weight 5.5 kilos.", "expected": {"vaccines_given": ["Penta2", "OPV2", "PCV2"], "fever": false, "weight_kg": 5.5}}
{"id": "c11", "note": "Follow-up timbang lang, 9.0 kg. Walang ubo, walang sipon.", "expected": {"weight_kg": 9.0, "cough": false, "colds": false}}
{"id": "c12", "note": "IPV at OPV 3 naibigay. Hindi pa nabibigyan ng Vitamin A ngayong buwan.", "expected": {"vaccines_given": ["IPV", "OPV3"], "vitamin_a_given": false}}
```
Create `evals/samples_bp_followup.jsonl`:
```
// FAKE SCENARIOS NOT REAL

{"id": "b01", "note": "BP 142/90 ngayon, pulso 80. Umiinom siya ng amlodipine araw-araw at nakainom na kanina.", "expected": {"bp_systolic": 142, "bp_diastolic": 90, "pulse_bpm": 80, "on_maintenance_meds": true, "took_meds_today": true}}
{"id": "b02", "note": "155 over 98 ang presyon ni Aling Rosa. Nahihilo daw siya kaninang umaga.", "expected": {"bp_systolic": 155, "bp_diastolic": 98, "dizziness": true}}
{"id": "b03", "note": "Walang sakit ng ulo at hindi malabo ang paningin. 126/80.", "expected": {"headache": false, "blurred_vision": false, "bp_systolic": 126, "bp_diastolic": 80}}
{"id": "b04", "note": "Timbang 81 kg, BP 138/88. Nakalimutan uminom ng gamot ngayong araw.", "expected": {"weight_kg": 81, "bp_systolic": 138, "bp_diastolic": 88, "took_meds_today": false}}
{"id": "b05", "note": "180/110 ang BP, masakit ang dibdib at hirap huminga.", "expected": {"bp_systolic": 180, "bp_diastolic": 110, "chest_pain": true, "shortness_of_breath": true}}
{"id": "b06", "note": "Wala siyang maintenance na gamot. Presyon 134/86, pulse 76.", "expected": {"on_maintenance_meds": false, "bp_systolic": 134, "bp_diastolic": 86, "pulse_bpm": 76}}
{"id": "b07", "note": "Blood pressure 120/80. Feels fine, no headache.", "expected": {"bp_systolic": 120, "bp_diastolic": 80, "headache": false}}
{"id": "b08", "note": "Malabo ang paningin at masakit ang ulo, 162/96.", "expected": {"blurred_vision": true, "headache": true, "bp_systolic": 162, "bp_diastolic": 96}}
{"id": "b09", "note": "Pulso 96, BP 148 over 94. Hindi kinakapos ng hininga.", "expected": {"pulse_bpm": 96, "bp_systolic": 148, "bp_diastolic": 94, "shortness_of_breath": false}}
{"id": "b10", "note": "Regular na umiinom ng losartan. 130/84 ngayon, walang hilo.", "expected": {"on_maintenance_meds": true, "bp_systolic": 130, "bp_diastolic": 84, "dizziness": false}}
{"id": "b11", "note": "BP check lang po, 136/88.", "expected": {"bp_systolic": 136, "bp_diastolic": 88}}
{"id": "b12", "note": "Weight 65.5 kg, BP 152/97. Walang chest pain pero nahihilo.", "expected": {"weight_kg": 65.5, "bp_systolic": 152, "bp_diastolic": 97, "chest_pain": false, "dizziness": true}}
```

- [ ] **Step 5: Verify the data tests**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_forms tests.test_extraction -v` → all PASS. Then the full suite → green.

- [ ] **Step 6: Run the real-model evals** (skip if Task 1 ruled the model unavailable)

```bash
.venv/Scripts/python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf --form child_growth --pseudonymize
.venv/Scripts/python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf --form bp_followup --pseudonymize
.venv/Scripts/python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf --form prenatal --pseudonymize
.venv/Scripts/python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf --pseudonymize
```
The last command is the legacy 19-field prenatal eval with the new prompt, compared directly against the Task 1 pseudonymized baseline.
Expected: each prints a SUMMARY and a MISSES list.

- [ ] **Step 7: Tune (at most 3 rounds per form)**

For each target missed (child_growth or bp_followup: `parse_fail` > 0% or `exact` < 75%; prenatal legacy: `exact` below the Task 1 pseudonymized baseline), read the MISSES list. Change **only**:
- the matching few-shot file (add or adjust examples that teach the missed pattern)
- `glossary_fil.json` (add missing terms)
- the option-line wording in `build_messages`

After each change, re-run Step 5 (the data tests must stay green, and no few-shot may copy an eval note) and re-run that form's eval. Stop after the target is met or after 3 rounds.

- [ ] **Step 8: Log results**

Append a `LOG.md` entry:
```markdown

## DD/MM/YY HH:MM
- Added checkup form definitions (prenatal, child_growth, bp_followup; pending DOH review) and option-type extraction (`choice`/`choices`)
- Eval results (Qwen3-4B-Q4_K_M, `--pseudonymize`), after <n> tuning rounds:
  - child_growth (12): fields <x>%, exact <y>%, parse_fail <z>%, avg <s>s
  - bp_followup (12): fields <x>%, exact <y>%, parse_fail <z>%, avg <s>s
  - prenatal form fields (25): fields <x>%, exact <y>%, parse_fail <z>%, avg <s>s
  - prenatal legacy 19 fields (25): exact <y>% (baseline <b>%)
- Remaining misses: <field-level list, or "none">
```

---

### Task 5: AI assist service, model runtime, `/forms`, `/ai/status`, suggestions endpoint

**Files:**
- Create: `core/errors.py`, `core/clock.py`, `core/assist.py`
- Modify: `core/auth.py` (`AuthError` subclasses `ApiError`)
- Modify: `core/inference.py` (`LlamaCppLLM.model_name`)
- Modify: `core/pseudonymize.py` (marker words case-insensitive)
- Create: `migrations/004_visits_follow_ups.sql`
- Create: `routes/forms.py`, `routes/visits.py` (suggestions endpoint only, for now)
- Modify: `api.py` (handlers, model runtime, routers)
- Create: `tests/fakes.py`, `tests/test_assist.py`
- Modify: `tests/api_case.py` (helpers `make_patient`, `use_llm`)
- Modify: `tests/test_pseudonymize.py` (append one test)

**Interfaces:**
- Consumes: `get_form`, `extraction_fields`, `extract(..., fewshot_file=)`, `Pseudonymizer`, `current_user`, `get_db`
- Produces:
  - `core.errors.ApiError(status_code: int, detail)`
  - `core.clock.today() -> date`
  - In `core.assist`:
    - `MODEL_FILE`, `MODEL_LOCK`, `AI_UNAVAILABLE`
    - `AIUnavailable(ApiError)`, which is always 503 with `AI_UNAVAILABLE`
    - `model_file() -> Path`, `load_model() -> LlamaCppLLM`, `get_assist_llm()` (FastAPI dependency), `ai_status() -> dict`
    - `patient_entities(conn, patient_id) -> dict | None`, `mask_note(note, entities) -> str`
    - `suggest(conn, llm, patient_id, form, note, user_id) -> dict | None`
  - `tests.fakes.FakeLLM(reply)` with `.calls` and `.model_name = "fake-model"`
  - `ApiTestCase.make_patient(token, **overrides) -> str` (patient id) and `ApiTestCase.use_llm(llm)`

- [ ] **Step 1: Write the failing tests**

Create `tests/fakes.py`:
```python
"""Test doubles shared by the HTTP tests."""


class FakeLLM:
    """Stands in for the local model: returns a canned reply and records every prompt."""
    model_name = "fake-model"

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def chat_json(self, messages, schema, max_tokens=512):
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(messages) if callable(self.reply) else self.reply
```
Append these methods to `ApiTestCase` in `tests/api_case.py`:
```python
    def make_patient(self, token, full_name="Ana Dela Cruz", barangay="San Roque", sitio="Malinis",
                     contact_number="09171234567"):
        """Register a one-member household and return the member's patient id."""
        response = self.client.post("/api/v1/households", headers=self.bearer(token), json={
            "barangay": barangay, "sitio": sitio, "address_line": "Purok 2",
            "members": [{"full_name": full_name, "sex": "female", "birth_date": "1995-03-14",
                         "contact_number": contact_number, "is_household_head": True}],
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["members"][0]["id"]

    def use_llm(self, llm):
        """Serve `llm` as the AI model for this test."""
        api.app.dependency_overrides[get_assist_llm] = lambda: llm
        self.addCleanup(api.app.dependency_overrides.pop, get_assist_llm, None)
```
and add `from core.assist import get_assist_llm` to its imports.

Create `tests/test_assist.py`:
```python
import json
from unittest import mock

from core import assist
from core import config as api_config
from core.storage import connect
from tests.api_case import ApiTestCase
from tests.fakes import FakeLLM

BP_REPLY = '{"bp_systolic": 150, "bp_diastolic": 95, "dizziness": true}'


class MaskNoteTests(ApiTestCase):
    def test_mask_note_replaces_whole_words_only(self):
        entities = {"full_name": "Ana Dela Cruz", "contact_number": "09171234567", "barangay": "San Roque",
                    "sitio": "Malinis", "address_line": "Purok 2", "household_contact": None}
        masked = assist.mask_note(
            "Si Ana Dela Cruz ng Sitio Malinis, San Roque. Kasama ang Nanay niya. "
            "Masakit ang kanang braso ni Ana. Tel 0917 123 4567. BP 150/95.", entities)
        for secret in ("Ana", "Dela Cruz", "Malinis", "San Roque", "4567"):
            self.assertNotIn(secret, masked)
        for kept in ("Nanay", "kanang braso", "BP 150/95"):
            self.assertIn(kept, masked)


class FormsApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.headers = self.bearer(self.admin_token())

    def test_forms_are_listed_and_fetchable(self):
        forms = self.client.get("/api/v1/forms", headers=self.headers).json()
        self.assertEqual(sorted(f["form_type"] for f in forms), ["bp_followup", "child_growth", "prenatal"])
        one = self.client.get("/api/v1/forms/child_growth", headers=self.headers).json()
        self.assertEqual(one["verification"], "pending DOH review")
        missing = self.client.get("/api/v1/forms/dental", headers=self.headers)
        self.assertEqual((missing.status_code, missing.json()["detail"]), (404, "Form not found"))
        self.assertEqual(self.client.get("/api/v1/forms").status_code, 401)

    def test_ai_status_reflects_the_model_file(self):
        self.assertEqual(self.client.get("/api/v1/ai/status", headers=self.headers).json(),
                         {"available": False, "model": None})
        api_config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        (api_config.MODELS_DIR / assist.MODEL_FILE).write_bytes(b"")
        self.assertEqual(self.client.get("/api/v1/ai/status", headers=self.headers).json(),
                         {"available": True, "model": assist.MODEL_FILE})

    def test_broken_model_file_counts_as_unavailable(self):
        api_config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        (api_config.MODELS_DIR / assist.MODEL_FILE).write_bytes(b"not a model")
        with mock.patch.object(assist, "_model", None), self.assertRaises(assist.AIUnavailable):
            assist.load_model()


class SuggestionApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.token = self.admin_token()
        self.headers = self.bearer(self.token)
        self.patient_id = self.make_patient(self.token)
        self.url = f"/api/v1/patients/{self.patient_id}/suggestions"

    def post(self, note="Si Ana, BP 150/95, nahihilo. San Roque.", form_type="bp_followup", **kwargs):
        return self.client.post(self.url, json={"form_type": form_type, "note": note},
                                headers=kwargs.get("headers", self.headers))

    def test_suggestions_come_back_with_missing_fields(self):
        self.use_llm(FakeLLM(BP_REPLY))
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["values"]["bp_systolic"], 150)
        self.assertIs(body["values"]["dizziness"], True)
        self.assertIn("pulse_bpm", body["missing"])
        self.assertNotIn("bp_systolic", body["missing"])
        self.assertEqual(body["form_type"], "bp_followup")
        self.assertEqual(body["problems"], [])

    def test_model_never_sees_identifying_details(self):
        llm = FakeLLM(BP_REPLY)
        self.use_llm(llm)
        self.post(note="Si Ana Dela Cruz ng Sitio Malinis, San Roque, 09171234567. BP 150/95.")
        sent = llm.calls[0][-1]["content"]
        for secret in ("Ana", "Dela Cruz", "Malinis", "San Roque", "09171234567"):
            self.assertNotIn(secret, sent)
        self.assertIn("150/95", sent)

    def test_audit_row_is_stored_without_the_note(self):
        self.use_llm(FakeLLM(BP_REPLY))
        suggestion_id = self.post(note="BP 150/95, nahihilo").json()["suggestion_id"]
        db = connect()
        try:
            row = dict(db.execute("SELECT * FROM ai_suggestions WHERE id = ?", (suggestion_id,)).fetchone())
        finally:
            db.close()
        self.assertEqual(row["model"], "fake-model")
        self.assertEqual(json.loads(row["values_json"])["bp_systolic"], 150)
        self.assertNotIn("nahihilo", json.dumps(row))

    def test_missing_model_returns_503_with_manual_message(self):
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], assist.AI_UNAVAILABLE)

    def test_generation_failure_returns_503(self):
        self.use_llm(FakeLLM(RuntimeError("llama crashed")))
        self.assertEqual(self.post().status_code, 503)

    def test_unreadable_output_gives_empty_values_and_problems(self):
        self.use_llm(FakeLLM("sorry, I cannot"))
        body = self.post().json()
        self.assertTrue(all(v is None for v in body["values"].values()))
        self.assertEqual(len(body["missing"]), len(body["values"]))
        self.assertTrue(body["problems"])

    def test_bad_requests(self):
        self.use_llm(FakeLLM(BP_REPLY))
        self.assertEqual(self.post(form_type="dental").status_code, 422)
        self.assertEqual(self.post(note="").status_code, 422)
        self.assertEqual(self.post(note="x" * 5001).status_code, 422)
        self.url = "/api/v1/patients/no-such-patient/suggestions"
        self.assertEqual(self.post().status_code, 404)
        self.assertEqual(self.post(headers={}).status_code, 401)
```
Append to `tests/test_pseudonymize.py` (inside its existing test class, keeping its style):
```python
    def test_capitalized_name_marker_at_sentence_start_is_masked(self):
        from core.pseudonymize import Pseudonymizer
        masked = Pseudonymizer().pseudonymize_text("Si Maria ay buntis. Kay Jose ang bahay.")
        self.assertNotIn("Maria", masked)
        self.assertNotIn("Jose", masked)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_assist tests.test_pseudonymize -v`
Expected: ERROR `ModuleNotFoundError: No module named 'core.assist'` (raised from `tests/api_case.py`). The pseudonymize test fails on `"Maria"` still being present.

- [ ] **Step 3: Shared errors and clock**

Create `core/errors.py`:
```python
"""Errors a service function raises for the client to see. api.py renders them as JSON."""


class ApiError(Exception):
    """A failure with the HTTP status to report and a JSON-serializable detail."""

    def __init__(self, status_code: int, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
```
Create `core/clock.py`:
```python
"""The device's local date. Tests patch `today` to pin the calendar."""
from datetime import date


def today() -> date:
    return date.today()
```
In `core/auth.py`, replace the whole `class AuthError` definition with:
```python
class AuthError(ApiError):
    """An authentication or authorization failure."""
```
and add `from core.errors import ApiError` to its imports.

- [ ] **Step 4: Pseudonymizer marker fix**

In `core/pseudonymize.py`, in the name-marker regex (the `re.sub(` call in step 5 of `pseudonymize_text`), change `(si|ni|kay|kina)` to `((?i:si|ni|kay|kina))`. This makes only the marker words case-insensitive; the capitalized-name part stays case-sensitive.

- [ ] **Step 5: Migration**

Create `migrations/004_visits_follow_ups.sql` with exactly the DDL from the spec's "Data model" section (tables `ai_suggestions`, `visits`, `follow_ups` and their three indexes).

- [ ] **Step 6: Model name on the real LLM**

In `core/inference.py`, add `from pathlib import Path` at the top and, in `LlamaCppLLM.__init__`, as its first line: `self.model_name = Path(model_path).name`.

- [ ] **Step 7: Write `core/assist.py`**

```python
"""AI-assisted form entry: mask the note, ask the local model, keep an audit record.

The model only proposes values. Nothing it returns is saved to a visit unless a health
worker submits it (see core/visits.py), and the original note never reaches the model.
"""
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from threading import Lock

from core import config
from core.errors import ApiError
from core.extraction import extract
from core.forms import extraction_fields
from core.pseudonymize import Pseudonymizer

MODEL_FILE = "Qwen3-4B-Q4_K_M.gguf"
AI_UNAVAILABLE = "AI assistant unavailable — please fill in the form manually"
MODEL_LOCK = Lock()  # llama.cpp is not thread-safe: every model call goes through this

_model = None
_load_lock = Lock()


class AIUnavailable(ApiError):
    """The local model is missing, failed to load, or failed while generating."""

    def __init__(self):
        super().__init__(503, AI_UNAVAILABLE)


def model_file() -> Path:
    return config.MODELS_DIR / MODEL_FILE


def load_model():
    """Return the shared model, loading it on first use."""
    global _model
    with _load_lock:
        if _model is None:
            path = model_file()
            if not path.is_file():
                raise AIUnavailable()
            try:
                from core.inference import LlamaCppLLM
                _model = LlamaCppLLM(model_path=str(path))
            except Exception as exc:  # missing llama-cpp, corrupt file, not enough RAM...
                raise AIUnavailable() from exc
        return _model


def get_assist_llm():
    """FastAPI dependency for endpoints that need the real model (no mock fallback)."""
    return load_model()


def ai_status() -> dict:
    path = model_file()
    return {"available": path.is_file(), "model": path.name if path.is_file() else None}


def patient_entities(conn: sqlite3.Connection, patient_id: str) -> dict | None:
    """The identifying details of a patient and their household, for masking."""
    row = conn.execute(
        "SELECT p.full_name, p.contact_number, h.barangay, h.sitio, h.address_line, "
        "h.contact_number AS household_contact "
        "FROM patients p JOIN households h ON h.id = p.household_id WHERE p.id = ?",
        (patient_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def mask_note(note: str, entities: dict) -> str:
    """Replace the patient's known details, then anything the pattern rules find."""
    pseudonymizer = Pseudonymizer()
    name = entities.get("full_name") or ""
    known = [("PATIENT", name), *(("PATIENT", part) for part in name.split() if len(part) >= 3)]
    for phone in (entities.get("contact_number"), entities.get("household_contact")):
        if phone:
            known.append(("PHONE", phone))
            digits = re.sub(r"\D", "", phone)
            if len(digits) >= 7:  # also catch "0917 123 4567" style spacing
                known.append(("PHONE", r"[\s-]?".join(digits)))
    known += [("LOCATION", entities.get(key)) for key in ("barangay", "sitio", "address_line")]
    masked = note
    for kind, value in sorted((k for k in known if k[1] and len(k[1].strip()) >= 2),
                              key=lambda k: len(k[1]), reverse=True):
        is_pattern = kind == "PHONE" and "[" in value
        pattern = value if is_pattern else re.escape(value.strip())
        token = pseudonymizer.get_or_create(kind, value)
        # Whole words only: patient "Ana" must not touch "Nanay" or "kanang".
        masked = re.sub(rf"(?<!\w){pattern}(?!\w)", token, masked, flags=re.IGNORECASE)
    return pseudonymizer.pseudonymize_text(masked)


def suggest(conn: sqlite3.Connection, llm, patient_id: str, form: dict, note: str, user_id: str) -> dict | None:
    """Suggest form values from a note. Returns None if the patient doesn't exist."""
    entities = patient_entities(conn, patient_id)
    if entities is None:
        return None
    fields = extraction_fields(form)
    masked = mask_note(note, entities)
    start = time.monotonic()
    try:
        with MODEL_LOCK:
            result = extract(llm, masked, fields, fewshot_file=f"{form['form_type']}_fewshot.json")
    except Exception as exc:
        raise AIUnavailable() from exc
    duration_ms = int((time.monotonic() - start) * 1000)
    suggestion_id = str(uuid.uuid4())
    with conn:
        conn.execute(
            "INSERT INTO ai_suggestions "
            "(id, patient_id, form_type, values_json, problems_json, model, duration_ms, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (suggestion_id, patient_id, form["form_type"], json.dumps(result["fields"]),
             json.dumps(result["problems"]), getattr(llm, "model_name", type(llm).__name__),
             duration_ms, user_id),
        )
    values = result["fields"]
    return {
        "suggestion_id": suggestion_id,
        "form_type": form["form_type"],
        "values": values,
        "missing": [name for name, value in values.items() if value is None],
        "problems": result["problems"],
    }
```

- [ ] **Step 8: Write `routes/forms.py`**

```python
"""Form definitions and AI availability, so the frontend can render forms from data."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.assist import ai_status
from core.forms import get_form, list_forms

router = APIRouter()


class FormField(BaseModel):
    name: str
    type: Literal["integer", "number", "boolean", "choice", "choices"]
    label: dict[str, str]
    required: bool = False
    ai: bool = False
    min: float | None = None
    max: float | None = None
    options: list[str] | None = None


class FormDefinition(BaseModel):
    form_type: str
    title: dict[str, str]
    verification: str
    default_follow_up_days: int
    fields: list[FormField]


class AIStatus(BaseModel):
    available: bool
    model: str | None


@router.get("/forms", response_model=list[FormDefinition], operation_id="listForms")
def forms():
    return list_forms()


@router.get("/forms/{form_type}", response_model=FormDefinition, operation_id="getForm")
def form_detail(form_type: str):
    form = get_form(form_type)
    if form is None:
        raise HTTPException(status_code=404, detail="Form not found")
    return form


@router.get("/ai/status", response_model=AIStatus, operation_id="getAIStatus")
def status():
    return ai_status()
```

- [ ] **Step 9: Write `routes/visits.py` (suggestions part)**

```python
"""Checkup visits and AI field suggestions for a patient."""
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.assist import get_assist_llm, suggest
from core.auth import AuthContext, current_user
from core.errors import ApiError
from core.forms import get_form
from core.storage import get_db

router = APIRouter()


def _form_or_422(form_type: str) -> dict:
    form = get_form(form_type)
    if form is None:
        raise ApiError(422, ["form_type: unknown form"])
    return form


class SuggestionRequest(BaseModel):
    form_type: str = Field(min_length=1, max_length=40)
    note: str = Field(min_length=1, max_length=5000)


class Suggestion(BaseModel):
    suggestion_id: str
    form_type: str
    values: dict[str, Any]
    missing: list[str]
    problems: list[str]


@router.post("/patients/{patient_id}/suggestions", response_model=Suggestion, operation_id="suggestVisitValues")
def suggest_values(
    patient_id: str,
    data: SuggestionRequest,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
    llm=Depends(get_assist_llm),
):
    result = suggest(db, llm, patient_id, _form_or_422(data.form_type), data.note, auth.user["id"])
    if result is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return result
```

- [ ] **Step 10: Wire `api.py`**

- **Imports.** Replace `from core.auth import AuthError, current_user` with `from core.auth import current_user`. Add `from core.assist import MODEL_LOCK, AIUnavailable, load_model`, `from core.errors import ApiError`, `from routes.forms import router as forms_router` and `from routes.visits import router as visits_router`. Remove `LlamaCppLLM` from the `core.inference` import, leaving `from core.inference import LLM, MockLLM`.
- **Model globals.** Delete the three lines `model_path = config.MODELS_DIR / "Qwen3-4B-Q4_K_M.gguf"`, `llm: LLM | None = None` and `llm_lock = Lock()`, and remove `from threading import Lock` if nothing else uses it.
- **`get_llm`.** Replace the whole function with:
```python
def get_llm() -> LLM:
    """The shared local model for chat, or the mock when it's unavailable."""
    try:
        return load_model()
    except AIUnavailable:
        return MockLLM()
```
- **Chat stream.** In the chat `events()` generator, wrap the streaming loop so model calls are serialized:
```python
        with MODEL_LOCK:
            for piece in get_llm().stream(req.message):
                parts.append(piece)
                yield f"data: {piece}\n\n"
```
- **Error handler.** Rename the `AuthError` handler to handle `ApiError`:
```python
@app.exception_handler(ApiError)
async def api_error_handler(_request, exc: ApiError):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)
```
- **Routers.** Directly after the `users_router` include, add:
```python
app.include_router(forms_router, prefix="/api/v1", dependencies=signed_in, tags=["forms"])
app.include_router(visits_router, prefix="/api/v1", dependencies=signed_in, tags=["visits"])
```

- [ ] **Step 11: Verify**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_assist tests.test_pseudonymize tests.test_auth -v` → all PASS. Then the full suite → green (the chat tests confirm the `get_llm` and lock change).

- [ ] **Step 12: Re-check the prenatal eval after the masking fix** (skip if the model is unavailable)

The marker fix changes how eval notes are masked, so run `.venv/Scripts/python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf --form prenatal --pseudonymize` and the legacy `--pseudonymize` command. Add one line to the Task 4 `LOG.md` entry: `- After the "Si/Kay" masking fix: prenatal exact <y>% (legacy <y2>%)`. If the legacy exact match fell below the baseline, treat it as a missed target, as in Task 4 Step 7 (tuning rounds count toward the same limit of 3).

---

### Task 6: Visits — create, read, timeline, edit and finalize, provenance

**Files:**
- Create: `core/visits.py`
- Modify: `routes/visits.py` (append visit endpoints)
- Modify: `tests/api_case.py` (append `VisitTestCase`)
- Create: `tests/test_visits.py`

**Interfaces:**
- Consumes: `ApiError`, `clock.today`, `get_form`, `validate_values`, `core.records.get_patient`
- Produces:
  - `core.visits.get_visit(conn, visit_id) -> dict | None`. The dict has `values` and `sources` decoded and no `*_json` keys.
  - `core.visits.list_visits(conn, patient_id, form_type, limit, offset) -> dict | None` (page, newest first; None if the patient is missing)
  - `core.visits.create_visit(conn, patient_id, data: dict, user_id) -> dict | None`
  - `core.visits.update_visit(conn, visit_id, changes: dict, user_id) -> dict | None`
  - The returned visit dicts carry `follow_up_created: dict | None`.
  - `core.visits.on_finalize(conn, visit_id, patient_id, form_type, visit_date: date, data, user_id) -> dict | None`, a hook that Task 7 fills in. In this task it only enforces rule 5's draft restriction and returns None.
  - `tests.api_case.VisitTestCase` with `self.token`, `self.headers`, `self.patient_id`, `create_visit(**overrides)`, `patch_visit(visit_id, **changes)`, `suggest(reply, form_type="bp_followup", note=...)`, and `TODAY = date(2026, 10, 10)` pinned through `core.clock.today`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/api_case.py`. Put the three imports with the file's other imports at the top, and `TODAY` below `PASSWORD`.
```python
from datetime import date

from core import clock
from tests.fakes import FakeLLM

TODAY = date(2026, 10, 10)


class VisitTestCase(ApiTestCase):
    """A signed-in admin, one patient, and the calendar pinned to TODAY."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(clock, "today", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.token = self.admin_token()
        self.headers = self.bearer(self.token)
        self.patient_id = self.make_patient(self.token)

    def create_visit(self, patient_id=None, **overrides):
        payload = {"form_type": "bp_followup", "visit_date": "2026-10-10",
                   "values": {"bp_systolic": 150, "bp_diastolic": 95}, **overrides}
        return self.client.post(f"/api/v1/patients/{patient_id or self.patient_id}/visits",
                                json=payload, headers=self.headers)

    def patch_visit(self, visit_id, **changes):
        return self.client.patch(f"/api/v1/visits/{visit_id}", json=changes, headers=self.headers)

    def suggest(self, reply, form_type="bp_followup", note="BP 150/95, nahihilo", patient_id=None):
        self.use_llm(FakeLLM(reply))
        response = self.client.post(f"/api/v1/patients/{patient_id or self.patient_id}/suggestions",
                                    json={"form_type": form_type, "note": note}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()
```
Create `tests/test_visits.py`:
```python
from tests.api_case import VisitTestCase

BP_REPLY = '{"bp_systolic": 150, "bp_diastolic": 95, "dizziness": true}'


class VisitCreateTests(VisitTestCase):
    def test_draft_can_miss_required_fields_but_final_cannot(self):
        draft = self.create_visit(values={"headache": True})
        self.assertEqual(draft.status_code, 201, draft.text)
        self.assertEqual(draft.json()["status"], "draft")
        self.assertIsNone(draft.json()["finalized_at"])
        final = self.create_visit(values={"headache": True}, status="final")
        self.assertEqual(final.status_code, 422)
        self.assertEqual(set(final.json()["detail"]), {"bp_systolic: required", "bp_diastolic: required"})

    def test_final_visit_stores_clean_values_note_and_manual_sources(self):
        response = self.create_visit(status="final", note="BP 150/95 si Ana", values={
            "bp_systolic": 150.0, "bp_diastolic": 95, "headache": False})
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["values"]["bp_systolic"], 150)
        self.assertIsNone(body["values"]["pulse_bpm"])
        self.assertEqual(body["sources"], {"bp_systolic": "manual", "bp_diastolic": "manual", "headache": "manual"})
        self.assertEqual(body["note"], "BP 150/95 si Ana")
        self.assertIsNotNone(body["finalized_at"])
        self.assertIsNone(body["follow_up_created"])

    def test_invalid_values_dates_and_forms_are_rejected(self):
        cases = [
            ({"values": {"bp_systolic": 999}}, "bp_systolic: "),
            ({"values": {"diagnosis": "HTN"}}, "diagnosis: unknown field"),
            ({"values": {"bp_systolic": "150"}}, "bp_systolic: "),
            ({"visit_date": "2026-10-11"}, "visit_date: cannot be in the future"),
            ({"form_type": "dental"}, "form_type: unknown form"),
        ]
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                response = self.create_visit(**overrides)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertTrue(any(p.startswith(expected) for p in response.json()["detail"]))

    def test_unknown_patient_and_missing_token(self):
        self.assertEqual(self.create_visit(patient_id="nope").status_code, 404)
        self.headers = {}
        self.assertEqual(self.create_visit().status_code, 401)


class ProvenanceTests(VisitTestCase):
    def test_accepted_edited_and_manual_sources(self):
        suggestion = self.suggest(BP_REPLY)
        response = self.create_visit(
            status="final",
            suggestion_id=suggestion["suggestion_id"],
            ai_accepted_fields=["bp_systolic", "bp_diastolic", "dizziness"],
            values={"bp_systolic": 150, "bp_diastolic": 90, "dizziness": True, "pulse_bpm": 80},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["sources"], {
            "bp_systolic": "ai_accepted", "bp_diastolic": "ai_edited",
            "dizziness": "ai_accepted", "pulse_bpm": "manual"})
        self.assertEqual(response.json()["suggestion_id"], suggestion["suggestion_id"])

    def test_accepting_a_field_the_ai_left_empty_is_rejected(self):
        suggestion = self.suggest(BP_REPLY)
        response = self.create_visit(suggestion_id=suggestion["suggestion_id"], ai_accepted_fields=["pulse_bpm"],
                                     values={"pulse_bpm": 80})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], ["pulse_bpm: the AI did not suggest a value"])

    def test_suggestion_must_match_patient_and_form(self):
        suggestion = self.suggest(BP_REPLY)
        other_patient = self.make_patient(self.token, full_name="Ben Reyes", contact_number="09181112222")
        wrong_patient = self.create_visit(patient_id=other_patient, suggestion_id=suggestion["suggestion_id"])
        wrong_form = self.create_visit(form_type="prenatal", values={},
                                       suggestion_id=suggestion["suggestion_id"])
        for response in (wrong_patient, wrong_form):
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"], ["suggestion_id: does not match this patient and form"])

    def test_accepted_fields_require_a_suggestion(self):
        response = self.create_visit(ai_accepted_fields=["bp_systolic"])
        self.assertEqual(response.json()["detail"], ["ai_accepted_fields: requires suggestion_id"])


class VisitUpdateTests(VisitTestCase):
    def test_draft_edit_recomputes_sources_and_finalize_locks(self):
        suggestion = self.suggest(BP_REPLY)
        visit = self.create_visit(suggestion_id=suggestion["suggestion_id"],
                                  ai_accepted_fields=["bp_systolic"], values={"bp_systolic": 150}).json()
        edited = self.patch_visit(visit["id"], values={"bp_systolic": 152, "bp_diastolic": 95})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["sources"], {"bp_systolic": "ai_edited", "bp_diastolic": "manual"})
        final = self.patch_visit(visit["id"], status="final")
        self.assertEqual(final.status_code, 200, final.text)
        self.assertEqual(final.json()["status"], "final")

    def test_patch_on_final_visit_is_rejected(self):
        visit = self.create_visit(status="final").json()
        for changes in ({"note": "late edit"}, {"status": "final"}):
            response = self.patch_visit(visit["id"], **changes)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"], "Finalized visits cannot be edited")

    def test_finalizing_validates_required_fields(self):
        visit = self.create_visit(values={"headache": True}).json()
        response = self.patch_visit(visit["id"], status="final")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get(f"/api/v1/visits/{visit['id']}", headers=self.headers).json()["status"],
                         "draft")

    def test_unknown_visit(self):
        self.assertEqual(self.patch_visit("nope", note="x").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/visits/nope", headers=self.headers).status_code, 404)


class TimelineTests(VisitTestCase):
    def test_timeline_is_newest_first_and_filterable(self):
        self.create_visit(visit_date="2026-09-01")
        self.create_visit(visit_date="2026-10-01")
        self.create_visit(form_type="prenatal", visit_date="2026-09-15", values={"weeks_pregnant": 20})
        url = f"/api/v1/patients/{self.patient_id}/visits"
        page = self.client.get(url, headers=self.headers).json()
        self.assertEqual(page["total"], 3)
        self.assertEqual([v["visit_date"] for v in page["items"]], ["2026-10-01", "2026-09-15", "2026-09-01"])
        bp_only = self.client.get(f"{url}?form_type=bp_followup", headers=self.headers).json()
        self.assertEqual(bp_only["total"], 2)
        self.assertEqual(self.client.get("/api/v1/patients/nope/visits", headers=self.headers).status_code, 404)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_visits -v`
Expected: FAILs with 404/405 (no visit routes yet).

- [ ] **Step 3: Write `core/visits.py`**

```python
"""Checkup visits: validated form values, the draft/final lifecycle, and AI provenance."""
import json
import sqlite3
import uuid
from datetime import date

from core import clock
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
    return None  # Task 7 fills this in


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
```

- [ ] **Step 4: Add the visit endpoints**

Append to `routes/visits.py`:
```python
from datetime import date
from typing import Literal

from fastapi import Query, status

from core.visits import create_visit, get_visit, list_visits, update_visit


class FollowUpPlan(BaseModel):
    due_date: date
    reason: str | None = Field(default=None, max_length=500)


class VisitCreate(BaseModel):
    form_type: str = Field(min_length=1, max_length=40)
    visit_date: date
    values: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=5000)
    status: Literal["draft", "final"] = "draft"
    suggestion_id: str | None = None
    ai_accepted_fields: list[str] = Field(default_factory=list, max_length=100)
    follow_up: FollowUpPlan | None = None
    completes_follow_up_id: str | None = None


class VisitUpdate(BaseModel):
    visit_date: date | None = None
    values: dict[str, Any] | None = None
    note: str | None = Field(default=None, max_length=5000)
    status: Literal["draft", "final"] | None = None
    suggestion_id: str | None = None
    ai_accepted_fields: list[str] | None = Field(default=None, max_length=100)
    follow_up: FollowUpPlan | None = None
    completes_follow_up_id: str | None = None


class Visit(BaseModel):
    id: str
    patient_id: str
    form_type: str
    visit_date: str
    status: Literal["draft", "final"]
    values: dict[str, Any]
    sources: dict[str, Literal["manual", "ai_accepted", "ai_edited"]]
    note: str | None
    suggestion_id: str | None
    recorded_by: str
    created_at: str
    updated_at: str
    finalized_at: str | None
    follow_up_created: dict[str, Any] | None = None


class VisitPage(BaseModel):
    items: list[Visit]
    total: int
    limit: int
    offset: int


@router.post("/patients/{patient_id}/visits", response_model=Visit,
             status_code=status.HTTP_201_CREATED, operation_id="createVisit")
def record_visit(
    patient_id: str,
    data: VisitCreate,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    visit = create_visit(db, patient_id, data.model_dump(), auth.user["id"])
    if visit is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return visit


@router.get("/patients/{patient_id}/visits", response_model=VisitPage, operation_id="listPatientVisits")
def patient_visits(
    patient_id: str,
    form_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    page = list_visits(db, patient_id, form_type, limit, offset)
    if page is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return page


@router.get("/visits/{visit_id}", response_model=Visit, operation_id="getVisit")
def visit_detail(visit_id: str, db: sqlite3.Connection = Depends(get_db)):
    visit = get_visit(db, visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    return visit


@router.patch("/visits/{visit_id}", response_model=Visit, operation_id="updateVisit")
def edit_visit(
    visit_id: str,
    data: VisitUpdate,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    visit = update_visit(db, visit_id, data.model_dump(exclude_unset=True), auth.user["id"])
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    return visit
```
Move the new imports to the top of the file with the existing ones (merge `from fastapi import ...` lines; keep a single import block).

- [ ] **Step 5: Verify**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_visits -v` → all PASS. Then the full suite → green.

---

### Task 7: Follow-ups and their link to finalized visits

**Files:**
- Create: `core/follow_ups.py`
- Modify: `core/visits.py` (`on_finalize`)
- Create: `routes/follow_ups.py`
- Modify: `api.py` (include router)
- Create: `tests/test_follow_ups.py`

**Interfaces:**
- Consumes: `VisitTestCase`, `ApiError`, `clock.today`, `get_form`, `core.records.get_patient`, `core.records._search_expression`, `core.visits.get_visit`
- Produces:
  - `core.follow_ups.derive_state(status: str, due_date: str) -> str`
  - `core.follow_ups.get_follow_up(conn, follow_up_id) -> dict | None`
  - `core.follow_ups.insert(conn, patient_id, due_date: date, reason, form_type, user_id, source_visit_id=None) -> str` (no commit)
  - `core.follow_ups.complete_in_tx(conn, follow_up_id, patient_id, visit_id | None) -> None` (no commit)
  - `core.follow_ups.create_follow_up(conn, patient_id, data, user_id) -> dict | None`
  - `core.follow_ups.list_follow_ups(conn, state, patient_id, query, limit, offset) -> dict`
  - `core.follow_ups.update_follow_up(conn, follow_up_id, changes) -> dict | None`
  - `core.follow_ups.complete_follow_up(conn, follow_up_id, visit_id) -> dict | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_follow_ups.py`:
```python
from datetime import date
from unittest import mock

from core import clock
from tests.api_case import VisitTestCase


class FollowUpTestCase(VisitTestCase):
    def schedule(self, due_date, patient_id=None, **extra):
        return self.client.post(f"/api/v1/patients/{patient_id or self.patient_id}/follow-ups",
                                json={"due_date": due_date, **extra}, headers=self.headers)

    def follow_ups(self, query=""):
        return self.client.get(f"/api/v1/follow-ups{query}", headers=self.headers).json()


class FinalizeIntegrationTests(FollowUpTestCase):
    def test_finalizing_with_follow_up_creates_a_linked_one(self):
        response = self.create_visit(status="final", follow_up={"due_date": "2026-11-09", "reason": "BP recheck"})
        self.assertEqual(response.status_code, 201, response.text)
        created = response.json()["follow_up_created"]
        self.assertEqual(created["source_visit_id"], response.json()["id"])
        self.assertEqual((created["form_type"], created["state"], created["reason"]),
                         ("bp_followup", "upcoming", "BP recheck"))
        self.assertEqual(created["patient_name"], "Ana Dela Cruz")

    def test_follow_up_must_come_after_the_visit(self):
        response = self.create_visit(status="final", follow_up={"due_date": "2026-10-10"})
        self.assertEqual(response.json()["detail"], ["follow_up.due_date: must be after visit_date"])
        self.assertEqual(self.client.get(f"/api/v1/patients/{self.patient_id}/visits",
                                         headers=self.headers).json()["total"], 0)  # rolled back

    def test_follow_up_options_are_rejected_on_drafts(self):
        for extra in ({"follow_up": {"due_date": "2026-11-09"}}, {"completes_follow_up_id": "x"}):
            response = self.create_visit(**extra)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"], ["follow_up: only allowed when finalizing"])

    def test_completing_through_a_visit(self):
        follow_up = self.schedule("2026-10-10").json()
        visit = self.create_visit(status="final", completes_follow_up_id=follow_up["id"]).json()
        done = self.client.get(f"/api/v1/follow-ups?state=completed", headers=self.headers).json()["items"][0]
        self.assertEqual((done["id"], done["completed_visit_id"]), (follow_up["id"], visit["id"]))

    def test_completing_twice_is_rejected(self):
        follow_up = self.schedule("2026-10-10").json()
        self.create_visit(status="final", completes_follow_up_id=follow_up["id"])
        again = self.create_visit(status="final", completes_follow_up_id=follow_up["id"])
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["detail"], "Follow-up is not scheduled")

    def test_completing_another_patients_follow_up_is_rejected(self):
        other = self.make_patient(self.token, full_name="Ben Reyes", contact_number="09181112222")
        follow_up = self.schedule("2026-10-10", patient_id=other).json()
        response = self.create_visit(status="final", completes_follow_up_id=follow_up["id"])
        self.assertEqual(response.status_code, 409)

    def test_finalizing_a_draft_by_patch_can_schedule(self):
        visit = self.create_visit().json()
        response = self.patch_visit(visit["id"], status="final", follow_up={"due_date": "2026-11-09"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["follow_up_created"]["source_visit_id"], visit["id"])


class FollowUpStateTests(FollowUpTestCase):
    def test_derived_states(self):
        upcoming = self.schedule("2026-10-20").json()
        due = self.schedule("2026-10-10").json()
        self.assertEqual((upcoming["state"], due["state"]), ("upcoming", "due"))
        db_overdue = self.schedule("2026-10-12").json()
        with mock.patch.object(clock, "today", return_value=date(2026, 10, 15)):
            states = {f["id"]: f["state"] for f in self.follow_ups()["items"]}
        self.assertEqual(states[db_overdue["id"]], "overdue")
        self.assertEqual(states[due["id"]], "overdue")
        self.assertEqual(states[upcoming["id"]], "upcoming")

    def test_list_filters_and_ordering(self):
        ben = self.make_patient(self.token, full_name="Ben Reyes", contact_number="09181112222")
        self.schedule("2026-10-20")
        self.schedule("2026-10-10", patient_id=ben)
        cancelled = self.schedule("2026-10-15").json()
        self.client.patch(f"/api/v1/follow-ups/{cancelled['id']}", json={"status": "cancelled"}, headers=self.headers)
        everything = self.follow_ups()
        self.assertEqual([f["due_date"] for f in everything["items"]], ["2026-10-10", "2026-10-15", "2026-10-20"])
        self.assertEqual(self.follow_ups("?state=due")["total"], 1)
        self.assertEqual(self.follow_ups("?state=cancelled")["total"], 1)
        self.assertEqual(self.follow_ups(f"?patient_id={ben}")["total"], 1)
        self.assertEqual([f["patient_name"] for f in self.follow_ups("?q=reyes")["items"]], ["Ben Reyes"])
        self.assertEqual(self.follow_ups("?q=!!!")["total"], 0)
        self.assertEqual(self.client.get("/api/v1/follow-ups?state=late", headers=self.headers).status_code, 422)


class FollowUpEditTests(FollowUpTestCase):
    def test_standalone_create_validates(self):
        self.assertEqual(self.schedule("2026-10-09").json()["detail"], ["due_date: cannot be in the past"])
        self.assertEqual(self.schedule("2026-10-20", form_type="dental").json()["detail"], ["form_type: unknown form"])
        self.assertEqual(self.schedule("2026-10-20", patient_id="nope").status_code, 404)
        self.headers = {}
        self.assertEqual(self.schedule("2026-10-20").status_code, 401)

    def test_reschedule_cancel_and_lock_after_completion(self):
        follow_up = self.schedule("2026-10-20", reason="weigh baby").json()
        url = f"/api/v1/follow-ups/{follow_up['id']}"
        moved = self.client.patch(url, json={"due_date": "2026-10-25"}, headers=self.headers).json()
        self.assertEqual((moved["due_date"], moved["reason"]), ("2026-10-25", "weigh baby"))
        done = self.client.post(f"{url}/complete", json={}, headers=self.headers)
        self.assertEqual((done.status_code, done.json()["state"]), (200, "completed"))
        locked = self.client.patch(url, json={"status": "cancelled"}, headers=self.headers)
        self.assertEqual((locked.status_code, locked.json()["detail"]), (409, "Only scheduled follow-ups can be changed"))
        self.assertEqual(self.client.patch("/api/v1/follow-ups/nope", json={}, headers=self.headers).status_code, 404)

    def test_complete_with_visit_must_be_same_patients_final_visit(self):
        follow_up = self.schedule("2026-10-20").json()
        draft = self.create_visit().json()
        response = self.client.post(f"/api/v1/follow-ups/{follow_up['id']}/complete",
                                    json={"visit_id": draft["id"]}, headers=self.headers)
        self.assertEqual(response.json()["detail"], ["visit_id: must be a finalized visit of the same patient"])
        final = self.create_visit(status="final").json()
        ok = self.client.post(f"/api/v1/follow-ups/{follow_up['id']}/complete",
                              json={"visit_id": final["id"]}, headers=self.headers)
        self.assertEqual(ok.json()["completed_visit_id"], final["id"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_follow_ups -v`
Expected: FAILs. Follow-up routes return 404, and `follow_up_created` is `None`.

- [ ] **Step 3: Write `core/follow_ups.py`**

```python
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
    total = conn.execute(
        f"SELECT count(*) FROM follow_ups f {where}", params
    ).fetchone()[0]
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
    if changes.get("due_date") is not None:
        _check_due(changes["due_date"])
    fields = {}
    if changes.get("due_date") is not None:
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
```

- [ ] **Step 4: Fill in `on_finalize` in `core/visits.py`**

Add `from core import follow_ups` to the imports, and replace the `on_finalize` body:
```python
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
```
(`complete_in_tx` raises 409 for another patient's follow-up, because the `patient_id` condition makes `rowcount` 0.)

- [ ] **Step 5: Write `routes/follow_ups.py`**

```python
"""Follow-up scheduling and tracking."""
import sqlite3
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from core.auth import AuthContext, current_user
from core.follow_ups import complete_follow_up, create_follow_up, list_follow_ups, update_follow_up
from core.storage import get_db

router = APIRouter()
State = Literal["overdue", "due", "upcoming", "completed", "cancelled"]


class FollowUp(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    barangay: str
    source_visit_id: str | None
    form_type: str | None
    due_date: str
    reason: str | None
    status: Literal["scheduled", "completed", "cancelled"]
    state: State
    completed_visit_id: str | None
    completed_at: str | None
    created_at: str
    updated_at: str


class FollowUpPage(BaseModel):
    items: list[FollowUp]
    total: int
    limit: int
    offset: int


class FollowUpCreate(BaseModel):
    due_date: date
    reason: str | None = Field(default=None, max_length=500)
    form_type: str | None = Field(default=None, max_length=40)


class FollowUpUpdate(BaseModel):
    due_date: date | None = None
    reason: str | None = Field(default=None, max_length=500)
    status: Literal["cancelled"] | None = None


class FollowUpComplete(BaseModel):
    visit_id: str | None = None


def _found(follow_up: dict | None) -> dict:
    if follow_up is None:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    return follow_up


@router.get("/follow-ups", response_model=FollowUpPage, operation_id="listFollowUps")
def follow_ups(
    state: State | None = None,
    patient_id: str | None = None,
    q: str | None = Query(default=None, max_length=120, description="Search patient name"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    return list_follow_ups(db, state, patient_id, q.strip() if q else None, limit, offset)


@router.post("/patients/{patient_id}/follow-ups", response_model=FollowUp,
             status_code=status.HTTP_201_CREATED, operation_id="createFollowUp")
def schedule_follow_up(
    patient_id: str,
    data: FollowUpCreate,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    follow_up = create_follow_up(db, patient_id, data.model_dump(), auth.user["id"])
    if follow_up is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return follow_up


@router.patch("/follow-ups/{follow_up_id}", response_model=FollowUp, operation_id="updateFollowUp")
def change_follow_up(follow_up_id: str, data: FollowUpUpdate, db: sqlite3.Connection = Depends(get_db)):
    return _found(update_follow_up(db, follow_up_id, data.model_dump(exclude_unset=True)))


@router.post("/follow-ups/{follow_up_id}/complete", response_model=FollowUp, operation_id="completeFollowUp")
def finish_follow_up(follow_up_id: str, data: FollowUpComplete, db: sqlite3.Connection = Depends(get_db)):
    return _found(complete_follow_up(db, follow_up_id, data.visit_id))
```

- [ ] **Step 6: Mount it**

In `api.py`, add `from routes.follow_ups import router as follow_ups_router` with the other router imports. After the `visits_router` include, add:
```python
app.include_router(follow_ups_router, prefix="/api/v1", dependencies=signed_in, tags=["follow-ups"])
```

- [ ] **Step 7: Verify**

Run: `.venv/Scripts/python -W ignore -m unittest tests.test_follow_ups tests.test_visits -v` → all PASS. Then the full suite → green.

---

### Task 8: Docs and final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the API**

In `README.md`'s "Frontend API" section, insert this directly above the paragraph that begins `Use this same resource-oriented, versioned contract`:
````markdown
Checkup forms, AI-assisted entry, visits and follow-ups:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/forms` / `/api/v1/forms/{form_type}` | Form definitions (`prenatal`, `child_growth`, `bp_followup`): fields, types, ranges, en/fil labels, required and AI flags. Drafts pending DOH review, defined in `backend/forms/*.json` |
| `GET` | `/api/v1/ai/status` | `{ available, model }`: whether the local model file is present |
| `POST` | `/api/v1/patients/{id}/suggestions` | `{ form_type, note }` → `{ suggestion_id, values, missing, problems }`. The note is pseudonymized before it reaches the model. `503` means fill the form manually |
| `POST` | `/api/v1/patients/{id}/visits` | Record a visit: `{ form_type, visit_date, values, note, status: draft\|final, suggestion_id, ai_accepted_fields, follow_up: { due_date, reason }, completes_follow_up_id }` |
| `GET` | `/api/v1/patients/{id}/visits?form_type=` | Visit timeline, newest first |
| `GET` / `PATCH` | `/api/v1/visits/{id}` | Get a visit; edit or finalize a draft (final visits are read-only) |
| `GET` | `/api/v1/follow-ups?state=overdue\|due\|upcoming\|completed\|cancelled&patient_id=&q=` | Follow-up list, by due date |
| `POST` | `/api/v1/patients/{id}/follow-ups` | Schedule a follow-up |
| `PATCH` | `/api/v1/follow-ups/{id}` | Reschedule or cancel |
| `POST` | `/api/v1/follow-ups/{id}/complete` | Mark completed, optionally with `{ visit_id }` |

AI suggestions are never saved on their own. The client submits the values the worker
confirmed plus `ai_accepted_fields`, and each saved field records its source:
`manual`, `ai_accepted` or `ai_edited`. Validation errors on visit values come back as
`422 { "detail": ["<field>: <problem>", ...] }`.

````
In the "Running Evaluations & Tests" section, replace the eval code block with:
````markdown
```bash
python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf                                   # original 19-field prenatal eval
python -m evals.run_eval Qwen3-4B-Q4_K_M.gguf --form child_growth --pseudonymize  # a form's AI fields, masked notes
```
````
In "Project Layout", add these lines under `backend/`:
```
  forms/                  Checkup form definitions (JSON, pending DOH review)
  core/forms.py           Form loading and value validation
  core/assist.py          Shared local model, note masking, AI suggestions
  core/visits.py          Visits: draft/final lifecycle and AI provenance
  core/follow_ups.py      Follow-up scheduling and due/overdue state
```

- [ ] **Step 2: Full suite**

Run: `.venv/Scripts/python -W ignore -m unittest discover -s tests`
Expected: OK. The total is 81 plus all new tests.

- [ ] **Step 3: Live smoke test**

Start `.venv/Scripts/python run.py --port 8799` with `APP_DATA_DIR` pointed at a temp folder. With curl:
1. Sign up and log in.
2. Create a household with one member.
3. `GET /api/v1/ai/status` → `available: false` (the temp folder has no model).
4. Request a suggestion for that member → 503 with the manual message.
5. Create a final `bp_followup` visit with a `follow_up` → 201 and a non-null `follow_up_created`.
6. `GET /api/v1/follow-ups?state=upcoming` → `total: 1`.

Stop the server and delete the temp folder.

- [ ] **Step 4: Real model end to end** (skip if unavailable)

Don't touch the real app database. Write a throwaway script in the session scratchpad that:
1. sets `core.config.DATA_DIR` and `core.config.DB_PATH` to a temp folder, leaving `MODELS_DIR` pointing at the real models folder
2. runs `migrate(connect())`
3. creates a user with `core.auth.signup` and a household with `core.records.create_household`
4. calls `core.assist.suggest(conn, core.assist.load_model(), patient_id, get_form("child_growth"), "Timbang 8.2 kilo ni baby, binigyan ng Penta 2 at OPV 2.", user_id)`

Expected: `values` holds `weight_kg` 8.2 and `vaccines_given` containing Penta2 and OPV2. Delete the temp folder.
