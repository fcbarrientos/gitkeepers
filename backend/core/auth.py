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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header

from core.errors import ApiError
from core.storage import get_db

USER_COLUMNS = "id, username, email, full_name, role, status, created_at, updated_at"
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
SESSION_TTL = timedelta(days=7)
SESSION_REFRESH_INTERVAL = timedelta(hours=1)
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=5)
INVALID_LOGIN = "Invalid username or password"


class AuthError(ApiError):
    """An authentication or authorization failure."""


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
    try:
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:  # corrupted stored hash: treat as a failed check, not a crash
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return hmac.compare_digest(digest, expected)


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
        with conn:
            # Increment in SQL, not from the row read above, so parallel attempts can't lose counts.
            failures = conn.execute(
                "UPDATE users SET failed_logins = failed_logins + 1 WHERE id = ? RETURNING failed_logins",
                (row["id"],),
            ).fetchone()[0]
            if failures >= MAX_FAILED_LOGINS:
                conn.execute(
                    "UPDATE users SET failed_logins = 0, locked_until = ? WHERE id = ?",
                    (_iso(now + LOCKOUT), row["id"]),
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
        # Housekeeping: drop this user's dead sessions so the table doesn't grow forever.
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND (revoked = 1 OR expires_at <= ?)",
            (row["id"], _iso(now)),
        )
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
        # "!" escapes LIKE wildcards so "%" and "_" in the search are matched literally.
        pattern = "%" + query.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        clauses.append(
            "(username LIKE ? ESCAPE '!' OR full_name LIKE ? ESCAPE '!' OR email LIKE ? ESCAPE '!')"
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
