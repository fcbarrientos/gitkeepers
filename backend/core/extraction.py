"""Turn a typed/dictated visit note (Filipino, Taglish or English) into form-field SUGGESTIONS.

The model only proposes values. A health worker confirms every field, and danger-sign
decisions are made by the rules engine, never here.
"""
import json
import re
from pathlib import Path

from core.config import MIGRATIONS_DIR

PROMPTS_DIR = MIGRATIONS_DIR.parent / "prompts"

# field -> (json type, extra). extra is the (min, max) sanity range for numbers, None for
# booleans, or the tuple of allowed options for "choice"/"choices".
# null always means "the note does not mention this".
PRENATAL_FIELDS = {
    "weeks_pregnant": ("integer", (1, 45)),
    "bp_systolic": ("integer", (50, 260)),
    "bp_diastolic": ("integer", (30, 160)),
    "temperature_c": ("number", (30.0, 45.0)),
    "fever": ("boolean", None),
    "bleeding": ("boolean", None),
    "headache": ("boolean", None),
    "dizziness": ("boolean", None),
    "baby_moving": ("boolean", None),
    "vomiting": ("boolean", None),
    "cough": ("boolean", None),
    "colds": ("boolean", None),
    "sore_throat": ("boolean", None),
    "shortness_of_breath": ("boolean", None),
    "chest_pain": ("boolean", None),
    "abdominal_pain": ("boolean", None),
    "diarrhea": ("boolean", None),
    "rash": ("boolean", None),
    "body_pain": ("boolean", None),
}


def load_json(name: str):
    return json.loads((PROMPTS_DIR / name).read_text(encoding="utf-8"))


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


def build_messages(note: str, fields: dict = PRENATAL_FIELDS, fewshot=None, glossary=None,
                   fewshot_file: str = "prenatal_fewshot.json") -> list:
    fewshot = load_json(fewshot_file) if fewshot is None else fewshot
    glossary = load_json("glossary_fil.json") if glossary is None else glossary
    gloss = "\n".join(f"- {k} = {v}" for k, v in glossary.items())
    options = "".join(
        f"- {name}: one of {list(extra)}\n" if ftype == "choice" else f"- {name}: list of any of {list(extra)}\n"
        for name, (ftype, extra) in fields.items()
        if ftype in ("choice", "choices")
    )
    if options:
        options = "Fields with fixed options (copy the spelling exactly):\n" + options
    system = (
        "You extract structured clinical data from a health worker's visit note. "
        "The note may be in Filipino, Taglish or English.\n"
        f"Available fields: {', '.join(fields)}.\n"
        "Rules:\n"
        "- DO NOT include fields that are not mentioned in the note. Only return keys that are directly stated.\n"
        "- For yes/no symptoms: set to true ONLY if explicitly reported as present. Set to false ONLY if explicitly denied/absent (e.g. 'walang lagnat', 'no bleeding'). If a symptom is NOT mentioned at all, DO NOT set it to false—simply omit it.\n"
        "- Gestational age like '28 weeks' or '30 linggo' -> weeks_pregnant (as integer digits).\n"
        "- Blood pressure like '140/90' or '140 over 90' -> bp_systolic: 140, bp_diastolic: 90.\n"
        "- Temperature like '38.5 temp' or '37.8 C' -> temperature_c: 38.5 (and fever: true if >= 37.8).\n"
        f"{options}"
        f"Glossary (Filipino to English):\n{gloss}\n"
        "Output ONLY a valid compact JSON object."
    )
    messages = [{"role": "system", "content": system}]
    for ex in fewshot:
        # Schema order: the JSON grammar rejects keys out of order, so teach the model that order.
        answer = {k: ex["fields"][k] for k in fields if ex["fields"].get(k) is not None}
        messages.append({"role": "user", "content": f"{ex['note']} /no_think"})
        messages.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    messages.append({"role": "user", "content": f"{note} /no_think"})
    return messages


def strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


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


def parse_and_validate(raw: str, fields: dict = PRENATAL_FIELDS) -> dict:
    """Never raises. Returns {ok, fields, problems, raw}; bad values become None."""
    empty = {k: None for k in fields}
    text = strip_think(raw or "")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        try:
            obj = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            obj = None
    if not isinstance(obj, dict):
        return {"ok": False, "fields": empty, "problems": ["output was not a JSON object"], "raw": raw}
    clean, problems = {}, []
    for key, (ftype, rng) in fields.items():
        val, problem = _check(obj.get(key), ftype, rng)
        clean[key] = val
        if problem:
            problems.append(f"{key}: {problem}")
    for key in obj:
        if key not in fields:
            problems.append(f"{key}: unknown field ignored")
    return {"ok": True, "fields": clean, "problems": problems, "raw": raw}


def extract(llm, note: str, fields: dict = PRENATAL_FIELDS, fewshot=None, glossary=None,
            max_tokens: int = 512, fewshot_file: str = "prenatal_fewshot.json") -> dict:
    """llm must provide chat_json(messages, schema, max_tokens) -> str."""
    messages = build_messages(note, fields, fewshot, glossary, fewshot_file)
    raw = llm.chat_json(messages, schema_for(fields), max_tokens)
    return parse_and_validate(raw, fields)
