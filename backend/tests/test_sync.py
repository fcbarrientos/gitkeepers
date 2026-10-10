"""Manual transfer: pending records, encrypted transfer files and signed RHU receipts."""
import json
import tempfile
from pathlib import Path

from core.pseudonymize import Pseudonymizer
from core.storage import connect
from core.sync import unpack_and_resolve_bundle
from core.sync_state import make_receipt
from scripts.rhu_receipt import write_receipt
from tests.api_case import VisitTestCase

PASSPHRASE = "rhu-shared-secret-123"


class SyncTestCase(VisitTestCase):
    def setUp(self):
        super().setUp()
        self.visit = self.create_visit(status="final").json()
        self.referral = self.client.post("/api/v1/referrals", json={
            "patient_id": self.patient_id, "facility": "RHU", "reason": "BP", "urgency": "urgent"},
            headers=self.headers).json()

    def set_passphrase(self, passphrase=PASSPHRASE, headers=None):
        return self.client.put("/api/v1/sync/settings", json={"passphrase": passphrase},
                               headers=headers or self.headers)

    def status(self):
        return self.client.get("/api/v1/sync/status", headers=self.headers).json()

    def export(self):
        return self.client.post("/api/v1/sync/bundles", headers=self.headers)

    def receipt(self, receipt):
        return self.client.post("/api/v1/sync/receipts", json=receipt, headers=self.headers)


class ExportTests(SyncTestCase):
    def test_new_records_are_pending(self):
        records = self.status()["records"]
        self.assertEqual(records["household"]["pending"], 1)
        self.assertEqual(records["patient"]["pending"], 1)
        self.assertEqual(records["visit"]["pending"], 1)
        self.assertEqual(records["referral"]["pending"], 1)

    def test_drafts_are_not_transferred(self):
        self.create_visit()  # draft
        self.assertEqual(self.status()["records"]["visit"]["pending"], 1)

    def test_export_needs_a_passphrase_set_by_an_admin(self):
        self.assertEqual(self.export().json()["detail"], ["passphrase: set the RHU passphrase in Sync settings first"])
        self.assertEqual(self.set_passphrase("short").status_code, 422)
        volunteer = self.active_volunteer(self.token)
        self.assertTrue(volunteer)
        volunteer_headers = self.bearer(self.token_for("bhw.ben"))
        self.assertEqual(self.set_passphrase(headers=volunteer_headers).status_code, 403)
        self.assertEqual(self.set_passphrase().status_code, 204)
        self.assertTrue(self.status()["passphrase_set"])

    def test_export_moves_records_to_awaiting_and_hides_identities(self):
        self.set_passphrase()
        response = self.export()
        self.assertEqual(response.status_code, 201, response.text)
        bundle = response.json()
        self.assertEqual(bundle["record_count"], 4)
        payload = json.dumps(bundle["payload"])
        for secret in ("Ana Dela Cruz", "09171234567", "San Roque", "Malinis", "Purok 2"):
            self.assertNotIn(secret, payload)
        records = self.status()["records"]
        self.assertEqual((records["visit"]["pending"], records["visit"]["awaiting"]), (0, 1))
        self.assertEqual(self.export().status_code, 409)  # nothing left to send
        again = self.client.get(f"/api/v1/sync/bundles/{bundle['bundle_id']}", headers=self.headers).json()
        self.assertEqual(again["bundle_id"], bundle["bundle_id"])


class ReceiptTests(SyncTestCase):
    def setUp(self):
        super().setUp()
        self.set_passphrase()
        self.bundle = self.export().json()

    def test_valid_receipt_marks_records_synced_and_referrals_sent(self):
        response = self.receipt(make_receipt(self.bundle, PASSPHRASE))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(response.json()["acknowledged_at"])
        status = self.status()
        self.assertEqual(status["records"]["visit"], {"pending": 0, "awaiting": 0, "synced": 1})
        self.assertIsNotNone(status["last_acknowledged_at"])
        referral = self.client.get(f"/api/v1/referrals/{self.referral['id']}", headers=self.headers).json()
        self.assertEqual(referral["status"], "sent")
        self.assertEqual(self.status()["records"]["referral"]["synced"], 1)  # "sent" is not a new version
        self.assertEqual(self.receipt(make_receipt(self.bundle, PASSPHRASE)).status_code, 200)  # idempotent

    def test_bad_receipts_change_nothing(self):
        good = make_receipt(self.bundle, PASSPHRASE)
        cases = [
            ({**good, "signature": make_receipt(self.bundle, "some-other-passphrase")["signature"]},
             "signature: this receipt was not signed with this device's RHU passphrase"),
            ({**good, "record_count": 99}, "record_count: does not match the transfer file"),
            ({**good, "bundle_id": "nope"}, "bundle_id: no transfer file with this ID was made on this device"),
            ({**good, "format": "x"}, "format: this is not a GitKeepers RHU receipt"),
        ]
        for receipt, message in cases:
            response = self.receipt(receipt)
            self.assertEqual((response.status_code, response.json()["detail"]), (422, [message]))
        self.assertEqual(self.status()["records"]["visit"]["awaiting"], 1)

    def test_a_record_edited_after_export_is_pending_again(self):
        db = connect()
        try:
            with db:
                db.execute("UPDATE patients SET updated_at = '2099-01-01 00:00:00'")
        finally:
            db.close()
        self.receipt(make_receipt(self.bundle, PASSPHRASE))
        records = self.status()["records"]
        self.assertEqual((records["patient"]["pending"], records["patient"]["synced"]), (1, 0))
        self.assertEqual(self.export().json()["record_count"], 1)

    def test_rhu_script_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "transfer.json"
            path.write_text(json.dumps(self.bundle), encoding="utf-8")
            receipt_path = write_receipt(path, PASSPHRASE)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(self.receipt(receipt).status_code, 200)
        listed = self.client.get("/api/v1/sync/bundles", headers=self.headers).json()
        self.assertEqual(listed[0]["record_count"], 4)
        self.assertIsNotNone(listed[0]["acknowledged_at"])


class PrivacyTests(SyncTestCase):
    def test_free_text_is_vaulted_and_restored_at_the_rhu(self):
        self.client.post("/api/v1/referrals", json={
            "patient_id": self.patient_id, "facility": "Dr. Reyes clinic, Brgy San Roque",
            "reason": "Ana Dela Cruz BP 190/120", "notes": "Husband Jose Cruz will bring her", "urgency": "urgent"},
            headers=self.headers)
        self.client.post(f"/api/v1/patients/{self.patient_id}/follow-ups", json={
            "due_date": "2026-10-20", "reason": "Check Ana Dela Cruz again at Purok 2"}, headers=self.headers)
        self.create_visit(status="final", note="Maria Santos complained of headache, lives near the chapel")
        self.set_passphrase()
        bundle = self.export().json()
        payload = json.dumps(bundle["payload"])
        for secret in ("Ana Dela Cruz", "Reyes", "Jose Cruz", "Purok 2", "Maria Santos", "chapel"):
            self.assertNotIn(secret, payload)
        restored = json.dumps(unpack_and_resolve_bundle(bundle, PASSPHRASE))
        self.assertIn("Husband Jose Cruz will bring her", restored)
        self.assertIn("Maria Santos complained of headache, lives near the chapel", restored)

    def test_pseudonyms_cannot_be_rebuilt_from_the_station_id(self):
        self.set_passphrase()
        bundle = self.export().json()
        guessed = Pseudonymizer(salt=f"rhu-sync-{bundle['station_id']}").get_or_create("LOCATION", "San Roque")
        self.assertNotIn(guessed, json.dumps(bundle["payload"]))


class OpenFileTests(SyncTestCase):
    def test_passphrase_cannot_change_while_a_file_awaits_its_receipt(self):
        self.set_passphrase()
        bundle = self.export().json()
        self.assertEqual(self.set_passphrase("another-long-passphrase").status_code, 409)
        cancel = self.client.post(f"/api/v1/sync/bundles/{bundle['bundle_id']}/cancel", headers=self.headers)
        self.assertEqual(cancel.status_code, 204)
        self.assertEqual(self.status()["records"]["visit"], {"pending": 1, "awaiting": 0, "synced": 0})
        self.assertEqual(self.set_passphrase("another-long-passphrase").status_code, 204)
        self.assertEqual(self.export().json()["record_count"], 4)

    def test_acknowledged_files_cannot_be_cancelled(self):
        self.set_passphrase()
        bundle = self.export().json()
        self.receipt(make_receipt(bundle, PASSPHRASE))
        cancel = self.client.post(f"/api/v1/sync/bundles/{bundle['bundle_id']}/cancel", headers=self.headers)
        self.assertEqual(cancel.status_code, 409)
