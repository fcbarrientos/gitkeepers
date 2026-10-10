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
