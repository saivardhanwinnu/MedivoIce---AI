"""
Pipecat Voice AI pipeline for MediVoice AI.

Connects a local browser via SmallWebRTCTransport to:
- ElevenLabsRealtimeSTTService (Speech-to-Text)
- GoogleLLMService with Gemini (LLM + 3 clinic tools)
- ElevenLabsTTSService (Text-to-Speech)
- SileroVADAnalyzer (Voice Activity Detection)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frameworks.rtvi import RTVIServerMessageFrame
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

import db
import tools

BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"
DEFAULT_ELEVENLABS_TTS_MODEL = "eleven_flash_v2_5"
DEFAULT_ELEVENLABS_STT_MODEL = "scribe_v2_realtime"

VOICE_SYSTEM_PROMPT = f"""
{tools.CONVERSATION_RULES}

VOICE CONVERSATION GUIDELINES:
- Speak naturally, warmly, and concisely (1-3 short sentences per turn) as this is a live phone-style voice call.
- Do not use markdown formatting, bullet symbols, or asterisks in your spoken replies.
- Always check doctor availability using `check_doctor_availability` before suggesting specific slots, and mention the doctor name, date, time, and slot ID clearly when helping the caller choose.
- When the caller wants to book or cancel, ask for their phone number, repeat the full number back digit by digit, ask if it is correct, and wait for their explicit "yes" before setting `phone_confirmed=True`.
""".strip()

PLACEHOLDER_KEYS = {
    "your_gemini_api_key_here",
    "your_elevenlabs_api_key_here",
}


@dataclass(frozen=True)
class VoiceBotConfig:
    """Runtime API keys and model settings loaded from backend/.env."""

    gemini_api_key: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str = DEFAULT_ELEVENLABS_VOICE_ID
    gemini_model: str = DEFAULT_GEMINI_MODEL
    elevenlabs_tts_model: str = DEFAULT_ELEVENLABS_TTS_MODEL
    elevenlabs_stt_model: str = DEFAULT_ELEVENLABS_STT_MODEL


def load_voice_config(env_path: Path | None = None) -> VoiceBotConfig:
    """Load and validate required API keys from backend/.env without hardcoding secrets."""
    target_env = env_path or (BACKEND_DIR / ".env")
    if target_env.exists():
        load_dotenv(target_env, override=False)

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    elevenlabs_key = os.getenv("ELEVENLABS_API_KEY", "").strip()

    missing: list[str] = []
    if not gemini_key or gemini_key in PLACEHOLDER_KEYS:
        missing.append("GEMINI_API_KEY")
    if not elevenlabs_key or elevenlabs_key in PLACEHOLDER_KEYS:
        missing.append("ELEVENLABS_API_KEY")

    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            f"Missing required API key(s) in backend/.env: {joined}. "
            "Copy backend/.env.example to backend/.env and add your free keys."
        )

    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip() or DEFAULT_ELEVENLABS_VOICE_ID
    gemini_model = os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL

    return VoiceBotConfig(
        gemini_api_key=gemini_key,
        elevenlabs_api_key=elevenlabs_key,
        elevenlabs_voice_id=voice_id,
        gemini_model=gemini_model,
    )


def build_tools_schema() -> ToolsSchema:
    """Define Pipecat FunctionSchemas for the 3 MediVoice clinic tools."""
    check_availability_schema = FunctionSchema(
        name="check_doctor_availability",
        description=(
            "Search doctors and available appointment slots in the clinic database. "
            "Use this when the caller asks which doctors or times are open."
        ),
        properties={
            "specialty_or_doctor": {
                "type": "string",
                "description": (
                    "Optional doctor name (e.g. 'Dr. Rahul') or medical specialty "
                    "(e.g. 'Cardiologist', 'Dermatologist', 'Orthopedic', 'General Physician')."
                ),
            },
            "date": {
                "type": "string",
                "description": "Optional date filter in YYYY-MM-DD format.",
            },
        },
        required=[],
    )

    book_appointment_schema = FunctionSchema(
        name="book_appointment",
        description=(
            "Book an appointment slot for a patient. ONLY call with phone_confirmed=True "
            "after you have read the caller's phone number back digit by digit and they "
            "explicitly said yes."
        ),
        properties={
            "doctor_name": {
                "type": "string",
                "description": "Doctor's name, e.g. 'Dr. Ananya' or 'Dr. Rahul'.",
            },
            "slot_id": {
                "type": "integer",
                "description": "The numeric slot_id returned by check_doctor_availability.",
            },
            "patient_name": {
                "type": "string",
                "description": "Full name of the patient.",
            },
            "patient_phone": {
                "type": "string",
                "description": "Caller's 10-to-15 digit phone number.",
            },
            "phone_confirmed": {
                "type": "boolean",
                "description": (
                    "Must be true ONLY after reading back the phone number digit by digit "
                    "and receiving an explicit yes from the caller."
                ),
            },
        },
        required=[
            "doctor_name",
            "slot_id",
            "patient_name",
            "patient_phone",
            "phone_confirmed",
        ],
    )

    cancel_appointment_schema = FunctionSchema(
        name="cancel_appointment",
        description=(
            "Cancel an active appointment belonging to the caller's phone number. "
            "ONLY call with phone_confirmed=True after reading the phone number back "
            "digit by digit and receiving an explicit yes."
        ),
        properties={
            "patient_phone": {
                "type": "string",
                "description": "Caller's 10-to-15 digit phone number.",
            },
            "appointment_id": {
                "type": "integer",
                "description": "Optional specific appointment ID to cancel.",
            },
            "phone_confirmed": {
                "type": "boolean",
                "description": (
                    "Must be true ONLY after reading back the phone number digit by digit "
                    "and receiving an explicit yes from the caller."
                ),
            },
        },
        required=["patient_phone", "phone_confirmed"],
    )

    return ToolsSchema(
        standard_tools=[
            check_availability_schema,
            book_appointment_schema,
            cancel_appointment_schema,
        ]
    )


async def _notify_appointments_updated(
    params: FunctionCallParams,
    action: str,
    result: dict[str, Any],
) -> None:
    """Push an RTVI server event so the React UI refreshes slots and appointments live."""
    worker = getattr(params, "pipeline_worker", None)
    if worker is None or not result.get("success"):
        return

    try:
        await worker.queue_frames(
            [
                RTVIServerMessageFrame(
                    data={
                        "type": "appointments_updated",
                        "action": action,
                        "appointment": result.get("appointment"),
                    }
                )
            ]
        )
    except Exception as exc:
        logger.debug(f"Could not send RTVI update message: {exc}")


def create_tool_handlers(
    db_path: Path | str = db.DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Create async Pipecat tool handler functions bound to `db_path`."""

    async def handle_check_doctor_availability(params: FunctionCallParams) -> None:
        specialty_or_doctor = params.arguments.get("specialty_or_doctor")
        slot_date = params.arguments.get("date")
        result = await asyncio.to_thread(
            tools.check_doctor_availability,
            specialty_or_doctor=specialty_or_doctor,
            date=slot_date,
            db_path=db_path,
        )
        await params.result_callback(result)

    async def handle_book_appointment(params: FunctionCallParams) -> None:
        raw_slot_id = params.arguments.get("slot_id")
        try:
            slot_id = int(raw_slot_id)
        except (TypeError, ValueError):
            await params.result_callback(
                {
                    "success": False,
                    "message": "Invalid slot_id. Please pick a valid slot ID from availability.",
                    "appointment": None,
                }
            )
            return

        result = await asyncio.to_thread(
            tools.book_appointment,
            doctor_name=str(params.arguments.get("doctor_name", "")),
            slot_id=slot_id,
            patient_name=str(params.arguments.get("patient_name", "")),
            patient_phone=str(params.arguments.get("patient_phone", "")),
            phone_confirmed=params.arguments.get("phone_confirmed") is True,
            db_path=db_path,
        )
        await _notify_appointments_updated(params, "booked", result)
        await params.result_callback(result)

    async def handle_cancel_appointment(params: FunctionCallParams) -> None:
        raw_appt_id = params.arguments.get("appointment_id")
        appointment_id: int | None = None
        if raw_appt_id is not None and raw_appt_id != "":
            try:
                appointment_id = int(raw_appt_id)
            except (TypeError, ValueError):
                await params.result_callback(
                    {
                        "success": False,
                        "message": "Invalid appointment_id.",
                        "appointment": None,
                    }
                )
                return

        result = await asyncio.to_thread(
            tools.cancel_appointment,
            patient_phone=str(params.arguments.get("patient_phone", "")),
            appointment_id=appointment_id,
            phone_confirmed=params.arguments.get("phone_confirmed") is True,
            db_path=db_path,
        )
        await _notify_appointments_updated(params, "cancelled", result)
        await params.result_callback(result)

    return {
        "check_doctor_availability": handle_check_doctor_availability,
        "book_appointment": handle_book_appointment,
        "cancel_appointment": handle_cancel_appointment,
    }


def register_clinic_tools(
    llm: GoogleLLMService,
    db_path: Path | str = db.DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Register the 3 MediVoice tools on a GoogleLLMService instance."""
    handlers = create_tool_handlers(db_path=db_path)
    for name, handler in handlers.items():
        llm.register_function(name, handler)
    return handlers


def build_pipeline_worker(
    webrtc_connection: SmallWebRTCConnection,
    config: VoiceBotConfig,
    db_path: Path | str = db.DEFAULT_DB_PATH,
) -> tuple[PipelineWorker, SmallWebRTCTransport]:
    """Construct the Pipecat SmallWebRTC pipeline and PipelineWorker."""
    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    stt = ElevenLabsRealtimeSTTService(
        api_key=config.elevenlabs_api_key,
        settings=ElevenLabsRealtimeSTTService.Settings(
            model=config.elevenlabs_stt_model,
        ),
    )

    llm = GoogleLLMService(
        api_key=config.gemini_api_key,
        settings=GoogleLLMService.Settings(
            model=config.gemini_model,
            system_instruction=VOICE_SYSTEM_PROMPT,
        ),
    )
    register_clinic_tools(llm, db_path=db_path)

    tts = ElevenLabsTTSService(
        api_key=config.elevenlabs_api_key,
        settings=ElevenLabsTTSService.Settings(
            voice=config.elevenlabs_voice_id,
            model=config.elevenlabs_tts_model,
        ),
    )

    context = LLMContext(
        messages=[
            {
                "role": "system",
                "content": VOICE_SYSTEM_PROMPT,
            }
        ],
        tools=build_tools_schema(),
    )

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport: SmallWebRTCTransport, _client: Any) -> None:
        logger.info("Caller connected via SmallWebRTC; greeting caller.")
        context.add_message(
            {
                "role": "user",
                "content": (
                    "A caller just joined. Greet them warmly as MediVoice AI and ask "
                    "how you can help with doctor availability, booking, or cancellation."
                ),
            }
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport: SmallWebRTCTransport, _client: Any) -> None:
        logger.info("Caller disconnected; cancelling pipeline worker.")
        await worker.cancel()

    return worker, transport


async def run_bot(
    webrtc_connection: SmallWebRTCConnection,
    db_path: Path | str = db.DEFAULT_DB_PATH,
    config: VoiceBotConfig | None = None,
) -> None:
    """Run the Pipecat voice session for a connected SmallWebRTC peer."""
    resolved_config = config or load_voice_config()
    worker, _transport = build_pipeline_worker(
        webrtc_connection=webrtc_connection,
        config=resolved_config,
        db_path=db_path,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.run(worker)
