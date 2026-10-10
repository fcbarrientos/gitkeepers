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
