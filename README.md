# MediVoice AI

A local, zero-budget voice-powered medical appointment assistant built with React, Vite, FastAPI, Pipecat, ElevenLabs, Gemini API, and SQLite.

## Features (Planned)

- **Real-time Voice Call** in your browser (Start / End call controls)
- **Live Conversation Transcript** showing both caller and assistant messages
- **Doctors & Available Slots** view synced with SQLite
- **Appointments List** updated live after booking or cancellation
- **Phone Verification Rule:** The assistant asks for the caller's phone number, reads it back for confirmation, and only then books or cancels an appointment

## Tech Stack

- **Frontend:** React + Vite (`@pipecat-ai/client-js`, `@pipecat-ai/client-react`, `@pipecat-ai/small-webrtc-transport`)
- **Backend:** Python FastAPI + Pipecat (`pipecat-ai`)
- **Speech-to-Text (STT):** ElevenLabs (Free Tier)
- **Text-to-Speech (TTS):** ElevenLabs (Free Tier)
- **LLM:** Google Gemini API (Free Tier)
- **Database:** SQLite (local file, zero setup)

## Project Structure

```text
medvoice/
├── .gitignore          # Protects .env, venv/, node_modules/, and *.db from Git
├── README.md           # Project overview and setup instructions
├── backend/            # FastAPI + Pipecat + SQLite backend
│   └── .env.example    # Template for your local API keys
└── frontend/           # React + Vite frontend
```

## Prerequisites

1. **Python 3.11 – 3.14**
2. **Node.js (LTS) & npm**
3. **Free API Keys:**
   - Gemini API key from Google AI Studio
   - ElevenLabs API key from ElevenLabs

## Security Reminder

- Never put API keys inside `frontend/` files.
- Never commit `backend/.env` to Git. Copy `backend/.env.example` to `backend/.env` when you are ready to run the backend.

## Current Status

- [x] Step 1: Project root structure, `.gitignore`, `backend/.env.example`, and `README.md`
- [ ] Step 2: SQLite database and seed data
- [ ] Step 3: Voice assistant tools (`check_doctor_availability`, `book_appointment`, `cancel_appointment`)
- [ ] Step 4: FastAPI server & Pipecat voice pipeline
- [ ] Step 5: React + Vite frontend UI
- [ ] Step 6: Local end-to-end verification
