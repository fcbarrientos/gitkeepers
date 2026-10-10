"""Dashboard counts and the cross-patient visit list."""
from datetime import date
from unittest import mock

from core import clock
from tests.api_case import VisitTestCase


class DashboardTests(VisitTestCase):
    def schedule(self, due_date):
        response = self.client.post(f"/api/v1/patients/{self.patient_id}/follow-ups",
                                    json={"due_date": due_date}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)

    def dashboard(self):
        response = self.client.get("/api/v1/dashboard", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_follow_up_counts_match_the_follow_up_lists(self):
        with mock.patch.object(clock, "today", return_value=date(2026, 10, 1)):
            self.schedule("2026-10-05")  # overdue by TODAY
        self.schedule("2026-10-10")
        self.schedule("2026-10-20")
        self.schedule("2026-10-21")
        counts = self.dashboard()["follow_ups"]
        self.assertEqual(counts, {"overdue": 1, "due": 1, "upcoming": 2})
        for state, count in counts.items():
            listed = self.client.get(f"/api/v1/follow-ups?state={state}", headers=self.headers).json()
            self.assertEqual(listed["total"], count, state)

    def test_visit_record_and_ai_counts(self):
        self.assertEqual(self.create_visit().status_code, 201)  # a draft dated today
        self.assertEqual(self.create_visit(visit_date="2026-10-01", status="final").status_code, 201)
        self.make_patient(self.token, full_name="Berto Santos", contact_number="09179999999")
        summary = self.dashboard()
        self.assertEqual((summary["visits_today"], summary["drafts"]), (1, 1))
        self.assertEqual((summary["households"], summary["patients"]), (2, 2))
        self.assertEqual(summary["ai"], {"available": False, "model": None})

    def test_requires_sign_in(self):
        self.assertEqual(self.client.get("/api/v1/dashboard").status_code, 401)

    def test_referral_supply_and_sync_counts(self):
        self.create_visit(status="final", values={"bp_systolic": 190, "bp_diastolic": 100})
        item = self.client.post("/api/v1/supplies", json={"name": "ORS", "unit": "sachets",
                                                          "low_stock_threshold": 10, "target_level": 50},
                                headers=self.headers).json()
        self.assertTrue(item["low"])
        summary = self.dashboard()
        self.assertEqual((summary["referral_flags_open"], summary["low_stock"]), (1, 1))
        self.assertGreater(summary["unsynced"], 0)


class VisitListTests(VisitTestCase):
    def test_lists_visits_across_patients_newest_first_with_names(self):
        other = self.make_patient(self.token, full_name="Berto Santos", contact_number="09179999999")
        older = self.create_visit(visit_date="2026-10-01", status="final").json()
        newer = self.create_visit(patient_id=other).json()
        page = self.client.get("/api/v1/visits", headers=self.headers).json()
        self.assertEqual([v["id"] for v in page["items"]], [newer["id"], older["id"]])
        self.assertEqual([v["patient_name"] for v in page["items"]], ["Berto Santos", "Ana Dela Cruz"])
        self.assertEqual(page["total"], 2)

    def test_filters_by_date_and_status(self):
        self.create_visit(visit_date="2026-10-01", status="final")
        draft = self.create_visit().json()
        by_date = self.client.get("/api/v1/visits?date=2026-10-10", headers=self.headers).json()
        self.assertEqual([v["id"] for v in by_date["items"]], [draft["id"]])
        finals = self.client.get("/api/v1/visits?status=final", headers=self.headers).json()
        self.assertEqual(finals["total"], 1)
        self.assertEqual(finals["items"][0]["status"], "final")

    def test_limit_is_capped_and_sign_in_required(self):
        self.assertEqual(self.client.get("/api/v1/visits?limit=101", headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/visits").status_code, 401)
