import { useMemo, useCallback } from "react";
import { PipecatClient } from "@pipecat-ai/client-js";
import {
  PipecatClientProvider,
  PipecatClientAudio,
} from "@pipecat-ai/client-react";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";

import VoiceStage from "./components/VoiceStage.jsx";
import Transcript from "./components/Transcript.jsx";
import Schedule from "./components/Schedule.jsx";
import Appointments from "./components/Appointments.jsx";
import { useApi } from "./hooks/useApi.js";
import { useTranscript } from "./hooks/useTranscript.js";

export default function App() {
  const { doctors, appointments, loading, error, refetch } = useApi();
  const { messages, addUserMessage, addBotMessage } = useTranscript();

  // Create Pipecat client once, pointing SmallWebRTCTransport at FastAPI /api/offer
  const client = useMemo(() => {
    const transport = new SmallWebRTCTransport({
      webrtcRequestParams: {
        endpoint: "/api/offer",
      },
    });
    return new PipecatClient({
      transport,
    });
  }, []);

  // Callback when the voice assistant books or cancels
  const handleAppointmentsUpdated = useCallback(() => {
    // Small delay to let the database transaction complete
    setTimeout(() => refetch(), 500);
  }, [refetch]);

  return (
    <PipecatClientProvider client={client}>
      <PipecatClientAudio />

      <div className="app-shell">
        {/* Header */}
        <header className="app-header">
          <h1 className="app-title">MediVoice</h1>
          <span className="app-subtitle">Clinical Voice Console</span>
        </header>

        {error && (
          <div className="api-error">
            Backend unavailable — {error}. Start the FastAPI server on port 8000.
          </div>
        )}

        {/* Main Grid — 60/40 asymmetric layout */}
        <main className="app-main">
          {/* Left column — 60% — Voice + Transcript */}
          <section className="col-primary">
            <VoiceStage
              onUserTranscript={addUserMessage}
              onBotTranscript={addBotMessage}
              onAppointmentsUpdated={handleAppointmentsUpdated}
            />
            <Transcript messages={messages} />
          </section>

          {/* Right column — 40% — Schedule + Appointments */}
          <section className="col-secondary">
            <Schedule doctors={doctors} loading={loading} />
            <Appointments appointments={appointments} loading={loading} />
          </section>
        </main>

        <footer className="app-footer">
          <span>MediVoice AI — Local Demo</span>
        </footer>
      </div>
    </PipecatClientProvider>
  );
}
