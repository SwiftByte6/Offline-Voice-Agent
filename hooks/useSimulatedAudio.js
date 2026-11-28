"use client";

import { useEffect, useRef, useState } from "react";

const REST_LEVELS = [0.22, 0.34, 0.48, 0.38, 0.26];

export function computeSpeechEnergy(levels) {
  if (!Array.isArray(levels) || levels.length === 0) return 0;
  const total = levels.reduce((sum, val) => sum + Number(val || 0), 0);
  const avg = total / levels.length;
  return Number(Math.min(1, Math.max(0, (avg - 0.16) / 0.84)).toFixed(3));
}

/**
 * Provides organic audio amplitude bars during LISTENING.
 * Accepts optional `externalLevels` (e.g. from Web Audio API AnalyserNode)
 * so real microphone levels can drop in without rewriting the waveform UI.
 */
export function useSimulatedAudio({
  active,
  barCount = 5,
  externalLevels = null,
  reducedMotion = false,
}) {
  const [simulatedLevels, setSimulatedLevels] = useState(() =>
    Array.from({ length: barCount }, (_, i) => REST_LEVELS[i % REST_LEVELS.length])
  );
  const phaseRef = useRef(0);

  useEffect(() => {
    if (!active || externalLevels || reducedMotion) {
      return;
    }

    let cancelled = false;

    const tick = () => {
      if (cancelled) return;
      phaseRef.current += 0.55;
      const t = phaseRef.current;

      // Speech-cadence envelope: swells and natural micro-pauses.
      const cadence =
        0.52 +
        0.34 * Math.sin(t * 0.72) +
        0.16 * Math.cos(t * 1.43);

      const next = Array.from({ length: barCount }, (_, idx) => {
        const centerDist = Math.abs(idx - (barCount - 1) / 2) / Math.max(1, barCount / 2);
        const shape = 1 - centerDist * 0.28;
        const jitter = 0.72 + Math.random() * 0.56;
        const level = Math.min(1, Math.max(0.18, cadence * shape * jitter));
        return Number(level.toFixed(3));
      });

      setSimulatedLevels(next);
    };

    tick();
    const intervalId = window.setInterval(tick, 115);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [active, barCount, externalLevels, reducedMotion]);

  if (!active) {
    return Array.from({ length: barCount }, (_, i) => REST_LEVELS[i % REST_LEVELS.length]);
  }

  if (Array.isArray(externalLevels) && externalLevels.length > 0) {
    return Array.from({ length: barCount }, (_, idx) => {
      const sampleIndex = Math.min(
        externalLevels.length - 1,
        Math.floor((idx / barCount) * externalLevels.length)
      );
      const raw = Number(externalLevels[sampleIndex] ?? 0.25);
      return Math.min(1, Math.max(0.16, raw));
    });
  }

  return simulatedLevels;
}
