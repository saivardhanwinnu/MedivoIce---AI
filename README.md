# MediVoice AI – Voice-Based Doctor Appointment Assistant

MediVoice AI is a local, voice-powered doctor appointment assistant that allows users to check doctor availability, book appointments, and cancel appointments through natural conversation.

## Features

- Real-time browser-based voice conversations.
- Live conversation transcript.
- Doctor and available appointment slot listing.
- Book appointments using voice commands.
- Cancel existing appointments using voice commands.
- Phone number verification: the assistant reads back the caller's spoken phone number and requests confirmation before booking or cancellation.
- SQLite database for doctors, slots, and appointments.
- Dashboard updates after booking and cancellation.

## Technology Stack

- **Frontend:** React, Vite
- **Backend:** Python, FastAPI
- **Voice Pipeline:** Pipecat
- **Speech-to-Text:** ElevenLabs
- **Text-to-Speech:** ElevenLabs
- **LLM:** Google Gemini
- **Database:** SQLite
- **Communication:** WebRTC

## Project Structure

```text
medvoice/
├── backend/
│   ├── bot.py
│   ├── db.py
│   ├── server.py
│   ├── tools.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── .gitignore
└── README.md
```

## Prerequisites

- Python 3.13 (or a compatible version)
- Node.js and npm
- Gemini API key
- ElevenLabs API key

## Setup Instructions

### 1. Clone the repository

```bash
git clone https://github.com/saivardhanwinnu/MedivoIce---AI.git
cd MedivoIce---AI
```

### 2. Configure backend

Create and activate a virtual environment:

```powershell
python -m venv backend/venv
.\backend\venv\Scripts\activate
```

Install dependencies:

```powershell
pip install -r backend/requirements.txt
```

Copy the environment template:

```powershell
Copy-Item backend/.env.example backend/.env
```

Add your API keys to `backend/.env`. Never commit this file.

### 3. Start the backend

From the project root:

```powershell
python -m uvicorn server:app --app-dir backend --host 127.0.0.1 --port 8000
```

### 4. Start the frontend

Open another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the local URL displayed by Vite, usually:

```text
http://localhost:5173
```

## Voice Assistant Tools

The assistant uses three backend tools:

1. `check_doctor_availability` – checks doctors and available appointment slots.
2. `book_appointment` – books an appointment after phone number confirmation.
3. `cancel_appointment` – cancels an appointment after phone number confirmation and ownership verification.

## Testing

Run backend unit tests from the project root:

```powershell
python -m unittest discover -s backend -p "test_*.py" -v
```

The booking and cancellation workflows have been tested locally, including phone confirmation and appointment slot updates.

## Security

- API keys are stored in the local backend `.env` file.
- The `.env` file is excluded from Git using `.gitignore`.
- The `.env.example` file contains configuration placeholders only.
- Caller phone numbers are used for appointment ownership verification.

## Limitations

- This project uses mock doctor and appointment data stored locally in SQLite.
- It is a demonstration project, not a production medical service.
- API usage depends on the free-tier limits and availability of Gemini and ElevenLabs.
- The application is designed for local execution and does not require paid hosting.

## Author

**Chindam Sai Vardhan**

GitHub: https://github.com/saivardhanwinnu
