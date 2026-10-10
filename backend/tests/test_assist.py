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
