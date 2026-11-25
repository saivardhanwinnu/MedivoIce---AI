import { useRef, useEffect, useCallback } from "react";

/**
 * Canvas-based audio waveform visualizer.
 *
 * Props:
 *   state    – "idle" | "connecting" | "listening" | "speaking"
 *   stream   – MediaStream from the microphone (used for user waveform)
 */
const COLORS = {
  idle: "#9C9A93",
  connecting: "#9C9A93",
  listening: "#F2EFE9",
  speaking: "#C8F135",
};

const BAR_COUNT = 64;
const BAR_GAP = 3;

export default function Waveform({ state = "idle", stream = null }) {
  const canvasRef = useRef(null);
  const animRef = useRef(null);
  const analyserRef = useRef(null);
  const sourceRef = useRef(null);
  const ctxRef = useRef(null);

  // Set up Web Audio AnalyserNode from the mic stream
  useEffect(() => {
    if (!stream) {
      analyserRef.current = null;
      return;
    }

    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      ctxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      sourceRef.current = source;
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.75;
      source.connect(analyser);
      analyserRef.current = analyser;
    } catch (err) {
      console.warn("Web Audio setup failed:", err);
    }

    return () => {
      try {
        sourceRef.current?.disconnect();
        ctxRef.current?.close();
      } catch {}
      analyserRef.current = null;
      sourceRef.current = null;
      ctxRef.current = null;
    };
  }, [stream]);

  // Animation loop
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.width / dpr;
    const H = canvas.height / dpr;
    const midY = H / 2;

    ctx.clearRect(0, 0, W, H);

    const barWidth = (W - BAR_GAP * (BAR_COUNT - 1)) / BAR_COUNT;
    const color = COLORS[state] || COLORS.idle;
    ctx.fillStyle = color;

    const analyser = analyserRef.current;
    const dataArray = analyser
      ? new Uint8Array(analyser.frequencyBinCount)
      : null;

    if (analyser && (state === "listening" || state === "speaking")) {
      analyser.getByteFrequencyData(dataArray);
    }

    const now = performance.now();

    for (let i = 0; i < BAR_COUNT; i++) {
      let amplitude;

      if (state === "idle") {
        // Gentle sine idle animation
        amplitude =
          4 +
          Math.sin(now * 0.002 + i * 0.3) * 3 +
          Math.sin(now * 0.001 + i * 0.15) * 2;
      } else if (state === "connecting") {
        // Pulsing animation
        amplitude = 4 + Math.sin(now * 0.005 + i * 0.2) * 8;
      } else if (dataArray) {
        // Real audio data
        const index = Math.floor((i / BAR_COUNT) * dataArray.length);
        const value = dataArray[index] || 0;
        amplitude = 3 + (value / 255) * (H * 0.4);
      } else {
        amplitude = 4;
      }

      const x = i * (barWidth + BAR_GAP);
      const halfH = amplitude / 2;

      ctx.beginPath();
      ctx.roundRect(x, midY - halfH, barWidth, amplitude, 1);
      ctx.fill();
    }

    animRef.current = requestAnimationFrame(draw);
  }, [state]);

  useEffect(() => {
    animRef.current = requestAnimationFrame(draw);
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [draw]);

  // Handle canvas resize
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        canvas.width = width * window.devicePixelRatio;
        canvas.height = height * window.devicePixelRatio;
        const ctx = canvas.getContext("2d");
        ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
      }
    });
    resizeObserver.observe(canvas.parentElement);
    return () => resizeObserver.disconnect();
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="waveform-canvas"
      width={800}
      height={160}
    />
  );
}
