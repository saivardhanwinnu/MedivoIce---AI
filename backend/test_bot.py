"""
Unit tests for backend/bot.py Pipecat pipeline, tool schemas, and mocked tool calls.

No external Gemini or ElevenLabs API calls are made during these tests.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import bot  # noqa: E402
import db  # noqa: E402


def _make_fake_params(arguments: dict, worker: MagicMock | None = None):
    """Build a lightweight FunctionCallParams-like object with an async result callback."""
    callback = AsyncMock()
    params = SimpleNamespace(
        function_name="test_tool",
        tool_call_id="call_123",
        arguments=arguments,
        llm=MagicMock(),
        pipeline_worker=worker,
        context=MagicMock(),
        result_callback=callback,
    )
    return params, callback


class TestMediVoiceBotConfig(unittest.TestCase):
    def test_load_voice_config_rejects_missing_or_placeholder_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_env = Path(tmpdir) / ".env"
            empty_env.write_text(
                "GEMINI_API_KEY=your_gemini_api_key_here\n"
                "ELEVENLABS_API_KEY=your_elevenlabs_api_key_here\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ValueError) as ctx:
                    bot.load_voice_config(env_path=empty_env)
                self.assertIn("GEMINI_API_KEY", str(ctx.exception))
                self.assertIn("ELEVENLABS_API_KEY", str(ctx.exception))

    def test_load_voice_config_reads_env_file_without_hardcoded_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_env = Path(tmpdir) / ".env"
            test_env.write_text(
                "GEMINI_API_KEY=test-gem-key\n"
                "ELEVENLABS_API_KEY=test-el-key\n"
                "ELEVENLABS_VOICE_ID=custom-voice-123\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                cfg = bot.load_voice_config(env_path=test_env)
                self.assertEqual(cfg.gemini_api_key, "test-gem-key")
                self.assertEqual(cfg.elevenlabs_api_key, "test-el-key")
                self.assertEqual(cfg.elevenlabs_voice_id, "custom-voice-123")


class TestMediVoicePipelineAndTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.test_db = Path(self.temp_dir.name) / "test_bot.db"
        db.init_db(self.test_db)

    def test_tools_schema_exposes_required_three_tools(self) -> None:
        schema = bot.build_tools_schema()
        tool_names = [t.name for t in schema.standard_tools]
        self.assertEqual(
            tool_names,
            ["check_doctor_availability", "book_appointment", "cancel_appointment"],
        )
        book_schema = schema.standard_tools[1]
        cancel_schema = schema.standard_tools[2]
        self.assertIn("phone_confirmed", book_schema.required)
        self.assertIn("phone_confirmed", cancel_schema.required)

    async def test_registered_handlers_enforce_confirmation_and_ownership(self) -> None:
        handlers = bot.create_tool_handlers(db_path=self.test_db)

        # 1. Check availability
        avail_params, avail_cb = _make_fake_params({"specialty_or_doctor": "Cardiologist"})
        await handlers["check_doctor_availability"](avail_params)
        avail_result = avail_cb.call_args[0][0]
        self.assertTrue(avail_result["success"])
        slot_id = avail_result["available_slots"][0]["slot_id"]

        # 2. Booking without confirmation must be refused
        worker_mock = MagicMock()
        worker_mock.queue_frames = AsyncMock()
        unconfirmed_params, unconfirmed_cb = _make_fake_params(
            {
                "doctor_name": "Dr. Rahul",
                "slot_id": slot_id,
                "patient_name": "Anjali Rao",
                "patient_phone": "9876543210",
                "phone_confirmed": False,
            },
            worker=worker_mock,
        )
        await handlers["book_appointment"](unconfirmed_params)
        unconfirmed_result = unconfirmed_cb.call_args[0][0]
        self.assertFalse(unconfirmed_result["success"])
        self.assertTrue(unconfirmed_result.get("requires_confirmation"))
        worker_mock.queue_frames.assert_not_awaited()

        # 3. Booking with explicit confirmation succeeds and notifies UI
        confirmed_params, confirmed_cb = _make_fake_params(
            {
                "doctor_name": "Dr. Rahul",
                "slot_id": slot_id,
                "patient_name": "Anjali Rao",
                "patient_phone": "9876543210",
                "phone_confirmed": True,
            },
            worker=worker_mock,
        )
        await handlers["book_appointment"](confirmed_params)
        booked_result = confirmed_cb.call_args[0][0]
        self.assertTrue(booked_result["success"])
        appt_id = booked_result["appointment"]["id"]
        worker_mock.queue_frames.assert_awaited_once()

        # 4. Another caller cannot cancel Anjali's appointment
        other_cancel_params, other_cancel_cb = _make_fake_params(
            {
                "patient_phone": "9998887776",
                "appointment_id": appt_id,
                "phone_confirmed": True,
            }
        )
        await handlers["cancel_appointment"](other_cancel_params)
        self.assertFalse(other_cancel_cb.call_args[0][0]["success"])

        # 5. Confirmed cancellation by the owner succeeds
        owner_cancel_params, owner_cancel_cb = _make_fake_params(
            {
                "patient_phone": "9876543210",
                "appointment_id": appt_id,
                "phone_confirmed": True,
            },
            worker=worker_mock,
        )
        await handlers["cancel_appointment"](owner_cancel_params)
        self.assertTrue(owner_cancel_cb.call_args[0][0]["success"])

    def test_build_pipeline_worker_wires_elevenlabs_gemini_and_smallwebrtc(self) -> None:
        config = bot.VoiceBotConfig(
            gemini_api_key="mock-gem-key",
            elevenlabs_api_key="mock-el-key",
        )
        fake_conn = MagicMock()

        with (
            patch("bot.SmallWebRTCTransport") as mock_transport_cls,
            patch("bot.ElevenLabsRealtimeSTTService") as mock_stt_cls,
            patch("bot.GoogleLLMService") as mock_llm_cls,
            patch("bot.ElevenLabsTTSService") as mock_tts_cls,
            patch("bot.SileroVADAnalyzer") as mock_vad_cls,
            patch("bot.PipelineWorker") as mock_worker_cls,
        ):
            mock_transport = MagicMock()
            mock_transport.event_handler.return_value = lambda fn: fn
            mock_transport_cls.return_value = mock_transport

            mock_llm = MagicMock()
            mock_llm_cls.return_value = mock_llm

            worker, transport = bot.build_pipeline_worker(
                webrtc_connection=fake_conn,
                config=config,
                db_path=self.test_db,
            )

            mock_transport_cls.assert_called_once()
            mock_stt_cls.assert_called_once()
            mock_llm_cls.assert_called_once()
            mock_tts_cls.assert_called_once()
            mock_vad_cls.assert_called_once()
            mock_worker_cls.assert_called_once()
            self.assertIs(transport, mock_transport)
            self.assertIs(worker, mock_worker_cls.return_value)

            # Verify all 3 clinic tools were registered on GoogleLLMService
            registered_names = [call.args[0] for call in mock_llm.register_function.call_args_list]
            self.assertEqual(
                registered_names,
                ["check_doctor_availability", "book_appointment", "cancel_appointment"],
            )


if __name__ == "__main__":
    unittest.main()
