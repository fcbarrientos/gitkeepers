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
        done = self.client.get("/api/v1/follow-ups?state=completed", headers=self.headers).json()["items"][0]
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
