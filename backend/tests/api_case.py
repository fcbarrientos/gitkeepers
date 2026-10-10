"""Shared base class for HTTP-level tests: every test gets a fresh database folder."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import api
from core import clock, config
from core.assist import get_assist_llm
from tests.fakes import FakeLLM

PASSWORD = "correct-horse"
TODAY = date(2026, 10, 10)


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        for name, value in {
            "DATA_DIR": self.data_dir,
            "DB_PATH": self.data_dir / "app.db",
            "MODELS_DIR": self.data_dir / "models",
            "API_TOKEN": None,
        }.items():
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(api.app)
        self.client.__enter__()  # runs the startup migrations against the temp database
        self.addCleanup(self.client.__exit__, None, None, None)

    def signup(self, username, password=PASSWORD, full_name=None, email=None):
        payload = {"username": username, "password": password, "full_name": full_name or "Test User"}
        if email is not None:
            payload["email"] = email
        return self.client.post("/api/v1/auth/signup", json=payload)

    def login(self, login, password=PASSWORD):
        return self.client.post("/api/v1/auth/login", json={"login": login, "password": password})

    def token_for(self, login, password=PASSWORD):
        response = self.login(login, password)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["token"]

    @staticmethod
    def bearer(token):
        return {"Authorization": f"Bearer {token}"}

    def admin_token(self):
        """Sign up the first account on the device (which becomes admin) and log in."""
        self.assertEqual(self.signup("admin").status_code, 201)
        return self.token_for("admin")

    def active_volunteer(self, admin_token, username="bhw.ben"):
        """Sign up a volunteer and approve it. Returns the new user's id."""
        user_id = self.signup(username).json()["id"]
        response = self.client.patch(
            f"/api/v1/users/{user_id}", json={"status": "active"}, headers=self.bearer(admin_token)
        )
        self.assertEqual(response.status_code, 200, response.text)
        return user_id

    def make_patient(self, token, full_name="Ana Dela Cruz", barangay="San Roque", sitio="Malinis",
                     contact_number="09171234567"):
        """Register a one-member household and return the member's patient id."""
        response = self.client.post("/api/v1/households", headers=self.bearer(token), json={
            "barangay": barangay, "sitio": sitio, "address_line": "Purok 2",
            "members": [{"full_name": full_name, "sex": "female", "birth_date": "1995-03-14",
                         "contact_number": contact_number, "is_household_head": True}],
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["members"][0]["id"]

    def use_llm(self, llm):
        """Serve `llm` as the AI model for this test."""
        api.app.dependency_overrides[get_assist_llm] = lambda: llm
        self.addCleanup(api.app.dependency_overrides.pop, get_assist_llm, None)


class VisitTestCase(ApiTestCase):
    """A signed-in admin, one patient, and the calendar pinned to TODAY."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(clock, "today", return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.token = self.admin_token()
        self.headers = self.bearer(self.token)
        self.patient_id = self.make_patient(self.token)

    def create_visit(self, patient_id=None, **overrides):
        payload = {"form_type": "bp_followup", "visit_date": "2026-10-10",
                   "values": {"bp_systolic": 150, "bp_diastolic": 95}, **overrides}
        return self.client.post(f"/api/v1/patients/{patient_id or self.patient_id}/visits",
                                json=payload, headers=self.headers)

    def patch_visit(self, visit_id, **changes):
        return self.client.patch(f"/api/v1/visits/{visit_id}", json=changes, headers=self.headers)

    def suggest(self, reply, form_type="bp_followup", note="BP 150/95, nahihilo", patient_id=None):
        self.use_llm(FakeLLM(reply))
        response = self.client.post(f"/api/v1/patients/{patient_id or self.patient_id}/suggestions",
                                    json={"form_type": form_type, "note": note}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()
