import unittest

from core.pseudonymize import Pseudonymizer
from core.sync import (
    create_sync_bundle,
    decrypt_vault,
    encrypt_vault,
    unpack_and_resolve_bundle,
    unpack_deidentified_bundle,
)


class PseudonymizationTests(unittest.TestCase):
    def setUp(self):
        self.psn = Pseudonymizer(salt="test-rural-salt")

    def test_filipino_name_markers(self):
        note = "Buntis po si Maria Santos, 28 linggo na. Nagpa-checkup kasama ni Tatay Cardo."
        anon = self.psn.pseudonymize_text(note)
        self.assertNotIn("Maria Santos", anon)
        self.assertNotIn("Cardo", anon)
        self.assertIn("PSN-NAME-", anon)
        self.assertIn("Tatay PSN-NAME-", anon)

        # Reversibility
        restored = self.psn.depseudonymize_text(anon)
        self.assertEqual(restored, note)

    def test_philippine_phone_and_philhealth(self):
        note = "Contact: 0917-123-4567, PhilHealth: 12-345678901-2. May lagnat po."
        anon = self.psn.pseudonymize_text(note)
        self.assertNotIn("0917-123-4567", anon)
        self.assertNotIn("12-345678901-2", anon)
        self.assertIn("PSN-PHONE-", anon)
        self.assertIn("PSN-PHIC-", anon)
        self.assertIn("May lagnat po.", anon)

        # Restore
        restored = self.psn.depseudonymize_text(anon)
        self.assertEqual(restored, note)

    def test_philippine_addresses(self):
        note = "Nakatira sa Brgy. San Jose, Sitio Ilaya kanina nagpunta sa health center."
        anon = self.psn.pseudonymize_text(note)
        self.assertNotIn("San Jose", anon)
        self.assertIn("PSN-LOC-", anon)

    def test_deterministic_pseudonyms_same_patient(self):
        psn1 = self.psn.get_or_create("PATIENT", "Rosa Gomez")
        psn2 = self.psn.get_or_create("PATIENT", "Rosa Gomez")
        self.assertEqual(psn1, psn2)

    def test_structured_record_pseudonymization(self):
        record = {
            "patient_name": "Juana Dela Cruz",
            "contact_number": "09181234567",
            "philhealth_no": "12-123456789-0",
            "address": "Brgy. Maligaya",
            "visit": {
                "note": "Nagpunta si Juana Dela Cruz dahil masakit ang ulo.",
                "weeks_pregnant": 24,
                "headache": True,
            },
        }

        anon_record = self.psn.pseudonymize_record(record)
        self.assertNotEqual(anon_record["patient_name"], "Juana Dela Cruz")
        self.assertTrue(anon_record["patient_name"].startswith("PSN-PAT-"))
        self.assertTrue(anon_record["contact_number"].startswith("PSN-PHONE-"))
        self.assertNotIn("Juana Dela Cruz", anon_record["visit"]["note"])
        self.assertEqual(anon_record["visit"]["weeks_pregnant"], 24)
        self.assertEqual(anon_record["visit"]["headache"], True)

        restored_record = self.psn.depseudonymize_record(anon_record)
        self.assertEqual(restored_record, record)


class SyncProtocolTests(unittest.TestCase):
    def test_sync_bundle_encryption_and_resolution(self):
        secret_key = "secret-rhu-hospital-passphrase-2026"
        sample_records = [
            {
                "id": "v001",
                "patient_name": "Elena Torres",
                "phone": "09191112233",
                "address": "Sitio Riverside",
                "notes": "Si Elena Torres ay may ubo at lagnat, 38.2 C.",
                "vitals": {"bp_systolic": 120, "bp_diastolic": 80, "temperature_c": 38.2},
            },
            {
                "id": "v002",
                "patient_name": "Roberto Diaz",
                "phone": "09204445566",
                "address": "Brgy. San Roque",
                "notes": "Tatay Roberto Diaz masikip ang dibdib.",
                "vitals": {"bp_systolic": 150, "bp_diastolic": 95},
            },
        ]

        bundle = create_sync_bundle(sample_records, station_id="BHS-042", secret_key=secret_key)
        self.assertEqual(bundle["station_id"], "BHS-042")
        self.assertEqual(bundle["record_count"], 2)

        # Verify transit data is de-identified
        for item in bundle["payload"]:
            self.assertNotIn("Elena Torres", str(item))
            self.assertNotIn("Roberto Diaz", str(item))
            self.assertNotIn("09191112233", str(item))
            self.assertIn("PSN-PAT-", str(item))

        # Verify hospital resolution
        resolved = unpack_and_resolve_bundle(bundle, secret_key=secret_key)
        self.assertEqual(len(resolved), 2)
        self.assertEqual(resolved[0]["patient_name"], "Elena Torres")
        self.assertEqual(resolved[0]["phone"], "09191112233")
        self.assertEqual(resolved[1]["patient_name"], "Roberto Diaz")
        self.assertEqual(resolved[1]["vitals"]["bp_systolic"], 150)

    def test_wrong_key_fails_gracefully(self):
        records = [{"patient_name": "Ana Santos", "note": "Checkup para kay Ana Santos."}]
        bundle = create_sync_bundle(records, station_id="BHS-001", secret_key="correct-key")

        with self.assertRaises(Exception):
            unpack_and_resolve_bundle(bundle, secret_key="wrong-key")

    def test_anonymous_unpack_for_epidemiology(self):
        records = [{"patient_name": "Pedro Penduko", "note": "May ubo at sipon si Pedro Penduko."}]
        bundle = create_sync_bundle(records, station_id="BHS-001", secret_key="rhu-key")
        anon_data = unpack_deidentified_bundle(bundle)
        self.assertEqual(len(anon_data), 1)
        self.assertNotIn("Pedro Penduko", str(anon_data[0]))
        self.assertIn("PSN-PAT-", str(anon_data[0]))


if __name__ == "__main__":
    unittest.main()
