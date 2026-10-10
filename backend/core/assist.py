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
