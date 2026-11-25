import { useState, useCallback, useRef, useEffect } from "react";
import {
  usePipecatClient,
  useRTVIClientEvent,
  usePipecatClientTransportState,
} from "@pipecat-ai/client-react";
import { RTVIEvent, TransportStateEnum } from "@pipecat-ai/client-js";
import Waveform from "./Waveform.jsx";

/**
 * Voice interaction stage — the visual centerpiece.
 *
 * Props:
 *   onUserTranscript(text)  – called when the user finishes speaking
 *   onBotTranscript(text)   – called when the bot finishes speaking
 *   onAppointmentsUpdated() – called when the bot books/cancels (server message)
 */
export default function VoiceStage({
  onUserTranscript,
  onBotTranscript,
  onAppointmentsUpdated,
}) {
  const client = usePipecatClient();
  const transportState = usePipecatClientTransportState();

  const [isMuted, setIsMuted] = useState(false);
  const [micStream, setMicStream] = useState(null);
  const [waveformState, setWaveformState] = useState("idle");
  const [statusText, setStatusText] = useState("Ready to connect");

  const streamRef = useRef(null);

  // Determine effective state label
  const isConnected =
    transportState === TransportStateEnum.CONNECTED ||
    transportState === TransportStateEnum.READY;
  const isConnecting =
    transportState === TransportStateEnum.CONNECTING ||
    transportState === TransportStateEnum.AUTHENTICATING;
  const isDisconnected =
    transportState === TransportStateEnum.DISCONNECTED ||
    transportState === TransportStateEnum.IDLE ||
    transportState === TransportStateEnum.ERROR ||
    transportState == null;

  // Update status text based on transport state
  useEffect(() => {
    if (isConnecting) {
      setStatusText("Connecting…");
      setWaveformState("connecting");
    } else if (isConnected) {
      setStatusText("Connected — listening");
      setWaveformState("listening");
    } else if (transportState === TransportStateEnum.ERROR) {
      setStatusText("Connection failed — check backend");
      setWaveformState("idle");
    } else {
      setStatusText("Ready to connect");
      setWaveformState("idle");
    }
  }, [transportState, isConnecting, isConnected]);

  // User speaking events
  useRTVIClientEvent(RTVIEvent.UserStartedSpeaking, () => {
    if (isConnected) {
      setWaveformState("listening");
      setStatusText("Listening…");
    }
  });

  useRTVIClientEvent(RTVIEvent.UserStoppedSpeaking, () => {
    if (isConnected) {
      setStatusText("Processing…");
    }
  });

  // Bot speaking events
  useRTVIClientEvent(RTVIEvent.BotStartedSpeaking, () => {
    if (isConnected) {
      setWaveformState("speaking");
      setStatusText("MediVoice is speaking…");
    }
  });

  useRTVIClientEvent(RTVIEvent.BotStoppedSpeaking, () => {
    if (isConnected) {
      setWaveformState("listening");
      setStatusText("Listening…");
    }
  });

  // Transcript events
  useRTVIClientEvent(RTVIEvent.UserTranscript, (evt) => {
    if (evt?.final && evt?.text) {
      onUserTranscript?.(evt.text);
    }
  });

  useRTVIClientEvent(RTVIEvent.BotTranscript, (evt) => {
    if (evt?.text) {
      onBotTranscript?.(evt.text);
    }
  });

  // Server message (appointments_updated)
  useRTVIClientEvent(RTVIEvent.ServerMessage, (msg) => {
    if (msg?.type === "appointments_updated") {
      onAppointmentsUpdated?.();
    }
  });

  // Start call
  const handleStartCall = useCallback(async () => {
    if (!client) return;
    try {
      // Get microphone stream for waveform visualization
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setMicStream(stream);
      setIsMuted(false);

      await client.connect();
    } catch (err) {
      console.error("Failed to start call:", err);
      setStatusText("Connection failed — check backend");
      setWaveformState("idle");
      // Clean up mic stream on failure
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        setMicStream(null);
      }
    }
  }, [client]);

  // End call
  const handleEndCall = useCallback(async () => {
    if (!client) return;
    try {
      await client.disconnect();
    } catch (err) {
      console.error("Error ending call:", err);
    }
    // Stop mic stream
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setMicStream(null);
    }
    setIsMuted(false);
    setWaveformState("idle");
    setStatusText("Call ended");
  }, [client]);

  // Mute / unmute
  const handleToggleMute = useCallback(() => {
    if (!client || !isConnected) return;
    const newMuted = !isMuted;
    setIsMuted(newMuted);
    client.enableMic(!newMuted);

    // Also mute the visualization stream
    if (streamRef.current) {
      streamRef.current
        .getAudioTracks()
        .forEach((t) => (t.enabled = !newMuted));
    }
  }, [client, isMuted, isConnected]);

  return (
    <div className="voice-stage">
      <div className="voice-stage-header">
        <span className="voice-label">Voice Console</span>
        <span className={`connection-indicator ${isConnected ? "connected" : ""}`}>
          {isConnected ? "LIVE" : "OFFLINE"}
        </span>
      </div>

      <div className="waveform-container">
        <Waveform state={waveformState} stream={micStream} />
      </div>

      <p className="voice-status">{statusText}</p>

      <div className="voice-controls">
        {isDisconnected && !isConnecting ? (
          <button className="btn-call btn-start" onClick={handleStartCall}>
            Start Call
          </button>
        ) : (
          <>
            <button
              className={`btn-call btn-mute ${isMuted ? "muted" : ""}`}
              onClick={handleToggleMute}
              disabled={!isConnected}
            >
              {isMuted ? "Unmute" : "Mute"}
            </button>
            <button className="btn-call btn-end" onClick={handleEndCall}>
              End Call
            </button>
          </>
        )}
      </div>
    </div>
  );
}
