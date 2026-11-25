"""
Voice assistant tools and phone confirmation rules for MediVoice AI.

These functions wrap backend/db.py with strict validation and explicit
caller phone-number confirmation checks before booking or cancelling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import db

# Conversation rules shared with the LLM in the voice pipeline
CONVERSATION_RULES = """
You are MediVoice AI, a polite medical clinic appointment assistant.
You can help callers check doctor availability, book an appointment, or cancel an appointment.

STRICT PHONE NUMBER CONFIRMATION RULES:
1. Before booking or cancelling an appointment, ask the caller to speak their phone number.
2. Repeat the full phone number back to the caller DIGIT BY DIGIT (for example: "9, 8, 7, 6, 5, 4, 3, 2, 1, 0").
3. Explicitly ask: "Is that phone number correct?"
4. Wait for the caller to give an explicit "yes" (or clear affirmative confirmation).
5. NEVER assume confirmation and NEVER pass phone_confirmed=True until the caller explicitly confirms the read-back number.
""".strip()


def validate_phone_number(phone: str | None) -> tuple[bool, str, str]:
    """
    Validate a caller phone number.

    Returns (is_valid, normalized_digits, error_message).
    """
    if not phone or not isinstance(phone, str):
        return False, "", "Please provide a valid phone number."

    cleaned = phone.strip()
    if any(ch.isalpha() for ch in cleaned):
        return False, "", "Phone number cannot contain letters. Please provide digits only."

    digits = db._normalize_phone(cleaned)
    if len(digits) < 10 or len(digits) > 15:
        return (
            False,
            digits,
            "Phone number must contain between 10 and 15 digits. Please check and try again.",
        )

    return True, digits, ""


def format_phone_digit_by_digit(phone: str) -> str:
    """Format digits separated by hyphens so the assistant reads every digit clearly."""
    digits = db._normalize_phone(phone)
    return "-".join(digits)


def _doctor_matches(requested_name: str, actual_name: str) -> bool:
    """Check whether a requested doctor name matches the slot's doctor."""
    req = requested_name.strip().lower()
    act = actual_name.strip().lower()
    if not req:
        return False

    # Strip common 'dr.' / 'dr' prefix so "Rahul" matches "Dr. Rahul"
    req_short = req.removeprefix("dr.").removeprefix("dr ").strip()
    act_short = act.removeprefix("dr.").removeprefix("dr ").strip()
    return req == act or req_short == act_short or req_short in act_short


def check_doctor_availability(
    specialty_or_doctor: str | None = None,
    date: str | None = None,
    db_path: Path | str = db.DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Search doctors and available appointment slots using the existing database.

    Returns doctor names, specialties, slot IDs, dates, and times.
    """
    query = specialty_or_doctor.strip() if isinstance(specialty_or_doctor, str) and specialty_or_doctor.strip() else None
    slot_date = date.strip() if isinstance(date, str) and date.strip() else None

    doctors = db.get_all_doctors(db_path=db_path)
    slots = db.check_available_slots(
        doctor_query=query,
        slot_date=slot_date,
        db_path=db_path,
    )

    if not slots:
        return {
            "success": True,
            "message": "No available slots matched your search.",
            "doctors": doctors,
            "available_slots": [],
        }

    formatted_slots = [
        {
            "slot_id": s["slot_id"],
            "doctor_id": s["doctor_id"],
            "doctor_name": s["doctor_name"],
            "specialty": s["specialty"],
            "slot_date": s["slot_date"],
            "slot_time": s["slot_time"],
        }
        for s in slots
    ]

    return {
        "success": True,
        "message": f"Found {len(formatted_slots)} available slot(s).",
        "doctors": doctors,
        "available_slots": formatted_slots,
    }


def book_appointment(
    doctor_name: str,
    slot_id: int,
    patient_name: str,
    patient_phone: str,
    phone_confirmed: bool = False,
    db_path: Path | str = db.DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Book an appointment after validating phone number, doctor-slot match,
    and explicit caller confirmation (phone_confirmed=True).
    """
    if not patient_name or not str(patient_name).strip():
        return {
            "success": False,
            "message": "Patient name is required before booking.",
            "appointment": None,
        }

    if not doctor_name or not str(doctor_name).strip():
        return {
            "success": False,
            "message": "Doctor name is required before booking.",
            "appointment": None,
        }

    is_valid, digits, error_msg = validate_phone_number(patient_phone)
    if not is_valid:
        return {
            "success": False,
            "message": error_msg,
            "appointment": None,
        }

    if phone_confirmed is not True:
        readback = format_phone_digit_by_digit(digits)
        return {
            "success": False,
            "requires_confirmation": True,
            "message": (
                f"Booking refused: caller phone number is not confirmed yet. "
                f"Please read back the digits ({readback}), ask if it is correct, "
                f"and wait for an explicit 'yes' before calling book_appointment."
            ),
            "appointment": None,
        }

    # Verify the requested doctor actually owns this slot before booking
    conn = db.get_connection(db_path)
    try:
        slot_row = conn.execute(
            """
            SELECT s.id, d.name AS doctor_name, d.specialty
            FROM slots s
            JOIN doctors d ON d.id = s.doctor_id
            WHERE s.id = ?
            """,
            (slot_id,),
        ).fetchone()
    finally:
        conn.close()

    if slot_row is None:
        return {
            "success": False,
            "message": f"Slot {slot_id} was not found.",
            "appointment": None,
        }

    if not _doctor_matches(doctor_name, slot_row["doctor_name"]):
        return {
            "success": False,
            "message": (
                f"Doctor mismatch: slot {slot_id} belongs to {slot_row['doctor_name']} "
                f"({slot_row['specialty']}), not {doctor_name}."
            ),
            "appointment": None,
        }

    return db.book_appointment(
        slot_id=slot_id,
        patient_name=patient_name.strip(),
        patient_phone=digits,
        db_path=db_path,
    )


def cancel_appointment(
    patient_phone: str,
    appointment_id: int | None = None,
    phone_confirmed: bool = False,
    db_path: Path | str = db.DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Cancel an active appointment belonging to `patient_phone` after
    explicit caller confirmation (phone_confirmed=True).
    """
    is_valid, digits, error_msg = validate_phone_number(patient_phone)
    if not is_valid:
        return {
            "success": False,
            "message": error_msg,
            "appointment": None,
        }

    if phone_confirmed is not True:
        readback = format_phone_digit_by_digit(digits)
        return {
            "success": False,
            "requires_confirmation": True,
            "message": (
                f"Cancellation refused: caller phone number is not confirmed yet. "
                f"Please read back the digits ({readback}), ask if it is correct, "
                f"and wait for an explicit 'yes' before calling cancel_appointment."
            ),
            "appointment": None,
        }

    # Ensure there is an active booking belonging to this phone number
    active_for_phone = db.get_all_appointments(
        status="booked",
        patient_phone=digits,
        db_path=db_path,
    )
    if not active_for_phone:
        return {
            "success": False,
            "message": "No active appointment was found for that phone number.",
            "appointment": None,
        }

    if appointment_id is not None:
        matching_ids = {appt["id"] for appt in active_for_phone}
        if appointment_id not in matching_ids:
            return {
                "success": False,
                "message": (
                    f"Cannot cancel appointment #{appointment_id}: it is either inactive "
                    f"or does not belong to this phone number."
                ),
                "appointment": None,
            }

    return db.cancel_appointment(
        appointment_id=appointment_id,
        patient_phone=digits,
        db_path=db_path,
    )
