"""SQLite operations for household and patient records."""
import re
import sqlite3
import uuid


def _search_expression(query: str) -> str:
    terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
    return " AND ".join('"' + term.replace('"', '""') + '"*' for term in terms)


def _patient_values(member: dict) -> tuple:
    return (
        str(uuid.uuid4()),
        member["full_name"].strip(),
        member.get("birth_date").isoformat() if member.get("birth_date") else None,
        member.get("sex"),
        member.get("relationship_to_head"),
        member.get("contact_number"),
        int(member.get("is_household_head", False)),
    )


def _insert_patient(conn: sqlite3.Connection, household_id: str, member: dict) -> str:
    patient_id, *values = _patient_values(member)
    conn.execute(
        "INSERT INTO patients "
        "(id, household_id, full_name, birth_date, sex, relationship_to_head, "
        "contact_number, is_household_head) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (patient_id, household_id, *values),
    )
    return patient_id


def get_household(conn: sqlite3.Connection, household_id: str) -> dict | None:
    household = conn.execute(
        "SELECT id, barangay, sitio, address_line, contact_number, created_at, updated_at "
        "FROM households WHERE id = ?",
        (household_id,),
    ).fetchone()
    if household is None:
        return None
    result = dict(household)
    result["members"] = [
        dict(row) for row in conn.execute(
            "SELECT id, household_id, full_name, birth_date, sex, relationship_to_head, "
            "contact_number, is_household_head, created_at, updated_at "
            "FROM patients WHERE household_id = ? ORDER BY is_household_head DESC, full_name COLLATE NOCASE",
            (household_id,),
        )
    ]
    return result


def get_patient(conn: sqlite3.Connection, patient_id: str) -> dict | None:
    row = conn.execute(
        "SELECT p.id, p.household_id, p.full_name, p.birth_date, p.sex, "
        "p.relationship_to_head, p.contact_number, p.is_household_head, "
        "p.created_at, p.updated_at, h.barangay, h.sitio "
        "FROM patients p JOIN households h ON h.id = p.household_id WHERE p.id = ?",
        (patient_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def create_household(conn: sqlite3.Connection, data: dict) -> dict:
    household_id = str(uuid.uuid4())
    with conn:
        conn.execute(
            "INSERT INTO households (id, barangay, sitio, address_line, contact_number) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                household_id,
                data["barangay"].strip(),
                data.get("sitio"),
                data.get("address_line"),
                data.get("contact_number"),
            ),
        )
        for member in data.get("members", []):
            _insert_patient(conn, household_id, member)
    return get_household(conn, household_id)


def add_patient(conn: sqlite3.Connection, household_id: str, member: dict) -> dict | None:
    if conn.execute("SELECT 1 FROM households WHERE id = ?", (household_id,)).fetchone() is None:
        return None
    with conn:
        patient_id = _insert_patient(conn, household_id, member)
    return dict(conn.execute(
        "SELECT id, household_id, full_name, birth_date, sex, relationship_to_head, "
        "contact_number, is_household_head, created_at, updated_at "
        "FROM patients WHERE id = ?",
        (patient_id,),
    ).fetchone())


def list_households(
    conn: sqlite3.Connection, query: str | None, limit: int, offset: int
) -> dict:
    params: list = []
    where = ""
    if query is not None:
        expression = _search_expression(query)
        if not expression:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        where = (
            "WHERE h.id IN (SELECT household_id FROM household_search "
            "WHERE household_search MATCH ?) OR h.id IN ("
            "SELECT p.household_id FROM patients p WHERE p.id IN ("
            "SELECT patient_id FROM patient_search WHERE patient_search MATCH ?))"
        )
        params.extend([expression, expression])
    total = conn.execute(
        f"SELECT count(*) FROM households h {where}", params
    ).fetchone()[0]
    items = [
        dict(row) for row in conn.execute(
            "SELECT h.id, h.barangay, h.sitio, h.address_line, h.contact_number, "
            "h.updated_at, count(p.id) AS member_count, "
            "(SELECT head.full_name FROM patients head "
            "WHERE head.household_id = h.id AND head.is_household_head = 1 LIMIT 1) AS head_name "
            f"FROM households h LEFT JOIN patients p ON p.household_id = h.id {where} "
            "GROUP BY h.id ORDER BY h.updated_at DESC, h.id "
            "LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def list_patients(
    conn: sqlite3.Connection,
    query: str | None,
    household_id: str | None,
    limit: int,
    offset: int,
) -> dict:
    clauses = []
    params: list = []
    if household_id is not None:
        clauses.append("p.household_id = ?")
        params.append(household_id)
    if query is not None:
        expression = _search_expression(query)
        if not expression:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        clauses.append(
            "p.id IN (SELECT patient_id FROM patient_search WHERE patient_search MATCH ?)"
        )
        params.append(expression)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(
        f"SELECT count(*) FROM patients p {where}", params
    ).fetchone()[0]
    items = [
        dict(row) for row in conn.execute(
            "SELECT p.id, p.household_id, p.full_name, p.birth_date, p.sex, "
            "p.relationship_to_head, p.contact_number, p.is_household_head, "
            "p.created_at, p.updated_at, h.barangay, h.sitio "
            f"FROM patients p JOIN households h ON h.id = p.household_id {where} "
            "ORDER BY p.full_name COLLATE NOCASE, p.id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}
