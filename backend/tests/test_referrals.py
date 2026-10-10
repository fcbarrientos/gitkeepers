"""Rule-based referral flags and referral slips."""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from core import referrals
from core.forms import get_form
from core.referrals import COMPARE, load_rules, matches
from tests.api_case import VisitTestCase

SEVERE = {"bp_systolic": 185, "bp_diastolic": 100, "chest_pain": True}


class RuleFileTests(VisitTestCase):
    def test_every_rule_names_a_real_field_with_a_matching_type(self):
        for form_type, rule_set in load_rules().items():
            form = get_form(form_type)
            self.assertIsNotNone(form, form_type)
            types = {f["name"]: f["type"] for f in form["fields"]}
            for rule in rule_set["rules"]:
                self.assertIn(rule["urgency"], ("urgent", "routine"))
                self.assertTrue(rule["reason"]["en"] and rule["reason"]["fil"], rule["id"])
                for cond in rule["when"].get("any") or rule["when"].get("all") or [rule["when"]]:
                    self.assertIn(cond["field"], types, rule["id"])
                    if cond["op"] == "is_true":
                        self.assertEqual(types[cond["field"]], "boolean", rule["id"])
                    else:
                        self.assertIn(cond["op"], COMPARE, rule["id"])
                        self.assertIn(types[cond["field"]], ("integer", "number"), rule["id"])

    def test_matching_ignores_unrecorded_values(self):
        rule = {"any": [{"field": "bp_systolic", "op": ">=", "value": 140}, {"field": "bleeding", "op": "is_true"}]}
        self.assertTrue(matches(rule, {"bp_systolic": 150}))
        self.assertTrue(matches(rule, {"bleeding": True}))
        self.assertFalse(matches(rule, {"bp_systolic": None, "bleeding": False}))
        self.assertFalse(matches({"all": [{"field": "a", "op": "<", "value": 1}]}, {"a": True}))


class FlagTests(VisitTestCase):
    def flags(self, query=""):
        return self.client.get(f"/api/v1/referral-flags{query}", headers=self.headers).json()

    def test_finalizing_flags_every_matching_rule(self):
        visit = self.create_visit(status="final", values=SEVERE).json()
        flags = self.flags(f"?visit_id={visit['id']}")
        self.assertEqual(sorted(f["rule_id"] for f in flags), ["bp-chest-pain", "bp-severe"])
        self.assertEqual(flags[0]["patient_name"], "Ana Dela Cruz")
        self.assertEqual({f["status"] for f in flags}, {"open"})

    def test_drafts_and_normal_values_are_not_flagged(self):
        self.create_visit(values=SEVERE)  # draft
        self.create_visit(status="final", values={"bp_systolic": 130, "bp_diastolic": 85})
        self.assertEqual(self.flags(), [])

    def test_finalizing_a_draft_flags_it(self):
        draft = self.create_visit(values=SEVERE).json()
        self.assertEqual(self.patch_visit(draft["id"], status="final").status_code, 200)
        self.assertEqual(len(self.flags(f"?visit_id={draft['id']}")), 2)

    def test_dismiss_once(self):
        self.create_visit(status="final", values={"bp_systolic": 190, "bp_diastolic": 100})
        flag = self.flags()[0]
        response = self.client.post(f"/api/v1/referral-flags/{flag['id']}/dismiss",
                                    json={"note": "Seen by midwife"}, headers=self.headers)
        self.assertEqual((response.status_code, response.json()["status"]), (200, "dismissed"))
        again = self.client.post(f"/api/v1/referral-flags/{flag['id']}/dismiss", json={}, headers=self.headers)
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.flags("?status=open"), [])

    def test_rules_endpoint(self):
        rule_sets = self.client.get("/api/v1/referral-rules", headers=self.headers).json()
        self.assertEqual({r["form_type"] for r in rule_sets}, {"prenatal", "child_growth", "bp_followup"})


class ReferralTests(VisitTestCase):
    def referral(self, **overrides):
        payload = {"patient_id": self.patient_id, "facility": "San Roque RHU", "reason": "Very high BP",
                   "urgency": "urgent", **overrides}
        return self.client.post("/api/v1/referrals", json=payload, headers=self.headers)

    def test_referral_from_a_flag_marks_it_referred_and_carries_the_visit(self):
        self.create_visit(status="final", values={"bp_systolic": 190, "bp_diastolic": 100})
        flag = self.client.get("/api/v1/referral-flags", headers=self.headers).json()[0]
        response = self.referral(flag_id=flag["id"], notes="Please assess today")
        self.assertEqual(response.status_code, 201, response.text)
        referral = response.json()
        self.assertEqual((referral["status"], referral["created_by_name"]), ("issued", "Test User"))
        self.assertEqual(referral["visit"]["values"]["bp_systolic"], 190)
        self.assertEqual(referral["barangay"], "San Roque")
        flag = self.client.get(f"/api/v1/referral-flags/{flag['id']}", headers=self.headers).json()
        self.assertEqual(flag["status"], "referred")
        self.assertEqual(self.referral(flag_id=flag["id"]).status_code, 409)

    def test_manual_referral_and_listing(self):
        self.assertEqual(self.referral().status_code, 201)
        page = self.client.get(f"/api/v1/referrals?patient_id={self.patient_id}", headers=self.headers).json()
        self.assertEqual(page["total"], 1)
        self.assertIsNone(page["items"][0]["visit"])

    def test_rejects_bad_input(self):
        other = self.make_patient(self.token, full_name="Berto Santos", contact_number="09179999999")
        self.create_visit(patient_id=other, status="final", values={"bp_systolic": 190, "bp_diastolic": 100})
        flag = self.client.get("/api/v1/referral-flags", headers=self.headers).json()[0]
        self.assertEqual(self.referral(flag_id=flag["id"]).json()["detail"],
                         ["flag_id: not a referral flag of this patient"])
        self.assertEqual(self.referral(facility="   ").status_code, 422)
        self.assertEqual(self.referral(patient_id="nope").status_code, 404)


class BrokenRuleFileTests(VisitTestCase):
    def test_a_broken_rule_file_never_blocks_finalizing(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        shutil.copy(referrals.RULES_DIR / "bp_followup.json", folder / "bp_followup.json")
        (folder / "prenatal.json").write_text('{"form_type": "prenatal", "rules": [,]}', encoding="utf-8")
        (folder / "child_growth.json").write_text(
            '{"form_type": "child_growth", "verification": "x", "rules": [{"id": "typo", "urgency": "urgent", '
            '"when": {"field": "muac_cmm", "op": "<", "value": 11.5}, "reason": {"en": "x", "fil": "x"}}]}',
            encoding="utf-8")
        with mock.patch.object(referrals, "RULES_DIR", folder):
            visit = self.create_visit(status="final", values=SEVERE)
            self.assertEqual(visit.status_code, 201, visit.text)
            self.assertEqual(len(self.client.get("/api/v1/referral-flags", headers=self.headers).json()), 2)
            rule_sets = self.client.get("/api/v1/referral-rules", headers=self.headers)
            self.assertEqual([r["form_type"] for r in rule_sets.json()], ["bp_followup"])
            self.assertEqual(len(referrals.rule_problems()), 2)
