"""Weekly/monthly summaries and AI-assisted program-needs drafts."""
from datetime import date

from core.reports import period_bounds
from core.storage import connect
from tests.api_case import VisitTestCase
from tests.fakes import FakeLLM


class PeriodTests(VisitTestCase):
    def test_week_runs_monday_to_sunday_and_month_covers_the_calendar_month(self):
        self.assertEqual(period_bounds("week", date(2026, 10, 10)), (date(2026, 10, 5), date(2026, 10, 11)))
        self.assertEqual(period_bounds("month", date(2026, 2, 14)), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(period_bounds("month", date(2026, 12, 31)), (date(2026, 12, 1), date(2026, 12, 31)))


class SummaryTests(VisitTestCase):
    def summary(self, query="?period=week&date=2026-10-10"):
        response = self.client.get(f"/api/v1/reports/summary{query}", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_counts_current_and_previous_period(self):
        self.create_visit(status="final", values={"bp_systolic": 190, "bp_diastolic": 100})  # 2026-10-10
        self.create_visit(visit_date="2026-10-01", status="final")  # previous week
        self.client.post("/api/v1/referrals", json={"patient_id": self.patient_id, "facility": "RHU",
                                                    "reason": "Very high BP", "urgency": "urgent"}, headers=self.headers)
        item = self.client.post("/api/v1/supplies", json={"name": "ORS", "unit": "sachets",
                                                          "low_stock_threshold": 10, "target_level": 50},
                                headers=self.headers).json()
        self.client.post(f"/api/v1/supplies/{item['id']}/movements", json={
            "kind": "received", "quantity": 20, "movement_date": "2026-10-06"}, headers=self.headers)
        self.client.post(f"/api/v1/supplies/{item['id']}/movements", json={
            "kind": "distributed", "quantity": 15, "movement_date": "2026-10-07"}, headers=self.headers)
        report = self.summary()
        current, previous = report["current"], report["previous"]
        self.assertEqual((current["start"], current["end"]), ("2026-10-05", "2026-10-11"))
        self.assertEqual((current["visits"]["total"], previous["visits"]["total"]), (1, 1))
        self.assertEqual(current["visits"]["by_form"], {"bp_followup": 1})
        self.assertEqual((current["referral_flags"], current["referrals_issued"]), (1, 1))
        self.assertEqual(current["referrals_by_reason"], {"manual": 1})  # no flag: grouped as manual
        self.assertEqual(current["supplies"], [{"name": "ORS", "unit": "sachets", "received": 20, "distributed": 15}])
        self.assertEqual(current["low_stock_items"], ["ORS"])
        self.assertEqual(previous["low_stock_items"], ["ORS"])  # nothing had arrived yet
        self.assertGreater(report["unsynced_records"], 0)

    def test_month_period_and_default_date(self):
        self.create_visit(visit_date="2026-10-01", status="final")
        self.assertEqual(self.summary("?period=month&date=2026-10-20")["current"]["visits"]["total"], 1)
        self.assertEqual(self.summary("?period=month")["current"]["start"], "2026-10-01")
        bad = self.client.get("/api/v1/reports/summary?period=year", headers=self.headers)
        self.assertEqual(bad.status_code, 422)


class DraftTests(VisitTestCase):
    def ai_draft(self, llm):
        self.use_llm(llm)
        return self.client.post("/api/v1/reports/drafts", json={"period": "week", "date": "2026-10-10"},
                                headers=self.headers)

    def test_ai_draft_sees_only_totals(self):
        self.create_visit(status="final", note="Ana Dela Cruz said she is dizzy")
        llm = FakeLLM("<think>hmm</think>Consider a BP screening day.")
        response = self.ai_draft(llm)
        self.assertEqual(response.status_code, 201, response.text)
        draft = response.json()
        self.assertEqual((draft["text"], draft["status"], draft["model"]), ("Consider a BP screening day.", "draft", "fake-model"))
        prompt = llm.calls[0]
        self.assertIn('"total": 1', prompt)
        for secret in ("Ana", "dizzy", self.patient_id):
            self.assertNotIn(secret, prompt)

    def test_ai_failures_are_503(self):
        for llm in (FakeLLM(RuntimeError("boom")), FakeLLM("   ")):
            self.assertEqual(self.ai_draft(llm).status_code, 503)
        app_without_model = self.client.post("/api/v1/reports/drafts", json={"period": "week", "date": "2026-10-10"},
                                              headers=self.headers)
        self.assertEqual(app_without_model.status_code, 503)

    def test_manual_draft_edit_and_approve(self):
        response = self.client.post("/api/v1/reports/drafts/manual", json={
            "period": "month", "date": "2026-10-10", "text": "More prenatal visits needed."}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        draft = response.json()
        self.assertIsNone(draft["model"])
        patch = lambda **body: self.client.patch(f"/api/v1/reports/drafts/{draft['id']}", json=body, headers=self.headers)
        self.assertEqual(patch(text="  ").json()["detail"], ["text: cannot be empty"])
        approved = patch(text="Edited.", status="approved").json()
        self.assertEqual((approved["text"], approved["status"]), ("Edited.", "approved"))
        self.assertEqual(patch(text="again").status_code, 409)
        listed = self.client.get("/api/v1/reports/drafts?period=month&date=2026-10-31", headers=self.headers).json()
        self.assertEqual([d["id"] for d in listed], [draft["id"]])
        empty = self.client.post("/api/v1/reports/drafts/manual", json={
            "period": "month", "date": "2026-10-10", "text": " "}, headers=self.headers)
        self.assertEqual(empty.json()["detail"], ["text: write the summary first"])


class ReportCorrectnessTests(VisitTestCase):
    def summary(self, query="?period=week&date=2026-10-10"):
        return self.client.get(f"/api/v1/reports/summary{query}", headers=self.headers).json()

    def test_referrals_group_by_rule_never_by_free_text(self):
        self.create_visit(status="final", values={"bp_systolic": 190, "bp_diastolic": 100})
        flag = self.client.get("/api/v1/referral-flags", headers=self.headers).json()[0]
        self.client.post("/api/v1/referrals", json={"patient_id": self.patient_id, "flag_id": flag["id"],
                                                    "facility": "RHU", "reason": "Ana Dela Cruz BP 190/120"},
                         headers=self.headers)
        self.client.post("/api/v1/referrals", json={"patient_id": self.patient_id, "facility": "RHU",
                                                    "reason": "Ana asked to see a doctor"}, headers=self.headers)
        by_reason = self.summary()["current"]["referrals_by_reason"]
        self.assertEqual(by_reason, {"Very high blood pressure (180/110 or higher)": 1, "manual": 1})
        llm = FakeLLM("Draft.")
        self.use_llm(llm)
        self.client.post("/api/v1/reports/drafts", json={"period": "week", "date": "2026-10-10"}, headers=self.headers)
        self.assertNotIn("Ana", llm.calls[0])

    def test_overdue_counts_only_past_due_as_of_period_end_or_today(self):
        self.client.post(f"/api/v1/patients/{self.patient_id}/follow-ups", json={"due_date": "2026-10-11"},
                         headers=self.headers)  # due tomorrow, still this week
        self.assertEqual(self.summary()["current"]["follow_ups_overdue"], 0)
        db = connect()
        try:
            with db:  # due last week, completed only this week: overdue at the end of last week
                db.execute("INSERT INTO follow_ups (id, patient_id, due_date, status, completed_at, created_by) "
                           "SELECT 'late', ?, '2026-10-01', 'completed', datetime('2026-10-07 10:00:00', 'utc'), id "
                           "FROM users LIMIT 1", (self.patient_id,))
        finally:
            db.close()
        self.assertEqual(self.summary()["previous"]["follow_ups_overdue"], 1)

    def test_event_dates_use_local_time(self):
        db = connect()
        try:
            with db:  # 01:00 local on Monday 5 Oct, stored in UTC like every datetime('now')
                db.execute("UPDATE households SET created_at = datetime('2026-10-05 01:00:00', 'utc')")
        finally:
            db.close()
        report = self.summary()
        self.assertEqual((report["current"]["new_households"], report["previous"]["new_households"]), (1, 0))
