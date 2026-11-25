"""
Simple unit tests for backend/db.py using Python's built-in unittest module.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

# Allow running tests from either repo root or backend/
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import db  # noqa: E402


class TestMediVoiceDB(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_medvoice.db"
        db.init_db(self.test_db)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_tables_and_seed_data_created(self) -> None:
        conn = sqlite3.connect(self.test_db)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()

        self.assertTrue({"doctors", "slots", "appointments"}.issubset(tables))

        doctors = db.get_all_doctors(self.test_db)
        self.assertEqual(len(doctors), 4)
        self.assertEqual(
            [(d["name"], d["specialty"]) for d in doctors],
            [
                ("Dr. Ananya", "General Physician"),
                ("Dr. Rahul", "Cardiologist"),
                ("Dr. Priya", "Dermatologist"),
                ("Dr. Kiran", "Orthopedic"),
            ],
        )

        # Each doctor should have future slots seeded
        today_str = date.today().isoformat()
        for doc in doctors:
            doc_slots = db.check_available_slots(doctor_id=doc["id"], db_path=self.test_db)
            self.assertGreaterEqual(len(doc_slots), 4)
            self.assertTrue(all(s["slot_date"] > today_str for s in doc_slots))

    def test_book_appointment_and_prevent_double_booking(self) -> None:
        slots = db.check_available_slots(doctor_query="Cardiologist", db_path=self.test_db)
        self.assertGreater(len(slots), 0)
        chosen_slot = slots[0]

        first_booking = db.book_appointment(
            slot_id=chosen_slot["slot_id"],
            patient_name="Aarav Sharma",
            patient_phone="9876543210",
            db_path=self.test_db,
        )
        self.assertTrue(first_booking["success"])
        self.assertIsNotNone(first_booking["appointment"])
        self.assertEqual(first_booking["appointment"]["status"], "booked")

        # Slot should no longer appear in available slots
        remaining_ids = {
            s["slot_id"] for s in db.check_available_slots(doctor_query="Cardiologist", db_path=self.test_db)
        }
        self.assertNotIn(chosen_slot["slot_id"], remaining_ids)

        # Second booking on the exact same slot must fail
        second_booking = db.book_appointment(
            slot_id=chosen_slot["slot_id"],
            patient_name="Meera Nair",
            patient_phone="9123456789",
            db_path=self.test_db,
        )
        self.assertFalse(second_booking["success"])
        self.assertIsNone(second_booking["appointment"])

        # Only 1 appointment should exist
        all_appts = db.get_all_appointments(db_path=self.test_db)
        self.assertEqual(len(all_appts), 1)
        self.assertEqual(all_appts[0]["patient_name"], "Aarav Sharma")

    def test_cancel_appointment_frees_slot(self) -> None:
        slots = db.check_available_slots(doctor_query="Dr. Priya", db_path=self.test_db)
        chosen_slot = slots[0]

        booking = db.book_appointment(
            slot_id=chosen_slot["slot_id"],
            patient_name="Riya Verma",
            patient_phone="9988776655",
            db_path=self.test_db,
        )
        self.assertTrue(booking["success"])
        appt_id = booking["appointment"]["id"]

        cancel_result = db.cancel_appointment(
            patient_phone="9988776655",
            db_path=self.test_db,
        )
        self.assertTrue(cancel_result["success"])
        self.assertEqual(cancel_result["appointment"]["id"], appt_id)
        self.assertEqual(cancel_result["appointment"]["status"], "cancelled")

        # Cancelled appointment remains recorded with status='cancelled'
        all_appts = db.get_all_appointments(db_path=self.test_db)
        self.assertEqual(len(all_appts), 1)
        self.assertEqual(all_appts[0]["status"], "cancelled")

        # The freed slot should be available again and re-bookable
        available_ids = {
            s["slot_id"] for s in db.check_available_slots(doctor_query="Dr. Priya", db_path=self.test_db)
        }
        self.assertIn(chosen_slot["slot_id"], available_ids)

        rebook = db.book_appointment(
            slot_id=chosen_slot["slot_id"],
            patient_name="Kabir Patel",
            patient_phone="9000011111",
            db_path=self.test_db,
        )
        self.assertTrue(rebook["success"])


if __name__ == "__main__":
    unittest.main()
