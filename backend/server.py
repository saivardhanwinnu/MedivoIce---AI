"""
Local FastAPI REST & SmallWebRTC signaling server for MediVoice AI.

Exposes:
- Clinic REST endpoints (/api/health, /api/doctors, /api/appointments, /api/slots)
- Local WebRTC signaling endpoints (/api/offer POST & PATCH) for Pipecat
Bound strictly to localhost (127.0.0.1) for local development and demo use.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

# Ensure backend/ imports work whether started from repo root or backend/
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import bot  # noqa: E402
import db  # noqa: E402


def create_app(
    db_path: Path | str = db.DEFAULT_DB_PATH,
    webrtc_handler: SmallWebRTCRequestHandler | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application with the given SQLite path."""
    resolved_db_path = Path(db_path)
    handler = webrtc_handler or SmallWebRTCRequestHandler()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        # Safely initialize tables and seed sample data on server startup
        db.init_db(fastapi_app.state.db_path)
        yield
        await fastapi_app.state.webrtc_handler.close()

    fastapi_app = FastAPI(
        title="MediVoice AI API",
        description="Local REST & WebRTC API for MediVoice AI appointment scheduling.",
        version="0.2.0",
        lifespan=lifespan,
    )
    fastapi_app.state.db_path = resolved_db_path
    fastapi_app.state.webrtc_handler = handler

    # Allow only local React + Vite development origins
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )

    @fastapi_app.exception_handler(sqlite3.Error)
    async def sqlite_exception_handler(_request: Request, exc: sqlite3.Error) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Database error: {exc}"},
        )

    @fastapi_app.exception_handler(Exception)
    async def generic_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected server error occurred."},
        )

    @fastapi_app.get("/api/health")
    def get_health(request: Request) -> dict[str, Any]:
        """Return server and local SQLite database status."""
        current_db = request.app.state.db_path
        conn = db.get_connection(current_db)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()

        return {
            "status": "ok",
            "service": "MediVoice AI",
            "database": "connected",
        }

    @fastapi_app.get("/api/doctors")
    def get_doctors(request: Request) -> dict[str, Any]:
        """Return all doctors along with their available and booked appointment slots."""
        current_db = request.app.state.db_path
        doctors = db.get_all_doctors(db_path=current_db)
        available_slots = db.check_available_slots(db_path=current_db)
        booked_appointments = db.get_all_appointments(status="booked", db_path=current_db)

        slots_by_doctor: dict[int, list[dict[str, Any]]] = {doc["id"]: [] for doc in doctors}

        for slot in available_slots:
            slots_by_doctor.setdefault(slot["doctor_id"], []).append(
                {
                    "slot_id": slot["slot_id"],
                    "doctor_id": slot["doctor_id"],
                    "slot_date": slot["slot_date"],
                    "slot_time": slot["slot_time"],
                    "is_booked": False,
                }
            )

        for appt in booked_appointments:
            slots_by_doctor.setdefault(appt["doctor_id"], []).append(
                {
                    "slot_id": appt["slot_id"],
                    "doctor_id": appt["doctor_id"],
                    "slot_date": appt["slot_date"],
                    "slot_time": appt["slot_time"],
                    "is_booked": True,
                }
            )

        result: list[dict[str, Any]] = []
        for doc in doctors:
            doc_slots = sorted(
                slots_by_doctor.get(doc["id"], []),
                key=lambda s: (s["slot_date"], s["slot_id"]),
            )
            available_count = sum(1 for s in doc_slots if not s["is_booked"])
            result.append(
                {
                    "id": doc["id"],
                    "name": doc["name"],
                    "specialty": doc["specialty"],
                    "available_slots_count": available_count,
                    "slots": doc_slots,
                }
            )

        return {"doctors": result, "count": len(result)}

    @fastapi_app.get("/api/appointments")
    def get_appointments(
        request: Request,
        status: str | None = Query(default=None, description="Filter by 'booked' or 'cancelled'"),
        patient_phone: str | None = Query(default=None, description="Filter by patient phone number"),
    ) -> dict[str, Any]:
        """Return all appointments, optionally filtered by status or patient phone."""
        clean_status = status.strip().lower() if status else None
        if clean_status is not None and clean_status not in {"booked", "cancelled"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid status filter. Allowed values are 'booked' or 'cancelled'.",
            )

        appointments = db.get_all_appointments(
            status=clean_status,
            patient_phone=patient_phone,
            db_path=request.app.state.db_path,
        )
        return {"appointments": appointments, "count": len(appointments)}

    @fastapi_app.get("/api/slots")
    def get_slots(
        request: Request,
        doctor: str | None = Query(default=None, description="Filter by doctor name or specialty"),
        date: str | None = Query(default=None, description="Filter by date (YYYY-MM-DD)"),
    ) -> dict[str, Any]:
        """Return available (unbooked) slots with optional doctor and date filters."""
        clean_date: str | None = None
        if date is not None and date.strip():
            clean_date = date.strip()
            try:
                datetime.strptime(clean_date, "%Y-%m-%d")
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid date format. Please use YYYY-MM-DD (for example: 2026-11-26).",
                ) from exc

        clean_doctor = doctor.strip() if doctor and doctor.strip() else None
        slots = db.check_available_slots(
            doctor_query=clean_doctor,
            slot_date=clean_date,
            db_path=request.app.state.db_path,
        )
        return {"slots": slots, "count": len(slots)}

    @fastapi_app.post("/api/offer")
    async def webrtc_offer(
        request: SmallWebRTCRequest,
        background_tasks: BackgroundTasks,
        raw_request: Request,
    ) -> dict[str, str] | None:
        """Accept a browser WebRTC SDP offer and start the Pipecat voice pipeline."""
        try:
            config = bot.load_voice_config()
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        current_db = raw_request.app.state.db_path
        webrtc_mgr: SmallWebRTCRequestHandler = raw_request.app.state.webrtc_handler

        async def on_webrtc_connection(connection: Any) -> None:
            background_tasks.add_task(
                bot.run_bot,
                connection,
                db_path=current_db,
                config=config,
            )

        return await webrtc_mgr.handle_web_request(
            request=request,
            webrtc_connection_callback=on_webrtc_connection,
        )

    @fastapi_app.patch("/api/offer")
    async def webrtc_ice_candidate(
        request: SmallWebRTCPatchRequest,
        raw_request: Request,
    ) -> dict[str, str]:
        """Accept trickle ICE candidate patches for an active SmallWebRTC connection."""
        webrtc_mgr: SmallWebRTCRequestHandler = raw_request.app.state.webrtc_handler
        await webrtc_mgr.handle_patch_request(request)
        return {"status": "success"}

    return fastapi_app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # Bind strictly to localhost (127.0.0.1) so the server stays local only
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
