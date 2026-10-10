"""Medicine and supply stock. On-hand stock is always the sum of recorded movements."""
import sqlite3
import uuid

from core import clock
from core.errors import ApiError

ITEM_SELECT = (
    "SELECT i.id, i.name, i.unit, i.low_stock_threshold, i.target_level, i.active, i.created_at, i.updated_at, "
    "COALESCE((SELECT sum(m.quantity) FROM supply_movements m WHERE m.item_id = i.id), 0) AS on_hand "
    "FROM supply_items i"
)
MOVEMENT_SELECT = (
    "SELECT m.id, m.item_id, m.kind, m.quantity, m.movement_date, m.note, m.recorded_by, "
    "u.full_name AS recorded_by_name, m.created_at FROM supply_movements m JOIN users u ON u.id = m.recorded_by"
)
EDITABLE = ("name", "unit", "low_stock_threshold", "target_level", "active")


def _item(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["active"] = bool(item["active"])
    item["low"] = item["on_hand"] <= item["low_stock_threshold"]
    return item


def list_items(conn, include_inactive: bool) -> list[dict]:
    where = "" if include_inactive else "WHERE i.active = 1"
    return [_item(r) for r in conn.execute(f"{ITEM_SELECT} {where} ORDER BY i.name COLLATE NOCASE")]


def get_item(conn, item_id: str) -> dict | None:
    row = conn.execute(f"{ITEM_SELECT} WHERE i.id = ?", (item_id,)).fetchone()
    return _item(row) if row is not None else None


def _check_levels(low: int, target: int) -> None:
    if target < low:
        raise ApiError(422, ["target_level: must be at least the low-stock level"])


def create_item(conn, data: dict) -> dict:
    _check_levels(data["low_stock_threshold"], data["target_level"])
    item_id = str(uuid.uuid4())
    try:
        with conn:
            conn.execute(
                "INSERT INTO supply_items (id, name, unit, low_stock_threshold, target_level) VALUES (?, ?, ?, ?, ?)",
                (item_id, data["name"], data["unit"], data["low_stock_threshold"], data["target_level"]))
    except sqlite3.IntegrityError as exc:
        raise ApiError(409, "An item with this name already exists") from exc
    return get_item(conn, item_id)


def update_item(conn, item_id: str, changes: dict) -> dict | None:
    item = get_item(conn, item_id)
    if item is None:
        return None
    fields = {key: changes[key] for key in EDITABLE if changes.get(key) is not None}
    _check_levels(fields.get("low_stock_threshold", item["low_stock_threshold"]),
                  fields.get("target_level", item["target_level"]))
    if fields:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        try:
            with conn:
                conn.execute(f"UPDATE supply_items SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                             (*fields.values(), item_id))
        except sqlite3.IntegrityError as exc:
            raise ApiError(409, "An item with this name already exists") from exc
    return get_item(conn, item_id)


def record_movement(conn, item_id: str, data: dict, user_id: str) -> dict | None:
    item = get_item(conn, item_id)
    if item is None:
        return None
    kind, quantity = data["kind"], data["quantity"]
    if kind == "adjusted":
        if quantity == 0:
            raise ApiError(422, ["quantity: an adjustment cannot be 0"])
        change = quantity
    else:
        if quantity <= 0:
            raise ApiError(422, ["quantity: must be more than 0"])
        change = -quantity if kind == "distributed" else quantity
    if data["movement_date"] > clock.today():
        raise ApiError(422, ["movement_date: cannot be in the future"])
    movement_id = str(uuid.uuid4())
    conn.execute("BEGIN IMMEDIATE")  # read and write the stock level in one step
    try:
        on_hand = conn.execute("SELECT COALESCE(sum(quantity), 0) FROM supply_movements WHERE item_id = ?",
                               (item_id,)).fetchone()[0]
        if on_hand + change < 0:
            raise ApiError(422, [f"quantity: only {on_hand} {item['unit']} in stock"])
        conn.execute(
            "INSERT INTO supply_movements (id, item_id, kind, quantity, movement_date, note, recorded_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (movement_id, item_id, kind, change, data["movement_date"].isoformat(), data.get("note"), user_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return dict(conn.execute(f"{MOVEMENT_SELECT} WHERE m.id = ?", (movement_id,)).fetchone())


def list_movements(conn, item_id: str, limit: int, offset: int) -> dict | None:
    if get_item(conn, item_id) is None:
        return None
    total = conn.execute("SELECT count(*) FROM supply_movements WHERE item_id = ?", (item_id,)).fetchone()[0]
    rows = conn.execute(
        f"{MOVEMENT_SELECT} WHERE m.item_id = ? ORDER BY m.movement_date DESC, m.created_at DESC, m.rowid DESC "
        "LIMIT ? OFFSET ?", (item_id, limit, offset))
    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


def request_list(conn) -> list[dict]:
    return [{**item, "request_quantity": max(item["target_level"] - item["on_hand"], 0)}
            for item in list_items(conn, include_inactive=False) if item["low"]]
