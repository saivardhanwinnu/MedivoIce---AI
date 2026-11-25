"""
Local SQLite database setup and appointment helpers for MediVoice AI.

Uses Python's built-in sqlite3 module with zero external dependencies.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Store the database locally at backend/medvoice.db
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "medvoice.db"

SAMPLE_DOCTORS = [
    ("Dr. Ananya", "General Physician"),
    ("Dr. Rahul", "Cardiologist"),
    ("Dr. Priya", "Dermatologist"),
    ("Dr. Kiran", "Orthopedic"),
]

DEFAULT_SLOT_TIMES = ["09:30 AM", "11:00 AM", "02:30 PM", "04:00 PM"]


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection configured with row dicts and foreign keys."""
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _normalize_phone(phone: str) -> str:
    """Keep only digits from a phone number for consistent matching."""
    return "".join(ch for ch in phone if ch.isdigit())


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create the doctors, slots, and appointments tables if they do not exist."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            specialty TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            slot_date TEXT NOT NULL,
            slot_time TEXT NOT NULL,
            is_booked INTEGER NOT NULL DEFAULT 0 CHECK (is_booked IN (0, 1)),
            FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
            UNIQUE (doctor_id, slot_date, slot_time)
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            slot_id INTEGER NOT NULL,
            patient_name TEXT NOT NULL,
            patient_phone TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked', 'cancelled')),
            created_at TEXT NOT NULL,
            FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE,
            FOREIGN KEY (slot_id) REFERENCES slots(id) ON DELETE CASCADE
        );
        """
    )


def _seed_sample_data(conn: sqlite3.Connection) -> None:
    """Insert the 4 sample doctors and future slots if the database is empty."""
    existing_count = conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
    if existing_count > 0:
        return

    today = date.today()
    future_dates = [(today + timedelta(days=offset)).isoformat() for offset in (1, 2, 3)]

    for name, specialty in SAMPLE_DOCTORS:
        cursor = conn.execute(
            "INSERT INTO doctors (name, specialty) VALUES (?, ?)",
            (name, specialty),
        )
        doctor_id = cursor.lastrowid

        for slot_date in future_dates:
            for slot_time in DEFAULT_SLOT_TIMES:
                conn.execute(
                    """
                    INSERT INTO slots (doctor_id, slot_date, slot_time, is_booked)
                    VALUES (?, ?, ?, 0)
                    """,
                    (doctor_id, slot_date, slot_time),
                )


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> Path:
    """Initialize tables and seed sample doctors and future slots."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(path)
    try:
        with conn:
            _create_tables(conn)
            _seed_sample_data(conn)
    finally:
        conn.close()

    return path


def get_all_doctors(db_path: Path | str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Return all doctors ordered by id."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, specialty FROM doctors ORDER BY id ASC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def check_available_slots(
    doctor_query: str | None = None,
    slot_date: str | None = None,
    doctor_id: int | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """
    Return unbooked slots joined with doctor details.

    Optional filters:
    - doctor_query: matches doctor name or specialty (case-insensitive substring)
    - slot_date: exact YYYY-MM-DD date string
    - doctor_id: exact doctor id
    """
    query = """
        SELECT
            s.id AS slot_id,
            s.doctor_id,
            d.name AS doctor_name,
            d.specialty,
            s.slot_date,
            s.slot_time,
            s.is_booked
        FROM slots s
        JOIN doctors d ON d.id = s.doctor_id
        WHERE s.is_booked = 0
    """
    params: list[Any] = []

    if doctor_id is not None:
        query += " AND s.doctor_id = ?"
        params.append(doctor_id)

    if doctor_query:
        like_value = f"%{doctor_query.strip()}%"
        query += " AND (LOWER(d.name) LIKE LOWER(?) OR LOWER(d.specialty) LIKE LOWER(?))"
        params.extend([like_value, like_value])

    if slot_date:
        query += " AND s.slot_date = ?"
        params.append(slot_date.strip())

    query += " ORDER BY s.slot_date ASC, s.id ASC"

    conn = get_connection(db_path)
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def book_appointment(
    slot_id: int,
    patient_name: str,
    patient_phone: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Book an available slot inside an immediate SQLite transaction to prevent double booking.

    Returns a dictionary with `success` (bool), `message` (str), and `appointment` (dict | None).
    """
    clean_name = patient_name.strip()
    clean_phone = patient_phone.strip()
    if not clean_name:
        return {"success": False, "message": "Patient name is required.", "appointment": None}
    if not _normalize_phone(clean_phone):
        return {"success": False, "message": "A valid phone number is required.", "appointment": None}

    conn = get_connection(db_path)
    # Disable implicit autocommit so BEGIN IMMEDIATE gives us an exclusive write lock
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")

        slot = conn.execute(
            """
            SELECT s.id, s.doctor_id, s.slot_date, s.slot_time, s.is_booked, d.name AS doctor_name, d.specialty
            FROM slots s
            JOIN doctors d ON d.id = s.doctor_id
            WHERE s.id = ?
            """,
            (slot_id,),
        ).fetchone()

        if slot is None:
            conn.execute("ROLLBACK")
            return {
                "success": False,
                "message": f"Slot {slot_id} was not found.",
                "appointment": None,
            }

        if slot["is_booked"] == 1:
            conn.execute("ROLLBACK")
            return {
                "success": False,
                "message": (
                    f"Sorry, the {slot['slot_time']} slot on {slot['slot_date']} "
                    f"with {slot['doctor_name']} is already booked."
                ),
                "appointment": None,
            }

        # Guarded update ensures only one transaction can claim this slot
        update_cursor = conn.execute(
            "UPDATE slots SET is_booked = 1 WHERE id = ? AND is_booked = 0",
            (slot_id,),
        )
        if update_cursor.rowcount != 1:
            conn.execute("ROLLBACK")
            return {
                "success": False,
                "message": "Slot could not be booked because it was just taken.",
                "appointment": None,
            }

        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        insert_cursor = conn.execute(
            """
            INSERT INTO appointments (doctor_id, slot_id, patient_name, patient_phone, status, created_at)
            VALUES (?, ?, ?, ?, 'booked', ?)
            """,
            (slot["doctor_id"], slot_id, clean_name, clean_phone, created_at),
        )
        appointment_id = insert_cursor.lastrowid
        conn.execute("COMMIT")

        return {
            "success": True,
            "message": (
                f"Appointment #{appointment_id} booked with {slot['doctor_name']} "
                f"({slot['specialty']}) on {slot['slot_date']} at {slot['slot_time']}."
            ),
            "appointment": {
                "id": appointment_id,
                "doctor_id": slot["doctor_id"],
                "doctor_name": slot["doctor_name"],
                "specialty": slot["specialty"],
                "slot_id": slot_id,
                "slot_date": slot["slot_date"],
                "slot_time": slot["slot_time"],
                "patient_name": clean_name,
                "patient_phone": clean_phone,
                "status": "booked",
                "created_at": created_at,
            },
        }
    except sqlite3.Error as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return {"success": False, "message": f"Database error: {exc}", "appointment": None}
    finally:
        conn.close()


def cancel_appointment(
    appointment_id: int | None = None,
    patient_phone: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Cancel a booked appointment and free its slot in a single transaction.

    Lookup works by `appointment_id` or by `patient_phone` (cancels the latest active
    booking for that phone number if no appointment_id is given).
    """
    if appointment_id is None and not patient_phone:
        return {
            "success": False,
            "message": "Provide either an appointment_id or a patient_phone to cancel.",
            "appointment": None,
        }

    conn = get_connection(db_path)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")

        appointment = None
        if appointment_id is not None:
            appointment = conn.execute(
                """
                SELECT a.*, d.name AS doctor_name, d.specialty, s.slot_date, s.slot_time
                FROM appointments a
                JOIN doctors d ON d.id = a.doctor_id
                JOIN slots s ON s.id = a.slot_id
                WHERE a.id = ?
                """,
                (appointment_id,),
            ).fetchone()
        else:
            target_digits = _normalize_phone(patient_phone or "")
            if not target_digits:
                conn.execute("ROLLBACK")
                return {
                    "success": False,
                    "message": "A valid phone number is required to cancel.",
                    "appointment": None,
                }

            rows = conn.execute(
                """
                SELECT a.*, d.name AS doctor_name, d.specialty, s.slot_date, s.slot_time
                FROM appointments a
                JOIN doctors d ON d.id = a.doctor_id
                JOIN slots s ON s.id = a.slot_id
                WHERE a.status = 'booked'
                ORDER BY a.id DESC
                """
            ).fetchall()
            for row in rows:
                if _normalize_phone(row["patient_phone"]) == target_digits:
                    appointment = row
                    break

        if appointment is None:
            conn.execute("ROLLBACK")
            return {
                "success": False,
                "message": "No matching active appointment was found.",
                "appointment": None,
            }

        if appointment["status"] == "cancelled":
            conn.execute("ROLLBACK")
            return {
                "success": False,
                "message": f"Appointment #{appointment['id']} is already cancelled.",
                "appointment": None,
            }

        # Verify phone matches if both appointment_id and patient_phone were supplied
        if appointment_id is not None and patient_phone:
            if _normalize_phone(appointment["patient_phone"]) != _normalize_phone(patient_phone):
                conn.execute("ROLLBACK")
                return {
                    "success": False,
                    "message": "The phone number does not match this appointment.",
                    "appointment": None,
                }

        conn.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = ?",
            (appointment["id"],),
        )
        conn.execute(
            "UPDATE slots SET is_booked = 0 WHERE id = ?",
            (appointment["slot_id"],),
        )
        conn.execute("COMMIT")

        cancelled_data = dict(appointment)
        cancelled_data["status"] = "cancelled"
        return {
            "success": True,
            "message": (
                f"Appointment #{appointment['id']} with {appointment['doctor_name']} "
                f"on {appointment['slot_date']} at {appointment['slot_time']} has been cancelled."
            ),
            "appointment": cancelled_data,
        }
    except sqlite3.Error as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return {"success": False, "message": f"Database error: {exc}", "appointment": None}
    finally:
        conn.close()


def get_all_appointments(
    status: str | None = None,
    patient_phone: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Return all appointments joined with doctor and slot info, newest first."""
    query = """
        SELECT
            a.id,
            a.doctor_id,
            d.name AS doctor_name,
            d.specialty,
            a.slot_id,
            s.slot_date,
            s.slot_time,
            a.patient_name,
            a.patient_phone,
            a.status,
            a.created_at
        FROM appointments a
        JOIN doctors d ON d.id = a.doctor_id
        JOIN slots s ON s.id = a.slot_id
        WHERE 1 = 1
    """
    params: list[Any] = []

    if status:
        query += " AND a.status = ?"
        params.append(status.strip())

    query += " ORDER BY a.id DESC"

    conn = get_connection(db_path)
    try:
        rows = [dict(row) for row in conn.execute(query, params).fetchall()]
        if patient_phone:
            target_digits = _normalize_phone(patient_phone)
            rows = [r for r in rows if _normalize_phone(r["patient_phone"]) == target_digits]
        return rows
    finally:
        conn.close()


if __name__ == "__main__":
    created_path = init_db()
    doctors = get_all_doctors(created_path)
    available = check_available_slots(db_path=created_path)
    print(f"Database ready at: {created_path}")
    print(f"Seeded doctors: {len(doctors)}")
    print(f"Available slots: {len(available)}")
