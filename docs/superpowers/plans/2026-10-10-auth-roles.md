# Auth, Roles & Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add offline local accounts (signup with admin approval, login, logout, profile, admin user management) and require a signed-in user on every existing feature endpoint.

**Architecture:** Accounts and sessions live in the device's SQLite database (migration `003`). `core/auth.py` holds the service functions (scrypt hashing, opaque bearer tokens stored only as SHA-256 hashes, lockout, last-admin protection) plus two FastAPI dependencies, `current_user` and `require_role`. Service functions raise `AuthError`, which one handler in `api.py` turns into `{"detail": ...}` responses. `routes/auth.py` serves `/auth/*` and `/me`, and `routes/users.py` serves the admin `/users` endpoints. Both are mounted under `/api/v1`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, sqlite3, stdlib `hashlib`/`secrets`/`hmac`, `unittest` + `fastapi.testclient` (needs `httpx`, test-only).

**Spec:** `docs/superpowers/specs/2026-10-10-auth-roles-design.md`

## Global Constraints

- **Do not run `git commit`, `git push`, or create branches.** The user handles git. Leave all changes in the working tree.
- Work from `gitkeepers/backend/`. All paths below are relative to it.
- Use only the standard library for hashing and tokens. `httpx` is the one new package, and it is test-only.
- scrypt parameters: `n=2**14, r=8, p=1, dklen=32`, 16-byte random salt. Stored format: `scrypt$<salt_b64>$<hash_b64>`.
- Sessions: `secrets.token_urlsafe(32)`. Store only `sha256(token)` hex. 7-day sliding expiry, written at most once per hour per session.
- Lockout: 5 consecutive failed logins lock the account for 5 minutes (HTTP 423).
- Username: 3–40 characters matching `^[A-Za-z0-9._-]+$`, unique case-insensitively. Password: 8–128 characters. full_name: 1–200 characters after trimming. Email: optional, unique case-insensitively, max 254 characters.
- Roles: `admin`, `volunteer`. Statuses: `pending`, `active`, `disabled`.
- Error bodies use FastAPI's `{"detail": "<message>"}`. Every 401 carries `WWW-Authenticate: Bearer`.
- Exact messages: `"Invalid username or password"`, `"Account temporarily locked"`, `"Account awaiting admin approval"`, `"Account disabled"`, `"Not authenticated"`, `"Insufficient permissions"`, `"Username already taken"`, `"Email already in use"`, `"Current password is incorrect"`, `"Cannot remove the last active admin"`, `"User not found"`.
- The existing `X-API-Token` shell check (`api.require_token`) stays on every route except `/health`.

## Review Focus

- **Login typed with different case or surrounding spaces** (`"  NURSE.ANA "`) → logs in. Pinned in Task 3, `test_login_accepts_email_and_ignores_case_and_spaces`.
- **Malformed `Authorization` header** (`Bearer` with no token, `Basic …`, random token) → 401, never 500. Pinned in Task 3, `test_missing_or_malformed_authorization_is_rejected`.
- **Email reused with different case** at signup or profile update → 409 `"Email already in use"`, not a 500 or the wrong message. Pinned in Task 2 and Task 4.
- **Lock window elapses** → the correct password works again without admin help. Pinned in Task 3, `test_lock_expires_after_five_minutes`.
- **Privilege escalation through `/me`** (a volunteer sends `{"role":"admin","status":"active"}`) → ignored. Pinned in Task 4, `test_profile_update_cannot_change_role_or_status`.

---

### Task 1: Test harness and import-time side-effect fix

Right now `api.py` migrates the real user-data database when it is imported, and `core/storage.connect()` binds `DB_PATH` when the module loads. Tests therefore can't point the app at a temporary folder. This task moves migration into a FastAPI lifespan hook, makes `storage` read paths from `config` at call time, and adds a reusable `ApiTestCase`.

**Files:**
- Modify: `core/storage.py` (whole file shown)
- Modify: `api.py` (top section through `app.add_middleware`)
- Modify: `requirements.txt`
- Create: `tests/api_case.py`
- Create: `tests/test_auth.py`

**Interfaces:**
- Produces: `core.storage.connect(db_path: Path | None = None) -> sqlite3.Connection` and `core.storage.migrate(conn, migrations_dir: Path | None = None) -> list[str]`, both reading `core.config` at call time. Also `tests.api_case.ApiTestCase` with `self.client`, `self.data_dir`, and helper methods `signup`, `login`, `token_for`, `bearer`, `admin_token`, `active_volunteer` (the helpers call endpoints that later tasks add).

- [ ] **Step 1: Create the virtualenv and install dependencies**

Run from `backend/`:
```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install fastapi uvicorn platformdirs cryptography sqlite-vec huggingface_hub httpx
```
(Skip `llama-cpp-python`. It is only needed to run the real model, and the app falls back to `MockLLM`.)

Then add the test dependency to `requirements.txt`, directly under `cryptography`:
```
cryptography
httpx  # test-only: required by fastapi.testclient
```

- [ ] **Step 2: Record the pre-existing suite state**

Run: `.venv/Scripts/python -m unittest discover -s tests -v`
Expected: all existing tests pass. If any fail before you change anything, note which ones and don't count them against later tasks.

- [ ] **Step 3: Write the shared test base class**

Create `tests/api_case.py`:
```python
"""Shared base class for HTTP-level tests: every test gets a fresh database folder."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import api
from core import config

PASSWORD = "correct-horse"


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
```

- [ ] **Step 4: Write the failing startup test**

Create `tests/test_auth.py`:
```python
from datetime import timedelta
from unittest import mock

from core import auth as auth_core
from core.storage import connect
from tests.api_case import PASSWORD, ApiTestCase


class AppStartupTests(ApiTestCase):
    def test_health_is_open_and_database_lives_in_configured_folder(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue((self.data_dir / "app.db").is_file())
```
(The `auth_core`, `connect`, `timedelta`, `mock`, and `PASSWORD` imports are used by tests added in later tasks. Leave them.)

Temporarily comment out the `from core import auth as auth_core` line, because `core/auth.py` doesn't exist until Task 2. Uncomment it in Task 2, Step 1.

- [ ] **Step 5: Run it to verify it fails**

Run: `.venv/Scripts/python -m unittest tests.test_auth -v`
Expected: FAIL on `assertTrue(... is_file())`, because migrations still ran at import time against the real user-data folder.

- [ ] **Step 6: Make storage read config at call time**

Replace the whole of `core/storage.py` with:
```python
"""SQLite storage: one file, numbered migrations, optional vector search"""
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from core import config


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    config.ensure_dirs()
    # FastAPI may open a request's connection in one worker thread and use it in
    # another; each connection still serves only one request at a time.
    conn = sqlite3.connect(db_path or config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    """Apply any unapplied NNN_name.sql files in order. Returns names applied."""
    migrations_dir = migrations_dir or config.MIGRATIONS_DIR
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    done = {r["version"] for r in conn.execute("SELECT version FROM schema_version")}
    applied = []
    for f in sorted(migrations_dir.glob("*.sql")):
        m = re.match(r"(\d+)_", f.name)
        if not m:
            continue
        version = int(m.group(1))
        if version in done:
            continue
        with conn:  # one transaction per migration
            conn.executescript(f"BEGIN; {f.read_text()}")
            conn.execute("INSERT INTO schema_version (version, name) VALUES (?, ?)",
                         (version, f.name))
        applied.append(f.name)
    return applied


def enable_vectors(conn: sqlite3.Connection, dim: int) -> None:
    """Load sqlite-vec and create the embeddings table (dim depends on your embedding model)."""
    import sqlite_vec
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors "
        f"USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{dim}])"
    )


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
```

- [ ] **Step 7: Move migration into a lifespan hook**

In `api.py`, add `from contextlib import asynccontextmanager` to the stdlib imports at the top (next to `import secrets`). Then replace this block:
```python
app = FastAPI(title="GitKeepers Local API", version="1.0.0")
auth = [Depends(require_token)]
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
db = connect()
try:
    migrate(db)
finally:
    db.close()
```
with:
```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Migrate on startup, not on import, so tests can point config at a temp folder first.
    db = connect()
    try:
        migrate(db)
    finally:
        db.close()
    yield


app = FastAPI(title="GitKeepers Local API", version="1.0.0", lifespan=lifespan)
auth = [Depends(require_token)]
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `.venv/Scripts/python -m unittest tests.test_auth -v`
Expected: PASS.

Run: `.venv/Scripts/python -m unittest discover -s tests -v`
Expected: same results as Step 2 (`test_records.py` passes its own `migrations` path, so the new optional parameter doesn't affect it).

- [ ] **Step 9: Smoke-check the real server still starts**

Run: `.venv/Scripts/python run.py --port 8765`, then in another shell `curl http://127.0.0.1:8765/health`.
Expected: `{"status":"ok"}`. Stop the server.

---

### Task 2: Users table, password hashing, and signup

**Files:**
- Create: `migrations/003_users_sessions.sql`
- Create: `core/auth.py`
- Create: `routes/auth.py`
- Modify: `api.py` (imports, exception handler, router include)
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `core.storage.get_db`, `ApiTestCase.signup`.
- Produces:
  - `core.auth.AuthError(status_code: int, detail: str)` with `.status_code` and `.detail`
  - `core.auth._now() -> datetime` (UTC; tests patch it) and `core.auth._iso(datetime) -> str`
  - `core.auth.hash_password(password: str) -> str` and `core.auth.verify_password(password: str, stored: str) -> bool`
  - `core.auth.get_user(conn, user_id: str) -> dict | None` (the keys in `USER_COLUMNS`)
  - `core.auth.signup(conn, data: dict) -> dict`, where `data` has `username`, `password`, `full_name`, and optionally `email`
  - `core.auth._conflict(exc: sqlite3.IntegrityError) -> AuthError`
  - `routes.auth.User` (Pydantic response model), `routes.auth.router`, and helper validators `_clean_email`, `_clean_name`

- [ ] **Step 1: Write the failing tests**

Uncomment `from core import auth as auth_core` in `tests/test_auth.py`, then append:
```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m unittest tests.test_auth -v`
Expected: ERROR `ModuleNotFoundError: No module named 'core.auth'`.

- [ ] **Step 3: Write the migration**

Create `migrations/003_users_sessions.sql`:
```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    username        TEXT NOT NULL,
    email           TEXT,
    full_name       TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('admin', 'volunteer')),
    status          TEXT NOT NULL CHECK (status IN ('pending', 'active', 'disabled')),
    failed_logins   INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX idx_users_username ON users(username COLLATE NOCASE);
CREATE UNIQUE INDEX idx_users_email ON users(email COLLATE NOCASE) WHERE email IS NOT NULL;

CREATE TABLE sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    revoked     INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
```

- [ ] **Step 4: Write the core service**

Create `core/auth.py`:
```python
"""Local user accounts, password hashing, and bearer-token sessions.

Everything runs against the device's SQLite database, so login works offline.
Service functions raise AuthError; api.py turns it into an HTTP response.
"""
import base64
import hashlib
import hmac
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone

USER_COLUMNS = "id, username, email, full_name, role, status, created_at, updated_at"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


class AuthError(Exception):
    """A failure the client should see, with the HTTP status to report."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    """Current UTC time. Tests patch this to move the clock."""
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return "scrypt${}${}".format(
        base64.b64encode(salt).decode("ascii"), base64.b64encode(digest).decode("ascii")
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def get_user(conn: sqlite3.Connection, user_id: str) -> dict | None:
    row = conn.execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row is not None else None


def _conflict(exc: sqlite3.IntegrityError) -> AuthError:
    if "email" in str(exc):
        return AuthError(409, "Email already in use")
    return AuthError(409, "Username already taken")


def signup(conn: sqlite3.Connection, data: dict) -> dict:
    """Create an account. The first account on the device becomes an active admin;
    later ones are volunteers waiting for admin approval."""
    user_id = str(uuid.uuid4())
    password_hash = hash_password(data["password"])  # slow, so do it before taking the write lock
    conn.execute("BEGIN IMMEDIATE")  # serialises the "is this the first user?" check
    try:
        is_first = conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        role, status = ("admin", "active") if is_first else ("volunteer", "pending")
        conn.execute(
            "INSERT INTO users (id, username, email, full_name, password_hash, role, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, data["username"], data.get("email"), data["full_name"], password_hash, role, status),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise _conflict(exc) from exc
    except BaseException:
        conn.rollback()
        raise
    return get_user(conn, user_id)
```

- [ ] **Step 5: Write the signup route**

Create `routes/auth.py`:
```python
"""Versioned HTTP endpoints for signup, login, and the signed-in user's own profile."""
import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator

from core.auth import signup
from core.storage import get_db

router = APIRouter()

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _clean_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _EMAIL.fullmatch(value):
        raise ValueError("Invalid email address")
    return value


def _clean_name(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("full_name must not be blank")
    return value


class User(BaseModel):
    id: str
    username: str
    email: str | None
    full_name: str
    role: Literal["admin", "volunteer"]
    status: Literal["pending", "active", "disabled"]
    created_at: str
    updated_at: str


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return _clean_email(value)


@router.post(
    "/auth/signup",
    response_model=User,
    status_code=status.HTTP_201_CREATED,
    operation_id="signup",
)
def signup_endpoint(data: SignupRequest, db: sqlite3.Connection = Depends(get_db)):
    return signup(db, data.model_dump())
```

- [ ] **Step 6: Wire it into `api.py`**

Change the existing responses import to `from fastapi.responses import JSONResponse, StreamingResponse`, and add these imports next to the existing `from routes.records import ...`:
```python
from core.auth import AuthError
from routes.auth import router as auth_router
```
Directly after the existing `app.include_router(records_router, ...)` line, add:
```python
app.include_router(auth_router, prefix="/api/v1", dependencies=auth, tags=["auth"])


@app.exception_handler(AuthError)
async def auth_error_handler(_request, exc: AuthError):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest tests.test_auth -v`
Expected: all `SignupTests` and `AppStartupTests` PASS. If `test_duplicate_email_is_rejected_case_insensitively` reports `"Username already taken"`, print `str(exc)` in `_conflict`. SQLite should report `UNIQUE constraint failed: users.email`. Adjust the substring check only if the message differs.

---

### Task 3: Login, sessions, `current_user`, `/auth/me`, logout

**Files:**
- Modify: `core/auth.py` (append)
- Modify: `routes/auth.py` (imports + append)
- Test: `tests/test_auth.py` (append)

**Interfaces:**
- Consumes: `hash_password`, `verify_password`, `get_user`, `_now`, `_iso`, `AuthError` from Task 2.
- Produces:
  - `core.auth.AuthContext` (frozen dataclass: `user: dict`, `token_hash: str`)
  - `core.auth.login(conn, login_name: str, password: str) -> dict`, returning `{"token", "expires_at", "user"}`
  - `core.auth.authenticate(conn, token: str) -> AuthContext`
  - `core.auth.logout(conn, token_hash: str) -> None`
  - `core.auth.current_user(authorization: str | None = Header, conn = Depends(get_db)) -> AuthContext`, the FastAPI dependency
  - Constants `SESSION_TTL`, `SESSION_REFRESH_INTERVAL`, `MAX_FAILED_LOGINS`, `LOCKOUT`, `INVALID_LOGIN`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth.py`:
```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m unittest tests.test_auth -v`
Expected: the new `LoginTests` and `SessionTests` FAIL with 404/405, because the endpoints don't exist yet.

- [ ] **Step 3: Implement login, sessions, and the dependency**

In `core/auth.py`, extend the imports to:
```python
import base64
import hashlib
import hmac
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header

from core.storage import get_db
```
Add these constants under `_SCRYPT`:
```python
SESSION_TTL = timedelta(days=7)
SESSION_REFRESH_INTERVAL = timedelta(hours=1)
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=5)
INVALID_LOGIN = "Invalid username or password"
```
Append to the end of the file:
```python
# Checked against when the login name is unknown, so both failure paths take the same time.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


@dataclass(frozen=True)
class AuthContext:
    """The signed-in user plus the hash of the token they presented."""
    user: dict
    token_hash: str


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def login(conn: sqlite3.Connection, login_name: str, password: str) -> dict:
    """Check credentials (username or email) and open a new session."""
    row = conn.execute(
        "SELECT id, password_hash, status, failed_logins, locked_until FROM users "
        "WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE",
        (login_name, login_name),
    ).fetchone()
    now = _now()
    if row is None:
        verify_password(password, _DUMMY_HASH)
        raise AuthError(401, INVALID_LOGIN)
    if row["locked_until"] and datetime.fromisoformat(row["locked_until"]) > now:
        raise AuthError(423, "Account temporarily locked")
    if not verify_password(password, row["password_hash"]):
        failures = row["failed_logins"] + 1
        locked_until = _iso(now + LOCKOUT) if failures >= MAX_FAILED_LOGINS else None
        with conn:
            conn.execute(
                "UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                (0 if locked_until else failures, locked_until, row["id"]),
            )
        raise AuthError(401, INVALID_LOGIN)
    # Status is only revealed to someone who knows the password.
    if row["status"] == "pending":
        raise AuthError(403, "Account awaiting admin approval")
    if row["status"] == "disabled":
        raise AuthError(403, "Account disabled")
    token = secrets.token_urlsafe(32)
    expires_at = _iso(now + SESSION_TTL)
    with conn:
        conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (row["id"],))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_token_hash(token), row["id"], _iso(now), expires_at),
        )
    return {"token": token, "expires_at": expires_at, "user": get_user(conn, row["id"])}


def authenticate(conn: sqlite3.Connection, token: str) -> AuthContext:
    """Resolve a bearer token to its active user, sliding the session expiry forward."""
    token_hash = _token_hash(token)
    row = conn.execute(
        "SELECT s.expires_at, s.user_id FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.revoked = 0 AND u.status = 'active'",
        (token_hash,),
    ).fetchone()
    now = _now()
    if row is None:
        raise AuthError(401, "Not authenticated")
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at <= now:
        raise AuthError(401, "Not authenticated")
    # Extended at most once per SESSION_REFRESH_INTERVAL to avoid a write on every request.
    if expires_at - now < SESSION_TTL - SESSION_REFRESH_INTERVAL:
        with conn:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE token_hash = ?",
                (_iso(now + SESSION_TTL), token_hash),
            )
    return AuthContext(user=get_user(conn, row["user_id"]), token_hash=token_hash)


def logout(conn: sqlite3.Connection, token_hash: str) -> None:
    with conn:
        conn.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (token_hash,))


def current_user(
    authorization: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> AuthContext:
    """FastAPI dependency: requires `Authorization: Bearer <token>` for an active user."""
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise AuthError(401, "Not authenticated")
    return authenticate(conn, token)
```

- [ ] **Step 4: Add the routes**

In `routes/auth.py`, change the imports to:
```python
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, field_validator

from core.auth import AuthContext, current_user, login, logout, signup
from core.storage import get_db
```
Append:
```python
class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=254, description="Username or email")
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    user: User


@router.post("/auth/login", response_model=LoginResponse, operation_id="login")
def login_endpoint(data: LoginRequest, db: sqlite3.Connection = Depends(get_db)):
    return login(db, data.login.strip(), data.password)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="logout")
def logout_endpoint(
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    logout(db, auth.token_hash)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/auth/me", response_model=User, operation_id="getCurrentUser")
def me(auth: AuthContext = Depends(current_user)):
    return auth.user
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest tests.test_auth -v`
Expected: all tests PASS.

---

### Task 4: Own profile and password change

**Files:**
- Modify: `core/auth.py` (append)
- Modify: `routes/auth.py` (imports + append)
- Test: `tests/test_auth.py` (append)

**Interfaces:**
- Consumes: `AuthContext`, `current_user`, `_conflict`, `hash_password`, `verify_password`, `get_user`.
- Produces:
  - `core.auth.revoke_sessions(conn, user_id: str, keep_token_hash: str | None = None) -> None`. Must be called inside an open transaction.
  - `core.auth._set_password(conn, user_id: str, new_password: str, keep_token_hash: str | None = None) -> None`
  - `core.auth.update_profile(conn, user_id: str, changes: dict) -> dict`
  - `core.auth.change_password(conn, auth: AuthContext, current_password: str, new_password: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth.py`:
```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m unittest tests.test_auth.ProfileTests -v`
Expected: FAIL with 404/405 (no `/me` routes yet).

- [ ] **Step 3: Implement the service functions**

Append to `core/auth.py`:
```python
def revoke_sessions(conn: sqlite3.Connection, user_id: str, keep_token_hash: str | None = None) -> None:
    """Revoke a user's sessions, optionally sparing one. Call inside an open transaction."""
    conn.execute(
        "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND token_hash IS NOT ?",
        (user_id, keep_token_hash),
    )


def _set_password(
    conn: sqlite3.Connection, user_id: str, new_password: str, keep_token_hash: str | None = None
) -> None:
    password_hash = hash_password(new_password)
    with conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, failed_logins = 0, locked_until = NULL, "
            "updated_at = datetime('now') WHERE id = ?",
            (password_hash, user_id),
        )
        revoke_sessions(conn, user_id, keep_token_hash)


def update_profile(conn: sqlite3.Connection, user_id: str, changes: dict) -> dict:
    """Apply self-service profile edits. Only full_name and email are editable here."""
    fields = {name: value for name, value in changes.items() if name in ("full_name", "email")}
    if fields:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        try:
            with conn:
                conn.execute(
                    f"UPDATE users SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                    (*fields.values(), user_id),
                )
        except sqlite3.IntegrityError as exc:
            raise _conflict(exc) from exc
    return get_user(conn, user_id)


def change_password(
    conn: sqlite3.Connection, auth: AuthContext, current_password: str, new_password: str
) -> None:
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (auth.user["id"],)).fetchone()
    if not verify_password(current_password, row["password_hash"]):
        raise AuthError(400, "Current password is incorrect")
    _set_password(conn, auth.user["id"], new_password, keep_token_hash=auth.token_hash)
```

- [ ] **Step 4: Add the routes**

In `routes/auth.py`, change the core import to:
```python
from core.auth import AuthContext, change_password, current_user, login, logout, signup, update_profile
```
Append:
```python
class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)

    # Validators only run on fields the client actually sent, so omitted fields stay unchanged.
    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        return _clean_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return _clean_email(value)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.patch("/me", response_model=User, operation_id="updateMyProfile")
def update_me(
    data: ProfileUpdate,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    return update_profile(db, auth.user["id"], data.model_dump(exclude_unset=True))


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT, operation_id="changeMyPassword")
def change_my_password(
    data: PasswordChange,
    auth: AuthContext = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    change_password(db, auth, data.current_password, data.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest tests.test_auth -v`
Expected: all tests PASS. If `test_blank_or_null_name_is_rejected` lets `{"full_name": null}` through, check that the validator has no `mode="before"` and that `_clean_name(None)` raises `ValueError`.

---

### Task 5: Admin user management and role guard

**Files:**
- Modify: `core/auth.py` (append)
- Create: `routes/users.py`
- Modify: `api.py` (import + router include)
- Test: `tests/test_auth.py` (append)

**Interfaces:**
- Consumes: `current_user`, `AuthContext`, `get_user`, `revoke_sessions`, `_set_password`, `USER_COLUMNS`, `routes.auth.User`, `ApiTestCase.admin_token` / `active_volunteer`.
- Produces:
  - `core.auth.require_role(*roles: str)`, which returns a dependency that yields `AuthContext`
  - `core.auth.require_admin = require_role("admin")`, a single shared instance so FastAPI caches it per request
  - `core.auth.list_users(conn, status, role, query, limit, offset) -> dict` (page)
  - `core.auth.update_user(conn, user_id: str, changes: dict) -> dict`
  - `core.auth.reset_password(conn, user_id: str, new_password: str) -> None`
  - `routes.users.router`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth.py`:
```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m unittest tests.test_auth.UserAdminTests -v`
Expected: ERRORs, because `active_volunteer`'s PATCH returns 404 (no `/users` routes yet).

- [ ] **Step 3: Implement the service functions and role guard**

Append to `core/auth.py`:
```python
def require_role(*roles: str):
    """Build a dependency that allows only signed-in users holding one of `roles`."""
    def dependency(auth: AuthContext = Depends(current_user)) -> AuthContext:
        if auth.user["role"] not in roles:
            raise AuthError(403, "Insufficient permissions")
        return auth
    return dependency


require_admin = require_role("admin")


def list_users(
    conn: sqlite3.Connection,
    status: str | None,
    role: str | None,
    query: str | None,
    limit: int,
    offset: int,
) -> dict:
    clauses: list[str] = []
    params: list = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if role is not None:
        clauses.append("role = ?")
        params.append(role)
    if query:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append(
            "(username LIKE ? ESCAPE '\\' OR full_name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(f"SELECT count(*) FROM users {where}", params).fetchone()[0]
    items = [
        dict(row) for row in conn.execute(
            f"SELECT {USER_COLUMNS} FROM users {where} "
            "ORDER BY status = 'pending' DESC, username COLLATE NOCASE LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def update_user(conn: sqlite3.Connection, user_id: str, changes: dict) -> dict:
    """Admin change of a user's status and/or role, keeping at least one active admin."""
    fields = {k: v for k, v in changes.items() if k in ("status", "role") and v is not None}
    conn.execute("BEGIN IMMEDIATE")  # the admin count and the update must not interleave
    try:
        target = get_user(conn, user_id)
        if target is None:
            raise AuthError(404, "User not found")
        new_role = fields.get("role", target["role"])
        new_status = fields.get("status", target["status"])
        was_active_admin = target["role"] == "admin" and target["status"] == "active"
        if was_active_admin and (new_role != "admin" or new_status != "active"):
            admins = conn.execute(
                "SELECT count(*) FROM users WHERE role = 'admin' AND status = 'active'"
            ).fetchone()[0]
            if admins <= 1:
                raise AuthError(409, "Cannot remove the last active admin")
        if fields:
            assignments = ", ".join(f"{name} = ?" for name in fields)
            conn.execute(
                f"UPDATE users SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                (*fields.values(), user_id),
            )
        if new_status == "disabled" and target["status"] != "disabled":
            revoke_sessions(conn, user_id)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return get_user(conn, user_id)


def reset_password(conn: sqlite3.Connection, user_id: str, new_password: str) -> None:
    """Admin offline password reset: sets a new password and signs the user out everywhere."""
    if get_user(conn, user_id) is None:
        raise AuthError(404, "User not found")
    _set_password(conn, user_id, new_password)
```

- [ ] **Step 4: Write the admin router**

Create `routes/users.py`:
```python
"""Admin-only endpoints for approving, disabling, and managing user accounts."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from core.auth import AuthError, get_user, list_users, require_admin, reset_password, update_user
from core.storage import get_db
from routes.auth import User

router = APIRouter(dependencies=[Depends(require_admin)])


class UserPage(BaseModel):
    items: list[User]
    total: int
    limit: int
    offset: int


class UserUpdate(BaseModel):
    status: Literal["active", "disabled"] | None = None
    role: Literal["admin", "volunteer"] | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


@router.get("/users", response_model=UserPage, operation_id="listUsers")
def users(
    status_filter: Literal["pending", "active", "disabled"] | None = Query(default=None, alias="status"),
    role: Literal["admin", "volunteer"] | None = None,
    q: str | None = Query(default=None, max_length=120, description="Search username, name, or email"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    return list_users(db, status_filter, role, q.strip() if q else None, limit, offset)


@router.get("/users/{user_id}", response_model=User, operation_id="getUser")
def user_detail(user_id: str, db: sqlite3.Connection = Depends(get_db)):
    user = get_user(db, user_id)
    if user is None:
        raise AuthError(404, "User not found")
    return user


@router.patch("/users/{user_id}", response_model=User, operation_id="updateUser")
def change_user(user_id: str, data: UserUpdate, db: sqlite3.Connection = Depends(get_db)):
    return update_user(db, user_id, data.model_dump(exclude_unset=True))


@router.post(
    "/users/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="resetUserPassword",
)
def reset_user_password(user_id: str, data: PasswordReset, db: sqlite3.Connection = Depends(get_db)):
    reset_password(db, user_id, data.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: Mount it**

In `api.py`, add `from routes.users import router as users_router` next to the other router imports. Directly after the `auth_router` include, add:
```python
app.include_router(users_router, prefix="/api/v1", dependencies=auth, tags=["users"])
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m unittest tests.test_auth -v`
Expected: all tests PASS.

---

### Task 6: Require sign-in on existing endpoints, and docs

**Files:**
- Modify: `api.py` (records include + six chat/conversation decorators)
- Modify: `README.md` (Frontend API section)
- Test: `tests/test_auth.py` (append)

**Interfaces:**
- Consumes: `core.auth.current_user`, `ApiTestCase.admin_token`.
- Produces: `api.signed_in` (dependency list `[Depends(require_token), Depends(current_user)]`) for future feature routers to reuse.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth.py`:
```python
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
```
And add `from core import config as api_config` to the imports at the top of the file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m unittest tests.test_auth.ProtectedRouteTests -v`
Expected: `test_records_require_a_signed_in_user` and `test_conversations_and_chat_require_a_signed_in_user` FAIL (200 instead of 401). The other two PASS.

- [ ] **Step 3: Add the user requirement**

In `api.py`, change the auth import to `from core.auth import AuthError, current_user`. Under the line `auth = [Depends(require_token)]`, add:
```python
signed_in = [*auth, Depends(current_user)]  # shell token + an active user session
```
Change the records include to:
```python
app.include_router(records_router, prefix="/api/v1", dependencies=signed_in, tags=["records"])
```
Then, on exactly these six decorators, change `dependencies=auth` to `dependencies=signed_in`:
- `@app.get("/api/v1/conversations", ...)`
- `@app.get("/conversations", ...)`
- `@app.get("/api/v1/conversations/{cid}/messages", ...)`
- `@app.get("/conversations/{cid}/messages", ...)`
- `@app.post("/api/v1/chat", ...)`
- `@app.post("/chat", ...)`

Leave the `auth_router` and `users_router` includes on `dependencies=auth`. The users router already adds `require_admin` itself, and signup/login must work without a session.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python -m unittest discover -s tests -v`
Expected: every test PASSes, including the pre-existing `test_records`, `test_extraction`, and `test_pseudonymize` (or the same pre-existing failures recorded in Task 1, Step 2).

- [ ] **Step 5: Document the API**

In `README.md`, insert this directly above the line `Household and patient records:` in the "Frontend API" section:
````markdown
Authentication and accounts (accounts live on the device, so login works offline):

| Method | Endpoint | Who | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/auth/signup` | anyone | Create an account. The first account on a device becomes an active admin; later ones are pending volunteers until an admin approves them |
| `POST` | `/api/v1/auth/login` | anyone | `{ "login": "<username or email>", "password": "..." }` → `{ token, expires_at, user }` |
| `POST` | `/api/v1/auth/logout` | signed in | Revoke the current session |
| `GET` | `/api/v1/auth/me` | signed in | The current user |
| `PATCH` | `/api/v1/me` | signed in | Update own `full_name` / `email` |
| `POST` | `/api/v1/me/password` | signed in | `{ current_password, new_password }`; signs out other sessions |
| `GET` | `/api/v1/users?status=&role=&q=&limit=&offset=` | admin | List accounts, pending first |
| `GET` | `/api/v1/users/{user_id}` | admin | Get one account |
| `PATCH` | `/api/v1/users/{user_id}` | admin | `{ "status": "active" \| "disabled", "role": "admin" \| "volunteer" }` (approve = `active`) |
| `POST` | `/api/v1/users/{user_id}/password` | admin | Offline password reset; signs the user out everywhere |

Every other `/api/v1` endpoint requires `Authorization: Bearer <token>` from login.
Sessions last 7 days and are extended while in use. Five wrong passwords lock an account
for 5 minutes. Errors use `{ "detail": "<message>" }`, which is safe to show to users.

````
In the "Run Unit Tests" section, add above the code block:
```markdown
Tests need `httpx` (listed in `requirements.txt`); `llama-cpp-python` is not required to run them.
```

- [ ] **Step 6: Final check**

Run: `.venv/Scripts/python -m unittest discover -s tests -v`
Expected: all PASS. Then run `.venv/Scripts/python run.py --port 8765`, open `http://127.0.0.1:8765/docs`, and confirm the **auth** and **users** groups appear. Stop the server. Do not commit. Report the changed files to the user.
