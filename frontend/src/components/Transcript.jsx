import { useRef, useEffect } from "react";

/**
 * Live conversation transcript panel.
 *
 * Props:
 *   messages – array of { id, role, text, time }
 */
export default function Transcript({ messages = [] }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="transcript-panel">
      <h2 className="section-heading">Conversation Log</h2>
      <div className="transcript-scroll" ref={scrollRef}>
        {messages.length === 0 ? (
          <p className="transcript-empty">
            Start a call to see the conversation here.
          </p>
        ) : (
          messages.map((msg) => (
            <div key={msg.id} className={`transcript-msg transcript-${msg.role}`}>
              <div className="transcript-meta">
                <span className="transcript-role">
                  {msg.role === "user" ? "Caller" : "MediVoice"}
                </span>
                <span className="transcript-time">{msg.time}</span>
              </div>
              <p className="transcript-text">{msg.text}</p>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
