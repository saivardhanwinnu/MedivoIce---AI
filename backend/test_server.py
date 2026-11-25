"""
Unit tests for backend/server.py FastAPI REST and WebRTC signaling endpoints.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

# Allow running tests from either repo root or backend/
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import bot  # noqa: E402
import db  # noqa: E402
import tools  # noqa: E402
from server import create_app  # noqa: E402


class TestMediVoiceServer(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.test_db = Path(self.temp_dir.name) / "test_server.db"
        self.mock_webrtc_handler = MagicMock()
        self.mock_webrtc_handler.handle_web_request = AsyncMock(
            return_value={"sdp": "v=0...", "type": "answer", "pc_id": "pc-1"}
        )
        self.mock_webrtc_handler.handle_patch_request = AsyncMock()
        self.mock_webrtc_handler.close = AsyncMock()

        self.app = create_app(
            db_path=self.test_db,
            webrtc_handler=self.mock_webrtc_handler,
        )
        self.client_ctx = TestClient(self.app)
        self.client = self.client_ctx.__enter__()
        self.addCleanup(self.client_ctx.__exit__, None, None, None)

    def tearDown(self) -> None:
        # Cleanup is handled in reverse registration order via addCleanup
        pass

    def test_health_endpoint(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "connected")

    def test_doctors_endpoint_includes_slots(self) -> None:
        response = self.client.get("/api/doctors")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 4)
        self.assertEqual(len(data["doctors"]), 4)

        first_doc = data["doctors"][0]
        self.assertEqual(first_doc["name"], "Dr. Ananya")
        self.assertGreater(len(first_doc["slots"]), 0)
        self.assertFalse(first_doc["slots"][0]["is_booked"])

    def test_slots_endpoint_filters_by_doctor_and_date(self) -> None:
        all_resp = self.client.get("/api/slots")
        self.assertEqual(all_resp.status_code, 200)
        all_slots = all_resp.json()["slots"]
        self.assertEqual(len(all_slots), 48)

        cardio_resp = self.client.get("/api/slots", params={"doctor": "Cardiologist"})
        self.assertEqual(cardio_resp.status_code, 200)
        cardio_slots = cardio_resp.json()["slots"]
        self.assertGreater(len(cardio_slots), 0)
        self.assertTrue(all(s["doctor_name"] == "Dr. Rahul" for s in cardio_slots))

        target_date = cardio_slots[0]["slot_date"]
        date_resp = self.client.get(
            "/api/slots",
            params={"doctor": "Dr. Rahul", "date": target_date},
        )
        self.assertEqual(date_resp.status_code, 200)
        date_slots = date_resp.json()["slots"]
        self.assertGreater(len(date_slots), 0)
        self.assertTrue(all(s["slot_date"] == target_date for s in date_slots))

    def test_slots_endpoint_invalid_date_returns_400(self) -> None:
        response = self.client.get("/api/slots", params={"date": "25-11-2026"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("YYYY-MM-DD", response.json()["detail"])

    def test_appointments_endpoint_reflects_booking_and_cancellation(self) -> None:
        # Initially empty
        initial = self.client.get("/api/appointments")
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["count"], 0)

        # Book via existing tool
        slots = db.check_available_slots(doctor_query="Dr. Priya", db_path=self.test_db)
        chosen = slots[0]
        booking = tools.book_appointment(
            doctor_name="Dr. Priya",
            slot_id=chosen["slot_id"],
            patient_name="Asha Nair",
            patient_phone="9876543210",
            phone_confirmed=True,
            db_path=self.test_db,
        )
        self.assertTrue(booking["success"])

        # /api/appointments should show the booked appointment
        after_book = self.client.get("/api/appointments")
        self.assertEqual(after_book.status_code, 200)
        self.assertEqual(after_book.json()["count"], 1)
        self.assertEqual(after_book.json()["appointments"][0]["status"], "booked")

        # /api/doctors should mark that exact slot as is_booked=True
        docs_resp = self.client.get("/api/doctors").json()["doctors"]
        priya = next(d for d in docs_resp if d["name"] == "Dr. Priya")
        priya_slot = next(s for s in priya["slots"] if s["slot_id"] == chosen["slot_id"])
        self.assertTrue(priya_slot["is_booked"])

        # Cancel and verify status updates
        cancel = tools.cancel_appointment(
            patient_phone="9876543210",
            appointment_id=booking["appointment"]["id"],
            phone_confirmed=True,
            db_path=self.test_db,
        )
        self.assertTrue(cancel["success"])

        booked_only = self.client.get("/api/appointments", params={"status": "booked"})
        self.assertEqual(booked_only.status_code, 200)
        self.assertEqual(booked_only.json()["count"], 0)

        invalid_status = self.client.get("/api/appointments", params={"status": "unknown"})
        self.assertEqual(invalid_status.status_code, 400)

    def test_webrtc_offer_requires_api_keys(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("server.bot.load_voice_config", side_effect=ValueError("Missing required API key(s)")),
        ):
            response = self.client.post(
                "/api/offer",
                json={"sdp": "v=0...", "type": "offer"},
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("Missing required API key", response.json()["detail"])

    def test_webrtc_offer_and_patch_delegate_to_handler(self) -> None:
        fake_cfg = bot.VoiceBotConfig(
            gemini_api_key="test-gem",
            elevenlabs_api_key="test-el",
        )
        with patch("server.bot.load_voice_config", return_value=fake_cfg):
            offer_resp = self.client.post(
                "/api/offer",
                json={"sdp": "v=0...", "type": "offer"},
            )
            self.assertEqual(offer_resp.status_code, 200)
            self.assertEqual(offer_resp.json()["pc_id"], "pc-1")
            self.mock_webrtc_handler.handle_web_request.assert_awaited_once()

            patch_resp = self.client.patch(
                "/api/offer",
                json={
                    "pc_id": "pc-1",
                    "candidates": [
                        {
                            "candidate": "candidate:1 1 UDP 2122252543 127.0.0.1 50000 typ host",
                            "sdp_mid": "0",
                            "sdp_mline_index": 0,
                        }
                    ],
                },
            )
            self.assertEqual(patch_resp.status_code, 200)
            self.assertEqual(patch_resp.json()["status"], "success")
            self.mock_webrtc_handler.handle_patch_request.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
