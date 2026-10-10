import json
import tempfile
import unittest
from pathlib import Path

from core.extraction import PRENATAL_FIELDS, load_json
from core.forms import FormError, extraction_fields, get_form, list_forms, load_forms, validate_values
from evals.run_eval import form_settings, load_samples


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
