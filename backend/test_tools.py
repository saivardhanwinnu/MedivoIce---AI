"""
Unit tests for backend/tools.py using Python's built-in unittest module.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Allow running tests from either repo root or backend/
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import db  # noqa: E402
import tools  # noqa: E402


class TestMediVoiceTools(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_tools.db"
        db.init_db(self.test_db)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_check_doctor_availability(self) -> None:
        result = tools.check_doctor_availability(
            specialty_or_doctor="Cardiologist",
            db_path=self.test_db,
        )
        self.assertTrue(result["success"])
        self.assertGreater(len(result["available_slots"]), 0)
        first_slot = result["available_slots"][0]
        self.assertEqual(first_slot["doctor_name"], "Dr. Rahul")
        self.assertEqual(first_slot["specialty"], "Cardiologist")
        self.assertIn("slot_id", first_slot)
        self.assertIn("slot_date", first_slot)
        self.assertIn("slot_time", first_slot)

        # Date filter should narrow results to that exact date
        target_date = first_slot["slot_date"]
        date_filtered = tools.check_doctor_availability(
            specialty_or_doctor="Dr. Rahul",
            date=target_date,
            db_path=self.test_db,
        )
        self.assertGreater(len(date_filtered["available_slots"]), 0)
        self.assertTrue(
            all(s["slot_date"] == target_date for s in date_filtered["available_slots"])
        )

    def test_booking_rejected_without_confirmation(self) -> None:
        slots = tools.check_doctor_availability("Dr. Ananya", db_path=self.test_db)["available_slots"]
        chosen = slots[0]

        res = tools.book_appointment(
            doctor_name="Dr. Ananya",
            slot_id=chosen["slot_id"],
            patient_name="Sonia Rao",
            patient_phone="9876543210",
            phone_confirmed=False,
            db_path=self.test_db,
        )
        self.assertFalse(res["success"])
        self.assertTrue(res.get("requires_confirmation"))
        self.assertIn("9-8-7-6-5-4-3-2-1-0", res["message"])
        self.assertEqual(len(db.get_all_appointments(db_path=self.test_db)), 0)

    def test_booking_rejected_for_invalid_phone_number(self) -> None:
        slots = tools.check_doctor_availability("Dr. Ananya", db_path=self.test_db)["available_slots"]
        chosen = slots[0]

        for bad_phone in ["12345", "98765abcde", "", "12345678901234567"]:
            res = tools.book_appointment(
                doctor_name="Dr. Ananya",
                slot_id=chosen["slot_id"],
                patient_name="Sonia Rao",
                patient_phone=bad_phone,
                phone_confirmed=True,
                db_path=self.test_db,
            )
            self.assertFalse(res["success"], f"Expected failure for phone: {bad_phone!r}")

        self.assertEqual(len(db.get_all_appointments(db_path=self.test_db)), 0)

    def test_booking_rejected_when_doctor_and_slot_mismatch(self) -> None:
        rahul_slots = tools.check_doctor_availability("Dr. Rahul", db_path=self.test_db)["available_slots"]
        rahul_slot = rahul_slots[0]

        res = tools.book_appointment(
            doctor_name="Dr. Priya",
            slot_id=rahul_slot["slot_id"],
            patient_name="Sonia Rao",
            patient_phone="9876543210",
            phone_confirmed=True,
            db_path=self.test_db,
        )
        self.assertFalse(res["success"])
        self.assertIn("Doctor mismatch", res["message"])
        self.assertEqual(len(db.get_all_appointments(db_path=self.test_db)), 0)

    def test_successful_booking_after_confirmation(self) -> None:
        slots = tools.check_doctor_availability("Dermatologist", db_path=self.test_db)["available_slots"]
        chosen = slots[0]

        res = tools.book_appointment(
            doctor_name="Dr. Priya",
            slot_id=chosen["slot_id"],
            patient_name="Rohan Mehta",
            patient_phone="98765-43210",
            phone_confirmed=True,
            db_path=self.test_db,
        )
        self.assertTrue(res["success"])
        self.assertIsNotNone(res["appointment"])
        self.assertEqual(res["appointment"]["doctor_name"], "Dr. Priya")
        self.assertEqual(res["appointment"]["patient_phone"], "9876543210")

    def test_cancel_rejected_without_confirmation(self) -> None:
        slots = tools.check_doctor_availability("Orthopedic", db_path=self.test_db)["available_slots"]
        booking = tools.book_appointment(
            doctor_name="Dr. Kiran",
            slot_id=slots[0]["slot_id"],
            patient_name="Neha Gupta",
            patient_phone="9112233445",
            phone_confirmed=True,
            db_path=self.test_db,
        )
        appt_id = booking["appointment"]["id"]

        res = tools.cancel_appointment(
            patient_phone="9112233445",
            appointment_id=appt_id,
            phone_confirmed=False,
            db_path=self.test_db,
        )
        self.assertFalse(res["success"])
        self.assertTrue(res.get("requires_confirmation"))
        self.assertIn("9-1-1-2-2-3-3-4-4-5", res["message"])

        active = db.get_all_appointments(status="booked", db_path=self.test_db)
        self.assertEqual(len(active), 1)

    def test_prevent_cancelling_another_persons_appointment(self) -> None:
        slots = tools.check_doctor_availability("Dr. Kiran", db_path=self.test_db)["available_slots"]
        booking = tools.book_appointment(
            doctor_name="Dr. Kiran",
            slot_id=slots[0]["slot_id"],
            patient_name="Neha Gupta",
            patient_phone="9112233445",
            phone_confirmed=True,
            db_path=self.test_db,
        )
        neha_appt_id = booking["appointment"]["id"]

        # Another caller tries to cancel Neha's appointment using their own phone number
        attacker_res = tools.cancel_appointment(
            patient_phone="9998887776",
            appointment_id=neha_appt_id,
            phone_confirmed=True,
            db_path=self.test_db,
        )
        self.assertFalse(attacker_res["success"])

        # Even if the other caller ALSO has their own booking, they still cannot cancel Neha's ID
        tools.book_appointment(
            doctor_name="Dr. Kiran",
            slot_id=slots[1]["slot_id"],
            patient_name="Other Caller",
            patient_phone="9998887776",
            phone_confirmed=True,
            db_path=self.test_db,
        )
        cross_cancel = tools.cancel_appointment(
            patient_phone="9998887776",
            appointment_id=neha_appt_id,
            phone_confirmed=True,
            db_path=self.test_db,
        )
        self.assertFalse(cross_cancel["success"])
        self.assertIn("does not belong to this phone number", cross_cancel["message"])

        # Neha's appointment is still active
        neha_active = db.get_all_appointments(
            status="booked",
            patient_phone="9112233445",
            db_path=self.test_db,
        )
        self.assertEqual(len(neha_active), 1)

    def test_successful_cancellation_after_confirmation(self) -> None:
        slots = tools.check_doctor_availability("Dr. Ananya", db_path=self.test_db)["available_slots"]
        chosen = slots[0]
        booking = tools.book_appointment(
            doctor_name="Dr. Ananya",
            slot_id=chosen["slot_id"],
            patient_name="Vikram Joshi",
            patient_phone="9811122233",
            phone_confirmed=True,
            db_path=self.test_db,
        )
        appt_id = booking["appointment"]["id"]

        cancel_res = tools.cancel_appointment(
            patient_phone="9811122233",
            appointment_id=appt_id,
            phone_confirmed=True,
            db_path=self.test_db,
        )
        self.assertTrue(cancel_res["success"])
        self.assertEqual(cancel_res["appointment"]["status"], "cancelled")

        # Slot should be open again
        available_ids = {
            s["slot_id"]
            for s in tools.check_doctor_availability("Dr. Ananya", db_path=self.test_db)["available_slots"]
        }
        self.assertIn(chosen["slot_id"], available_ids)


if __name__ == "__main__":
    unittest.main()
