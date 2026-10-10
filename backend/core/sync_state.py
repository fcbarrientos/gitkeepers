"""What still has to reach the RHU, and the manual transfer files that carry it.

A record's sync state is derived from the transfer files that included it at its current
version (`updated_at`): synced once the RHU acknowledged such a file, awaiting while that file
is unacknowledged, otherwise pending. Editing a record after export makes it pending again.
"""
import hashlib
import hmac
import json
import sqlite3
import uuid

from core.errors import ApiError
from core.pseudonymize import Pseudonymizer
from core.sync import create_sync_bundle, derive_key

RECEIPT_FORMAT = "gitkeepers-receipt-v1"
# Typed free text can hold anything (names, places, family details), so the whole value goes
# into the encrypted identity envelope and the payload only carries a token.
FREE_TEXT = ("reason", "facility", "notes", "note")
# For counting, only ids and versions are read.
COUNT_SOURCES = {
    "household": "SELECT id, updated_at FROM households",
    "patient": "SELECT id, updated_at FROM patients",
    "visit": "SELECT id, updated_at FROM visits WHERE status = 'final'",
    "follow_up": "SELECT id, updated_at FROM follow_ups",
    "referral": "SELECT id, updated_at FROM referrals",
    "supply_item": "SELECT id, updated_at FROM supply_items",
    "supply_movement": "SELECT id, updated_at FROM supply_movements",
}
# Column aliases matter: core.pseudonymize masks values by key (full_name, contact_number,
# barangay, sitio, address, note/notes), so identifying columns use those names.
RECORD_SOURCES = {
    "household": "SELECT id, barangay, sitio, address_line AS address, contact_number, created_at, updated_at "
                 "FROM households",
    "patient": "SELECT id, household_id, full_name, birth_date, sex, relationship_to_head, contact_number, "
               "is_household_head, created_at, updated_at FROM patients",
    "visit": "SELECT id, patient_id, form_type, visit_date, values_json, sources_json, note, finalized_at, "
             "created_at, updated_at FROM visits WHERE status = 'final'",
    "follow_up": "SELECT id, patient_id, source_visit_id, form_type, due_date, reason, status, completed_visit_id, "
                 "completed_at, created_at, updated_at FROM follow_ups",
    "referral": "SELECT id, patient_id, flag_id, facility, reason, urgency, notes, created_at, updated_at "
                "FROM referrals",
    "supply_item": "SELECT id, name AS item_name, unit, low_stock_threshold, target_level, active, created_at, "
                   "updated_at FROM supply_items",
    "supply_movement": "SELECT id, item_id, kind, quantity, movement_date, note, created_at, updated_at "
                       "FROM supply_movements",
}
_IN_BUNDLE = (
    "EXISTS (SELECT 1 FROM sync_bundle_records r JOIN sync_bundles b ON b.id = r.bundle_id "
    "WHERE r.record_type = ? AND r.record_id = t.id AND r.record_updated_at = t.updated_at "
    "AND b.acknowledged_at IS {})"
)


def get_setting(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def set_setting(conn, key: str, value: str) -> None:
    with conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def station_id(conn) -> str:
    current = get_setting(conn, "station_id")
    if current is None:
        current = f"station-{uuid.uuid4().hex[:8]}"
        set_setting(conn, "station_id", current)
    return current


def _with_state(source: str) -> str:
    return (f"SELECT t.*, {_IN_BUNDLE.format('NOT NULL')} AS synced, {_IN_BUNDLE.format('NULL')} AS awaiting "
            f"FROM ({source}) t")


def _rows(conn, record_type: str) -> list[sqlite3.Row]:
    return conn.execute(_with_state(RECORD_SOURCES[record_type]), (record_type, record_type)).fetchall()


def counts(conn) -> dict[str, dict[str, int]]:
    result = {}
    for record_type, source in COUNT_SOURCES.items():
        total, synced, awaiting = conn.execute(
            f"SELECT count(*), COALESCE(sum(synced), 0), COALESCE(sum(awaiting AND NOT synced), 0) "
            f"FROM ({_with_state(source)})", (record_type, record_type)).fetchone()
        result[record_type] = {"pending": total - synced - awaiting, "awaiting": awaiting, "synced": synced}
    return result


def unsynced_count(conn) -> int:
    return sum(c["pending"] + c["awaiting"] for c in counts(conn).values())


def pending_records(conn) -> list[dict]:
    records = []
    for record_type in RECORD_SOURCES:
        for row in _rows(conn, record_type):
            if row["synced"] or row["awaiting"]:
                continue
            data = {key: row[key] for key in row.keys() if key not in ("synced", "awaiting")}
            records.append({"record_type": record_type, "record_id": row["id"], "version": row["updated_at"],
                            "data": data})
    return records


def receipt_signature(passphrase: str, bundle_id: str, record_count: int) -> str:
    key = derive_key(passphrase, salt=b"gitkeepers-receipt-salt")
    return hmac.new(key, f"{bundle_id}:{record_count}".encode(), hashlib.sha256).hexdigest()


def make_receipt(bundle: dict, passphrase: str) -> dict:
    """What the RHU sends back after storing a transfer file (see scripts/rhu_receipt.py)."""
    return {"format": RECEIPT_FORMAT, "bundle_id": bundle["bundle_id"], "station_id": bundle["station_id"],
            "record_count": bundle["record_count"],
            "signature": receipt_signature(passphrase, bundle["bundle_id"], bundle["record_count"])}


def _pseudonymizer(passphrase: str, station: str) -> Pseudonymizer:
    """Pseudonyms keyed by the RHU passphrase, so nobody holding only the file can recompute them."""
    key = derive_key(passphrase, salt=b"gitkeepers-pseudonym-salt")
    return Pseudonymizer(salt=hmac.new(key, station.encode(), hashlib.sha256).hexdigest())


def open_bundle_count(conn) -> int:
    return conn.execute("SELECT count(*) FROM sync_bundles WHERE acknowledged_at IS NULL").fetchone()[0]


def set_passphrase(conn, passphrase: str) -> None:
    if open_bundle_count(conn):
        raise ApiError(409, "Cancel or finish the transfer files waiting for a receipt before changing the passphrase")
    set_setting(conn, "sync_passphrase", passphrase)


def cancel_bundle(conn, bundle_id: str) -> bool | None:
    """Void an unacknowledged transfer file so its records are pending again. None if unknown."""
    row = conn.execute("SELECT acknowledged_at FROM sync_bundles WHERE id = ?", (bundle_id,)).fetchone()
    if row is None:
        return None
    if row["acknowledged_at"] is not None:
        raise ApiError(409, "The RHU already acknowledged this transfer file")
    with conn:
        conn.execute("DELETE FROM sync_bundle_records WHERE bundle_id = ?", (bundle_id,))
        conn.execute("DELETE FROM sync_bundles WHERE id = ? AND acknowledged_at IS NULL", (bundle_id,))
    return True


def create_bundle(conn, user_id: str) -> dict:
    passphrase = get_setting(conn, "sync_passphrase")
    if not passphrase:
        raise ApiError(422, ["passphrase: set the RHU passphrase in Sync settings first"])
    station = station_id(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        records = pending_records(conn)
        if not records:
            raise ApiError(409, "Nothing to transfer: every record is synced or waiting for an RHU receipt")
        bundle_id = str(uuid.uuid4())
        pseudonymizer = _pseudonymizer(passphrase, station)
        for record in records:
            for key in FREE_TEXT:
                if record["data"].get(key):
                    record["data"][key] = pseudonymizer.get_or_create("TEXT", str(record["data"][key]))
        bundle = create_sync_bundle(records, station, passphrase, pseudonymizer)
        bundle["bundle_id"] = bundle_id
        conn.execute("INSERT INTO sync_bundles (id, record_count, bundle_json, created_by) VALUES (?, ?, ?, ?)",
                     (bundle_id, len(records), json.dumps(bundle, ensure_ascii=False), user_id))
        conn.executemany(
            "INSERT INTO sync_bundle_records (bundle_id, record_type, record_id, record_updated_at) VALUES (?, ?, ?, ?)",
            [(bundle_id, r["record_type"], r["record_id"], r["version"]) for r in records])
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return bundle


BUNDLE_SELECT = (
    "SELECT b.id, b.record_count, b.created_at, b.acknowledged_at, u.full_name AS created_by_name "
    "FROM sync_bundles b JOIN users u ON u.id = b.created_by"
)


def list_bundles(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(f"{BUNDLE_SELECT} ORDER BY b.created_at DESC, b.rowid DESC LIMIT 50")]


def bundle_file(conn, bundle_id: str) -> dict | None:
    row = conn.execute("SELECT bundle_json FROM sync_bundles WHERE id = ?", (bundle_id,)).fetchone()
    return json.loads(row["bundle_json"]) if row is not None else None


def accept_receipt(conn, receipt: dict) -> dict:
    if receipt.get("format") != RECEIPT_FORMAT:
        raise ApiError(422, ["format: this is not a GitKeepers RHU receipt"])
    row = conn.execute("SELECT id, record_count, acknowledged_at FROM sync_bundles WHERE id = ?",
                       (str(receipt.get("bundle_id")),)).fetchone()
    if row is None:
        raise ApiError(422, ["bundle_id: no transfer file with this ID was made on this device"])
    if receipt.get("record_count") != row["record_count"]:
        raise ApiError(422, ["record_count: does not match the transfer file"])
    passphrase = get_setting(conn, "sync_passphrase") or ""
    expected = receipt_signature(passphrase, row["id"], row["record_count"])
    if not passphrase or not hmac.compare_digest(str(receipt.get("signature", "")), expected):
        raise ApiError(422, ["signature: this receipt was not signed with this device's RHU passphrase"])
    if row["acknowledged_at"] is None:
        with conn:
            conn.execute("UPDATE sync_bundles SET acknowledged_at = datetime('now') WHERE id = ?", (row["id"],))
            # Status only: updated_at stays, so a sent referral does not need transferring again.
            conn.execute(
                "UPDATE referrals SET status = 'sent' WHERE status = 'issued' AND id IN "
                "(SELECT record_id FROM sync_bundle_records WHERE bundle_id = ? AND record_type = 'referral')",
                (row["id"],))
    return dict(conn.execute(f"{BUNDLE_SELECT} WHERE b.id = ?", (row["id"],)).fetchone())


def status(conn) -> dict:
    return {
        "station_id": station_id(conn),
        "passphrase_set": bool(get_setting(conn, "sync_passphrase")),
        "records": counts(conn),
        "last_acknowledged_at": conn.execute("SELECT max(acknowledged_at) FROM sync_bundles").fetchone()[0],
        "open_bundles": open_bundle_count(conn),
    }
