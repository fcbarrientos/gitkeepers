from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import mock

from core import auth as auth_core
from core import config as api_config
from core.storage import connect
from tests.api_case import PASSWORD, ApiTestCase


class AppStartupTests(ApiTestCase):
    def test_health_is_open_and_database_lives_in_configured_folder(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue((self.data_dir / "app.db").is_file())


USER_KEYS = {"id", "username", "email", "full_name", "role", "status", "created_at", "updated_at"}


class SignupTests(ApiTestCase):
    def test_first_signup_is_active_admin_and_later_ones_are_pending_volunteers(self):
        first = self.signup("nurse.ana")
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual((first.json()["role"], first.json()["status"]), ("admin", "active"))
        second = self.signup("bhw.ben")
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual((second.json()["role"], second.json()["status"]), ("volunteer", "pending"))

    def test_signup_response_contains_only_public_fields(self):
        body = self.signup("nurse.ana", email="ana@example.org").json()
        self.assertEqual(set(body), USER_KEYS)
        self.assertEqual(body["email"], "ana@example.org")

    def test_password_is_stored_as_scrypt_hash(self):
        self.signup("nurse.ana")
        db = connect()
        try:
            stored = db.execute("SELECT password_hash FROM users").fetchone()[0]
        finally:
            db.close()
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(auth_core.verify_password(PASSWORD, stored))
        self.assertFalse(auth_core.verify_password("wrong-password", stored))

    def test_duplicate_username_is_rejected_case_insensitively(self):
        self.signup("Nurse.Ana")
        response = self.signup("nurse.ana")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Username already taken")

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.signup("nurse.ana", email="Ana@Example.org")
        response = self.signup("bhw.ben", email="ana@example.org")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Email already in use")

    def test_username_and_name_are_trimmed_and_blank_email_is_dropped(self):
        response = self.signup("  nurse.ana  ", full_name="  Ana Cruz ", email="   ")
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual((body["username"], body["full_name"], body["email"]), ("nurse.ana", "Ana Cruz", None))

    def test_invalid_input_is_rejected(self):
        for override in [
            {"username": "ab"},
            {"username": "has space"},
            {"username": "x" * 41},
            {"password": "short"},
            {"password": "p" * 129},
            {"full_name": "   "},
            {"email": "not-an-email"},
        ]:
            with self.subTest(override=override):
                payload = {"username": "nurse.ana", "password": PASSWORD, "full_name": "Ana", **override}
                response = self.client.post("/api/v1/auth/signup", json=payload)
                self.assertEqual(response.status_code, 422, response.text)


def session_expiry():
    db = connect()
    try:
        return db.execute("SELECT expires_at FROM sessions ORDER BY created_at LIMIT 1").fetchone()[0]
    finally:
        db.close()


class LoginTests(ApiTestCase):
    def test_login_returns_token_expiry_and_user(self):
        self.signup("nurse.ana")
        response = self.login("nurse.ana")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertGreaterEqual(len(body["token"]), 40)
        self.assertEqual(body["user"]["username"], "nurse.ana")
        self.assertEqual(set(body["user"]), USER_KEYS)
        self.assertIn("expires_at", body)

    def test_login_accepts_email_and_ignores_case_and_spaces(self):
        self.signup("nurse.ana", email="ana@example.org")
        for name in ["NURSE.ANA", "  nurse.ana ", "ANA@example.org"]:
            with self.subTest(login=name):
                self.assertEqual(self.login(name).status_code, 200)

    def test_wrong_password_and_unknown_user_get_the_same_error(self):
        self.signup("nurse.ana")
        wrong = self.login("nurse.ana", "wrong-password")
        unknown = self.login("nobody", "wrong-password")
        self.assertEqual((wrong.status_code, unknown.status_code), (401, 401))
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(wrong.json()["detail"], "Invalid username or password")

    def test_pending_user_cannot_log_in(self):
        self.signup("admin")
        self.signup("bhw.ben")
        response = self.login("bhw.ben")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Account awaiting admin approval")

    def test_pending_status_is_hidden_without_the_password(self):
        self.signup("admin")
        self.signup("bhw.ben")
        self.assertEqual(self.login("bhw.ben", "wrong-password").status_code, 401)

    def test_five_failures_lock_the_account_even_for_the_right_password(self):
        self.signup("nurse.ana")
        for _ in range(5):
            self.assertEqual(self.login("nurse.ana", "wrong-password").status_code, 401)
        response = self.login("nurse.ana")
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()["detail"], "Account temporarily locked")

    def test_lock_expires_after_five_minutes(self):
        self.signup("nurse.ana")
        for _ in range(5):
            self.login("nurse.ana", "wrong-password")
        later = auth_core._now() + timedelta(minutes=5, seconds=1)
        with mock.patch.object(auth_core, "_now", return_value=later):
            self.assertEqual(self.login("nurse.ana").status_code, 200)

    def test_successful_login_resets_the_failure_count(self):
        self.signup("nurse.ana")
        for _ in range(4):
            self.login("nurse.ana", "wrong-password")
        self.assertEqual(self.login("nurse.ana").status_code, 200)
        for _ in range(4):
            self.login("nurse.ana", "wrong-password")
        self.assertEqual(self.login("nurse.ana").status_code, 200)


class SessionTests(ApiTestCase):
    def test_me_returns_the_current_user(self):
        self.signup("nurse.ana")
        token = self.token_for("nurse.ana")
        response = self.client.get("/api/v1/auth/me", headers=self.bearer(token))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["username"], "nurse.ana")

    def test_missing_or_malformed_authorization_is_rejected(self):
        self.signup("nurse.ana")
        for headers in [
            {},
            {"Authorization": "Bearer"},
            {"Authorization": "Bearer   "},
            {"Authorization": "Basic bnVyc2U6cGFzcw=="},
            {"Authorization": "Bearer not-a-real-token"},
        ]:
            with self.subTest(headers=headers):
                response = self.client.get("/api/v1/auth/me", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Not authenticated")
                self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_token_is_stored_only_as_a_hash(self):
        self.signup("nurse.ana")
        token = self.token_for("nurse.ana")
        db = connect()
        try:
            stored = db.execute("SELECT token_hash FROM sessions").fetchone()[0]
        finally:
            db.close()
        self.assertNotEqual(stored, token)
        self.assertEqual(len(stored), 64)

    def test_logout_revokes_only_that_session(self):
        self.signup("nurse.ana")
        first, second = self.token_for("nurse.ana"), self.token_for("nurse.ana")
        response = self.client.post("/api/v1/auth/logout", headers=self.bearer(first))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(first)).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(second)).status_code, 200)

    def test_session_expires_after_seven_idle_days(self):
        self.signup("nurse.ana")
        token = self.token_for("nurse.ana")
        later = auth_core._now() + timedelta(days=7, seconds=1)
        with mock.patch.object(auth_core, "_now", return_value=later):
            self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(token)).status_code, 401)

    def test_activity_slides_the_expiry_forward(self):
        self.signup("nurse.ana")
        token = self.token_for("nurse.ana")
        start = auth_core._now()
        for days in (6, 12, 18):
            with self.subTest(days=days), mock.patch.object(
                auth_core, "_now", return_value=start + timedelta(days=days)
            ):
                self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(token)).status_code, 200)

    def test_expiry_is_not_rewritten_on_every_request(self):
        self.signup("nurse.ana")
        token = self.token_for("nurse.ana")
        before = session_expiry()
        later = auth_core._now() + timedelta(minutes=30)
        with mock.patch.object(auth_core, "_now", return_value=later):
            self.client.get("/api/v1/auth/me", headers=self.bearer(token))
        self.assertEqual(session_expiry(), before)


class ProfileTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.signup("nurse.ana", full_name="Ana Cruz", email="ana@example.org")
        self.token = self.token_for("nurse.ana")

    def patch_me(self, payload):
        return self.client.patch("/api/v1/me", json=payload, headers=self.bearer(self.token))

    def change_password(self, current, new, token=None):
        return self.client.post(
            "/api/v1/me/password",
            json={"current_password": current, "new_password": new},
            headers=self.bearer(token or self.token),
        )

    def test_update_name_and_email(self):
        response = self.patch_me({"full_name": " Ana Santos ", "email": "ana.santos@example.org"})
        self.assertEqual(response.status_code, 200, response.text)
        me = self.client.get("/api/v1/auth/me", headers=self.bearer(self.token)).json()
        self.assertEqual((me["full_name"], me["email"]), ("Ana Santos", "ana.santos@example.org"))

    def test_empty_update_changes_nothing(self):
        response = self.patch_me({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["full_name"], response.json()["email"]), ("Ana Cruz", "ana@example.org"))

    def test_blank_email_clears_it(self):
        self.assertIsNone(self.patch_me({"email": ""}).json()["email"])

    def test_blank_or_null_name_is_rejected(self):
        for payload in [{"full_name": "   "}, {"full_name": None}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.patch_me(payload).status_code, 422)

    def test_profile_update_cannot_change_role_or_status(self):
        self.signup("bhw.ben")  # pending volunteer; nurse.ana is the admin
        response = self.patch_me({"role": "volunteer", "status": "disabled"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["role"], response.json()["status"]), ("admin", "active"))

    def test_email_taken_by_someone_else_is_rejected_case_insensitively(self):
        self.signup("bhw.ben", email="ben@example.org")
        response = self.patch_me({"email": "BEN@example.org"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Email already in use")

    def test_wrong_current_password_is_rejected(self):
        response = self.change_password("wrong-password", "brand-new-pass")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Current password is incorrect")

    def test_short_new_password_is_rejected(self):
        self.assertEqual(self.change_password(PASSWORD, "short").status_code, 422)

    def test_password_change_keeps_this_session_and_revokes_others(self):
        other = self.token_for("nurse.ana")
        self.assertEqual(self.change_password(PASSWORD, "brand-new-pass").status_code, 204)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(self.token)).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(other)).status_code, 401)
        self.assertEqual(self.login("nurse.ana", PASSWORD).status_code, 401)
        self.assertEqual(self.login("nurse.ana", "brand-new-pass").status_code, 200)


class UserAdminTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.admin_token()
        self.admin_id = self.client.get("/api/v1/auth/me", headers=self.bearer(self.admin)).json()["id"]

    def patch_user(self, user_id, payload, token=None):
        return self.client.patch(f"/api/v1/users/{user_id}", json=payload, headers=self.bearer(token or self.admin))

    def test_only_admins_can_manage_users(self):
        self.active_volunteer(self.admin)
        volunteer = self.token_for("bhw.ben")
        self.assertEqual(self.client.get("/api/v1/users").status_code, 401)
        response = self.client.get("/api/v1/users", headers=self.bearer(volunteer))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Insufficient permissions")
        self.assertEqual(self.patch_user(self.admin_id, {"status": "disabled"}, volunteer).status_code, 403)

    def test_list_shows_pending_first_and_filters(self):
        self.signup("bhw.ben", full_name="Ben Reyes")
        page = self.client.get("/api/v1/users", headers=self.bearer(self.admin)).json()
        self.assertEqual(page["total"], 2)
        self.assertEqual([u["username"] for u in page["items"]], ["bhw.ben", "admin"])
        pending = self.client.get("/api/v1/users?status=pending", headers=self.bearer(self.admin)).json()
        self.assertEqual([u["username"] for u in pending["items"]], ["bhw.ben"])
        found = self.client.get("/api/v1/users?q=reyes", headers=self.bearer(self.admin)).json()
        self.assertEqual([u["username"] for u in found["items"]], ["bhw.ben"])
        literal = self.client.get("/api/v1/users?q=%25", headers=self.bearer(self.admin)).json()
        self.assertEqual(literal["total"], 0)  # "%" is matched literally, not as a wildcard

    def test_approving_a_volunteer_lets_them_log_in(self):
        user_id = self.signup("bhw.ben").json()["id"]
        self.assertEqual(self.login("bhw.ben").status_code, 403)
        response = self.patch_user(user_id, {"status": "active"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "active")
        self.assertEqual(self.login("bhw.ben").status_code, 200)

    def test_disabling_blocks_login_and_kills_existing_sessions(self):
        user_id = self.active_volunteer(self.admin)
        volunteer = self.token_for("bhw.ben")
        self.assertEqual(self.patch_user(user_id, {"status": "disabled"}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(volunteer)).status_code, 401)
        response = self.login("bhw.ben")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Account disabled")
        self.patch_user(user_id, {"status": "active"})
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(volunteer)).status_code, 401)

    def test_last_active_admin_cannot_be_removed(self):
        for payload in [{"role": "volunteer"}, {"status": "disabled"}]:
            with self.subTest(payload=payload):
                response = self.patch_user(self.admin_id, payload)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["detail"], "Cannot remove the last active admin")

    def test_admin_can_step_down_once_another_admin_exists(self):
        user_id = self.active_volunteer(self.admin)
        self.assertEqual(self.patch_user(user_id, {"role": "admin"}).json()["role"], "admin")
        self.assertEqual(self.patch_user(self.admin_id, {"role": "volunteer"}).status_code, 200)

    def test_unknown_user_returns_404(self):
        missing = "00000000-0000-0000-0000-000000000000"
        headers = self.bearer(self.admin)
        self.assertEqual(self.client.get(f"/api/v1/users/{missing}", headers=headers).status_code, 404)
        self.assertEqual(self.patch_user(missing, {"status": "active"}).status_code, 404)
        response = self.client.post(
            f"/api/v1/users/{missing}/password", json={"new_password": "brand-new-pass"}, headers=headers
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "User not found")

    def test_pending_is_not_a_settable_status(self):
        user_id = self.active_volunteer(self.admin)
        self.assertEqual(self.patch_user(user_id, {"status": "pending"}).status_code, 422)

    def test_admin_password_reset_revokes_sessions_and_clears_lock(self):
        user_id = self.active_volunteer(self.admin)
        volunteer = self.token_for("bhw.ben")
        for _ in range(5):
            self.login("bhw.ben", "wrong-password")
        response = self.client.post(
            f"/api/v1/users/{user_id}/password",
            json={"new_password": "brand-new-pass"},
            headers=self.bearer(self.admin),
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.bearer(volunteer)).status_code, 401)
        self.assertEqual(self.login("bhw.ben", "brand-new-pass").status_code, 200)


class ProtectedRouteTests(ApiTestCase):
    def test_records_require_a_signed_in_user(self):
        self.assertEqual(self.client.get("/api/v1/households").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/patients").status_code, 401)
        token = self.admin_token()
        created = self.client.post(
            "/api/v1/households", json={"barangay": "San Roque"}, headers=self.bearer(token)
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(self.client.get("/api/v1/households", headers=self.bearer(token)).json()["total"], 1)

    def test_conversations_and_chat_require_a_signed_in_user(self):
        self.assertEqual(self.client.get("/api/v1/conversations").status_code, 401)
        self.assertEqual(self.client.get("/conversations").status_code, 401)
        self.assertEqual(self.client.post("/api/v1/chat", json={"message": "hi"}).status_code, 401)
        token = self.admin_token()
        self.assertEqual(self.client.get("/api/v1/conversations", headers=self.bearer(token)).status_code, 200)

    def test_health_stays_open(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_shell_token_is_still_enforced_outside_user_auth(self):
        token = self.admin_token()
        with mock.patch.object(api_config, "API_TOKEN", "shell-secret"):
            only_bearer = self.client.get("/api/v1/households", headers=self.bearer(token))
            self.assertEqual(only_bearer.status_code, 401)
            self.assertEqual(only_bearer.json()["detail"], "invalid or missing X-API-Token")
            both = {**self.bearer(token), "X-API-Token": "shell-secret"}
            self.assertEqual(self.client.get("/api/v1/households", headers=both).status_code, 200)
            self.assertEqual(self.login("admin").status_code, 401)  # signup/login need the shell token too
            self.assertEqual(self.client.get("/health").status_code, 200)


class HardeningTests(ApiTestCase):
    def test_parallel_wrong_passwords_still_lock_the_account(self):
        self.signup("nurse.ana")
        with ThreadPoolExecutor(max_workers=20) as pool:
            codes = list(pool.map(lambda _: self.login("nurse.ana", "wrong-password").status_code, range(20)))
        self.assertTrue(all(code in (401, 423) for code in codes), codes)
        self.assertEqual(self.login("nurse.ana").status_code, 423)

    def test_validation_errors_never_echo_the_password(self):
        secret = "s3cret-pass"
        cases = [
            ("/api/v1/auth/signup", {"username": "nurse.ana", "password": "short7"}),  # too short
            ("/api/v1/auth/signup", {"username": "ab", "password": secret, "full_name": "Ana"}),
            ("/api/v1/auth/signup", {"username": "nurse.ana", "password": secret}),  # missing full_name
        ]
        for path, payload in cases:
            with self.subTest(payload=payload):
                response = self.client.post(path, json=payload)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn(payload["password"], response.text)
                self.assertIn("loc", response.json()["detail"][0])

    def test_busy_database_returns_503_not_500(self):
        with mock.patch.object(api_config, "DB_BUSY_TIMEOUT_SECONDS", 0.1):
            blocker = connect()
            try:
                blocker.execute("BEGIN IMMEDIATE")  # another writer holds the lock
                response = self.signup("nurse.ana")
            finally:
                blocker.rollback()
                blocker.close()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Database is busy, please try again")

    def test_login_purges_the_users_dead_sessions(self):
        self.signup("nurse.ana")
        revoked = self.token_for("nurse.ana")
        self.client.post("/api/v1/auth/logout", headers=self.bearer(revoked))
        self.token_for("nurse.ana")
        later = auth_core._now() + timedelta(days=8)
        with mock.patch.object(auth_core, "_now", return_value=later):
            self.token_for("nurse.ana")  # the previous session is now expired
        db = connect()
        try:
            self.assertEqual(db.execute("SELECT count(*) FROM sessions").fetchone()[0], 1)
        finally:
            db.close()

    def test_corrupted_password_hash_fails_login_instead_of_crashing(self):
        self.signup("nurse.ana")
        db = connect()
        try:
            with db:
                db.execute("UPDATE users SET password_hash = 'scrypt$!!not-base64!!$???'")
        finally:
            db.close()
        self.assertEqual(self.login("nurse.ana").status_code, 401)


class ChatTests(ApiTestCase):
    def test_assistant_reply_is_saved_after_streaming(self):
        token = self.admin_token()
        response = self.client.post("/api/v1/chat", json={"message": "kumusta"}, headers=self.bearer(token))
        self.assertEqual(response.status_code, 200)
        cid = int(response.text.rsplit("data: ", 1)[1].strip())
        messages = self.client.get(f"/api/v1/conversations/{cid}/messages", headers=self.bearer(token)).json()
        self.assertEqual([m["role"] for m in messages["items"]], ["user", "assistant"])
