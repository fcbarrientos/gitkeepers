"""Offline-first Pseudonymization Engine for Rural Healthcare Records.

Protects Patient Personally Identifiable Information (PII) and Protected Health
Information (PHI) before records leave the local device during RHU/Hospital sync or exports.
"""
import hashlib
import hmac
import re
from typing import Any


class Pseudonymizer:
    """Manages reversible pseudonymization with a local mapping vault."""

    def __init__(self, salt: str = "gitkeepers-rural-health-salt"):
        self.salt = salt.encode("utf-8")
        # vault maps { pseudonym: original_value }
        self.vault: dict[str, str] = {}
        # reverse cache { (entity_type, original_clean): pseudonym }
        self._cache: dict[tuple[str, str], str] = {}

    def get_or_create(self, entity_type: str, raw_value: str) -> str:
        """Generate or retrieve a deterministic pseudonym for a given entity."""
        if not raw_value or not raw_value.strip():
            return raw_value
        clean = raw_value.strip()
        # Free text is restored verbatim, so its case is part of its identity.
        folded = clean if entity_type.upper() == "TEXT" else clean.lower()
        cache_key = (entity_type.upper(), folded)
        if cache_key in self._cache:
            return self._cache[cache_key]

        digest = hmac.new(self.salt, f"{entity_type}:{folded}".encode("utf-8"), hashlib.sha256).hexdigest()
        short_id = digest[:8].upper()
        prefix = {
            "PATIENT": "PSN-PAT",
            "NAME": "PSN-NAME",
            "HOUSEHOLD": "PSN-HH",
            "PHONE": "PSN-PHONE",
            "PHILHEALTH": "PSN-PHIC",
            "LOCATION": "PSN-LOC",
            "DATE": "PSN-DATE",
        }.get(entity_type.upper(), f"PSN-{entity_type.upper()[:4]}")

        pseudonym = f"{prefix}-{short_id}"
        self.vault[pseudonym] = clean
        self._cache[cache_key] = pseudonym
        return pseudonym

    def pseudonymize_text(self, text: str, known_entities: dict[str, str] | None = None) -> str:
        """Detect and replace PII in unstructured Taglish/Filipino clinical notes."""
        if not text:
            return text

        result = text

        # 1. Replace explicitly known entities first (longest first to avoid substrings)
        if known_entities:
            sorted_known = sorted(known_entities.items(), key=lambda item: len(item[1]), reverse=True)
            for entity_type, raw_val in sorted_known:
                if raw_val and len(raw_val.strip()) >= 2:
                    psn = self.get_or_create(entity_type, raw_val)
                    # Case-insensitive whole word / phrase replacement
                    pattern = re.compile(re.escape(raw_val.strip()), re.IGNORECASE)
                    result = pattern.sub(psn, result)

        # 2. PhilHealth numbers: e.g. 12-345678901-2
        def phic_repl(match: re.Match) -> str:
            val = match.group(0)
            return self.get_or_create("PHILHEALTH", val)

        result = re.sub(r"\b\d{2}-\d{9}-\d{1}\b", phic_repl, result)

        # 3. Philippine Phone numbers (+639..., 09...)
        def phone_repl(match: re.Match) -> str:
            val = match.group(0)
            return self.get_or_create("PHONE", val)

        result = re.sub(r"(?:\+63\s?9\d{2}[\s-]?\d{3}[\s-]?\d{4}|09\d{2}[\s-]?\d{3}[\s-]?\d{4}|\b09\d{9}\b)",
                        phone_repl, result)

        # 4. Philippine Address patterns (Brgy., Sitio, Purok)
        def loc_repl(match: re.Match) -> str:
            val = match.group(0)
            return self.get_or_create("LOCATION", val)

        result = re.sub(r"\b(?:Brgy\.|Barangay|Sitio|Purok)\s+[A-Za-z0-9\s.-]+?(?=[,.\n;]|\s+(?:noong|nung|kanina|kahapon|mula|sa|at|pero)\b|$)",
                        loc_repl, result, flags=re.IGNORECASE)

        # 5. Combined Filipino Name Markers & Honorifics: (si/ni/kay/kina) and/or (Nanay/Tatay/Aling/Mang/Ate/Kuya/Dra./Dr.) + Name
        def name_repl(match: re.Match) -> str:
            marker = match.group(1) or ""
            honorific = match.group(2) or match.group(3) or ""
            name = match.group(4).strip()

            if name.startswith("PSN-") or name.lower() in {
                "doktor", "midwife", "bhw", "lunes", "martes", "miyerkules", "huwebes", "biyernes", "sabado", "linggo",
                "nanay", "tatay", "aling", "mang", "ate", "kuya", "baby", "buntis", "pasyente", "patient"
            }:
                return match.group(0)

            psn = self.get_or_create("NAME", name)
            parts = [p for p in (marker, honorific, psn) if p]
            return " ".join(parts)

        result = re.sub(
            r"\b(?:(si|ni|kay|kina)\s+(?:(Nanay|Tatay|Aling|Mang|Ate|Kuya|Dra\.|Dr\.)\s+)?|(Nanay|Tatay|Aling|Mang|Ate|Kuya|Dra\.|Dr\.)\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b",
            name_repl,
            result,
        )

        return result

    def pseudonymize_record(self, record: Any) -> Any:
        """Recursively pseudonymize structured records, dicts, or lists."""
        if isinstance(record, dict):
            new_rec = {}
            # Extract known contextual names in this record if present
            known_in_rec = {}
            if "patient_name" in record and record["patient_name"]:
                known_in_rec["PATIENT"] = str(record["patient_name"])
            if "household_head" in record and record["household_head"]:
                known_in_rec["NAME"] = str(record["household_head"])

            for k, v in record.items():
                if k in {"patient_name", "full_name", "first_name", "last_name", "name", "mother_name", "guardian"}:
                    new_rec[k] = self.get_or_create("PATIENT", str(v)) if v else v
                elif k in {"household_head", "contact_person"}:
                    new_rec[k] = self.get_or_create("NAME", str(v)) if v else v
                elif k in {"contact_number", "phone", "mobile", "contact_no"}:
                    new_rec[k] = self.get_or_create("PHONE", str(v)) if v else v
                elif k in {"philhealth_no", "philhealth_id", "phic_pin", "phic"}:
                    new_rec[k] = self.get_or_create("PHILHEALTH", str(v)) if v else v
                elif k in {"address", "sitio", "purok", "barangay", "street"}:
                    new_rec[k] = self.get_or_create("LOCATION", str(v)) if v else v
                elif k in {"note", "notes", "clinical_note", "history", "chief_complaint", "summary"}:
                    new_rec[k] = self.pseudonymize_text(str(v), known_entities=known_in_rec) if v else v
                elif isinstance(v, (dict, list)):
                    new_rec[k] = self.pseudonymize_record(v)
                else:
                    new_rec[k] = v
            return new_rec
        elif isinstance(record, list):
            return [self.pseudonymize_record(item) for item in record]
        return record

    def depseudonymize_text(self, text: str, vault: dict[str, str] | None = None) -> str:
        """Restore original PII from pseudonyms in text using the vault."""
        if not text:
            return text
        v = self.vault if vault is None else vault
        result = text
        for psn, original in v.items():
            result = result.replace(psn, original)
        return result

    def depseudonymize_record(self, record: Any, vault: dict[str, str] | None = None) -> Any:
        """Recursively restore original identities in structured records."""
        v = self.vault if vault is None else vault
        if isinstance(record, dict):
            return {k: self.depseudonymize_record(val, v) for k, val in record.items()}
        elif isinstance(record, list):
            return [self.depseudonymize_record(item, v) for item in record]
        elif isinstance(record, str):
            return self.depseudonymize_text(record, v)
        return record
