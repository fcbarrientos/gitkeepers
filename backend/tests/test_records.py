import sqlite3
import unittest
from datetime import date
from pathlib import Path

from core.records import add_patient, create_household, get_household, get_patient, list_households, list_patients
from core.storage import migrate


class RecordStoreTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        migrations = Path(__file__).resolve().parent.parent / "migrations"
        migrate(self.db, migrations)

    def tearDown(self):
        self.db.close()

    def test_register_and_search_household_by_member(self):
        household = create_household(self.db, {
            "barangay": "San Roque",
            "sitio": "Purok 2",
            "members": [{
                "full_name": "Ana Dela Cruz",
                "birth_date": date(1990, 5, 4),
                "sex": "female",
                "is_household_head": True,
            }],
        })

        result = list_households(self.db, "ana", 25, 0)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], household["id"])
        self.assertEqual(result["items"][0]["head_name"], "Ana Dela Cruz")
        self.assertEqual(household["members"][0]["birth_date"], "1990-05-04")

    def test_add_and_search_patient_with_pagination(self):
        household = create_household(self.db, {"barangay": "San Roque"})
        first = add_patient(self.db, household["id"], {"full_name": "Ana Santos"})
        add_patient(self.db, household["id"], {"full_name": "Ben Santos"})

        result = list_patients(self.db, "sant", household["id"], 1, 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["limit"], 1)
        self.assertEqual(result["offset"], 1)
        self.assertEqual(result["items"][0]["full_name"], "Ben Santos")
        self.assertEqual(get_patient(self.db, first["id"])["household_id"], household["id"])
        self.assertEqual(len(get_household(self.db, household["id"])["members"]), 2)

    def test_household_head_is_unique(self):
        household = create_household(self.db, {
            "barangay": "San Roque",
            "members": [{"full_name": "Ana Santos", "is_household_head": True}],
        })
        with self.assertRaises(sqlite3.IntegrityError):
            add_patient(self.db, household["id"], {
                "full_name": "Ben Santos",
                "is_household_head": True,
            })

    def test_search_handles_punctuation_without_fts_syntax_errors(self):
        create_household(self.db, {"barangay": "San Roque"})
        self.assertEqual(list_households(self.db, '""', 25, 0)["total"], 0)
        self.assertEqual(list_households(self.db, "roque", 25, 0)["total"], 1)


if __name__ == "__main__":
    unittest.main()
