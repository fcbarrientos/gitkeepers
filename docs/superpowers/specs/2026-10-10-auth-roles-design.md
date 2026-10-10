# Auth, Roles & Profile — Design

**Sub-project 1 of 7** for the GitKeepers offline-first rural healthcare system.
Covers FR-01 (Login and Signup), FR-17 (User Profile and Role Management), and the
authentication half of FR-15 / AC-14 (access control). Acceptance: AC-01, AC-14 (auth
items), AC-15.

## Context

The backend is a local FastAPI + SQLite service bound to `127.0.0.1` on each device.
It currently has no per-user identity: the only guard is an optional shared
`X-API-Token` header that the desktop shell sets. Every later sub-project (visits,
referrals, supplies, reports, sync, frontend) needs to know *who* is acting and *what
role* they hold, so auth comes first.

Constraints:

- **Offline:** login must work with no internet. Accounts live in the device's SQLite.
- **No new dependencies:** use the Python standard library for hashing and tokens.
- **Follow existing patterns:** `/api/v1` routers in `routes/`, service functions in
  `core/`, numbered SQL migrations, `unittest` tests.

## Decisions

| Topic | Decision |
|---|---|
| Session mechanism | Opaque random bearer tokens; only the SHA-256 hash is stored in SQLite. Revocable instantly. |
| Password hashing | `hashlib.scrypt` (n=2**14, r=8, p=1, 32-byte key), 16-byte per-user random salt, constant-time comparison. |
| Roles | `admin`, `volunteer`. |
| Account creation | Self-signup with admin approval. The first account created on a device becomes an active admin; later signups are pending volunteers. |
| Shared `X-API-Token` | Kept unchanged as an outer, shell-level guard. User auth is layered inside it. |

## Data model — `migrations/003_users_sessions.sql`

```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,                 -- uuid4
    username        TEXT NOT NULL,
    email           TEXT,
    full_name       TEXT NOT NULL,
    password_hash   TEXT NOT NULL,                    -- "scrypt$<salt_b64>$<hash_b64>"
    role            TEXT NOT NULL CHECK (role IN ('admin', 'volunteer')),
    status          TEXT NOT NULL CHECK (status IN ('pending', 'active', 'disabled')),
    failed_logins   INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,                             -- ISO-8601 UTC, NULL when not locked
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX idx_users_username ON users(username COLLATE NOCASE);
CREATE UNIQUE INDEX idx_users_email ON users(email COLLATE NOCASE) WHERE email IS NOT NULL;

CREATE TABLE sessions (
    token_hash  TEXT PRIMARY KEY,                     -- sha256 hex of the bearer token
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    revoked     INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
```

## Rules

1. **Signup.** Username 3–40 characters (`[A-Za-z0-9._-]`), password 8–128 characters,
   full_name 1–200 characters, email optional (basic format check). The username must be
   unique, compared case-insensitively.
   - If `users` is empty → the new user is `role=admin, status=active`. The check and
     insert run in one transaction (`BEGIN IMMEDIATE`) so two simultaneous first signups
     cannot both become admin.
   - Otherwise → `role=volunteer, status=pending`. Signup never returns a session token.
2. **Login.** The user can log in by username or email.
   - An unknown user or wrong password returns the same `401 "Invalid username or password"`.
   - Five consecutive failures set `locked_until = now + 5 min`. While the account is
     locked, login returns `423 "Account temporarily locked"` without checking the
     password. A successful login resets the counter.
   - Status `pending` → `403 "Account awaiting admin approval"`. Status `disabled` →
     `403 "Account disabled"`. Both checks happen only after the password verifies, so
     account state is not exposed to someone who doesn't know the password.
   - On success, the endpoint creates a session that expires 7 days later and returns
     `{ token, expires_at, user }`.
3. **Session validation** (`current_user` dependency): it reads `Authorization: Bearer <token>`,
   hashes the token, and looks up a non-revoked, unexpired session whose user is `active`.
   If any of that fails → `401`. A valid request extends `expires_at` to now + 7 days
   (sliding expiry), but writes this at most once per hour per session.
4. **Logout** revokes the current session.
5. **Disabling a user or changing their password** revokes all of that user's sessions.
   A user who changes their own password keeps their current session and loses all others.
6. **Last-admin protection.** Any change that would leave zero `active` admins
   (demoting, disabling) returns `409`.
7. **Roles.** `require_role("admin")` returns `403` for an authenticated user who isn't an admin.

## API

All endpoints are under `/api/v1`. They still pass the existing `X-API-Token` check
when `API_TOKEN` is set. The `User` response is
`{ id, username, email, full_name, role, status, created_at, updated_at }` and never
contains the password hash or lockout fields.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/signup` | public | Create an account (rule 1). Returns `201 User`. |
| POST | `/auth/login` | public | `{ login, password }` → `{ token, expires_at, user }`. |
| POST | `/auth/logout` | user | Revoke the current session. Returns `204`. |
| GET | `/auth/me` | user | The current `User`. |
| PATCH | `/me` | user | Update `full_name`, `email`. Role and status are not editable here. |
| POST | `/me/password` | user | `{ current_password, new_password }`. Returns `204`. |
| GET | `/users?status=&role=&q=&limit=&offset=` | admin | Paged list, same shape as other list endpoints. |
| GET | `/users/{id}` | admin | A single `User`. |
| PATCH | `/users/{id}` | admin | `{ status?, role? }`. Approve = `status: active`. |
| POST | `/users/{id}/password` | admin | `{ new_password }`. Offline password reset. Returns `204`. |

## Code layout

```
backend/
  core/auth.py            hashing, token create/verify, signup/login/session service
                          functions, current_user + require_role dependencies
  routes/auth.py          /auth/* and /me endpoints + Pydantic schemas
  routes/users.py         admin /users endpoints
  migrations/003_users_sessions.sql
  tests/test_auth.py
```

`api.py` wiring:

- Include `auth_router` with the existing shell-token dependency only. Signup and login
  must be reachable without a user session.
- Include `users_router` with `require_role("admin")`.
- Add `Depends(current_user)` to the records router and to the chat/conversation
  endpoints, in addition to the existing shell-token check.
- `/health` stays open.

## Error handling

Errors use FastAPI's standard `{"detail": "..."}` body, so the frontend can show the
message directly as the validation or error text required by AC-01. Pydantic validation
errors return `422` as they already do. Unexpected database integrity errors (such as a
duplicate username race) map to `409 "Username already taken"`.

## Testing — `tests/test_auth.py`

Each test uses a fresh temporary `APP_DATA_DIR` and FastAPI's `TestClient`. Cases:

- The first signup becomes an active admin; the second becomes a pending volunteer.
- A duplicate username with different case → 409.
- A weak password or invalid username → 422.
- Logging in as a pending user → 403; after an admin approves, login succeeds.
- A wrong password → 401 with the same message as an unknown user.
- Five failures → 423 lock, even with the correct password during the lock window.
- Logout revokes the token, so the next request returns 401.
- An expired session → 401.
- A volunteer calling `/users` → 403; an admin → 200.
- Demoting or disabling the last active admin → 409.
- Disabling a user revokes their existing sessions.
- `/me/password` with a wrong current password → 400; on success, other sessions are revoked.
- `/api/v1/households` without a bearer token → 401; with one → 200.
- `/health` stays open.

Existing tests in `test_records.py` call `core.records` directly against an in-memory
database, so auth doesn't affect them. They must still pass unchanged.

## Out of scope

- Password reset by email or SMS (impossible offline; an admin resets passwords instead).
- Syncing user accounts across devices or with the RHU (sync sub-project).
- More roles such as midwife or RHU staff; add them when a feature needs them.
- Rate limiting beyond the per-account lockout (the backend binds to localhost only).
- Encrypting the database at rest (the privacy/sync sub-project will cover this).
