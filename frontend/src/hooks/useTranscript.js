import { useState, useCallback, useRef } from "react";

/**
 * Custom hook to collect live conversation transcripts.
 * Returns { messages, addUserMessage, addBotMessage, clearMessages }.
 */
export function useTranscript() {
  const [messages, setMessages] = useState([]);
  const idRef = useRef(0);

  const addUserMessage = useCallback((text) => {
    if (!text || !text.trim()) return;
    setMessages((prev) => [
      ...prev,
      {
        id: ++idRef.current,
        role: "user",
        text: text.trim(),
        time: new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
      },
    ]);
  }, []);

  const addBotMessage = useCallback((text) => {
    if (!text || !text.trim()) return;
    setMessages((prev) => [
      ...prev,
      {
        id: ++idRef.current,
        role: "assistant",
        text: text.trim(),
        time: new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        }),
      },
    ]);
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
    idRef.current = 0;
  }, []);

  return { messages, addUserMessage, addBotMessage, clearMessages };
}
