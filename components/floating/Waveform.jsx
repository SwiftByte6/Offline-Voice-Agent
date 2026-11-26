"use client";

import { memo } from "react";
import { IDLE_WAVEFORM_LEVELS } from "@/hooks/useVoiceRecorder";

/**
 * Horizontal multi-bar audio waveform driven by live Web Audio API levels while recording.
 * Uses scaleY transforms on fixed-height spans to avoid layout reflows.
 */
function Waveform({ levels = IDLE_WAVEFORM_LEVELS, isRecording = false }) {
  return (
    <div
      className="pointer-events-none flex h-[50px] min-w-0 flex-1 items-center justify-between gap-[4px] px-1 [contain:layout_style]"
      aria-hidden="true"
    >
      {levels.map((amplitude, index) => {
        const clamped = Math.min(1, Math.max(0.1, amplitude));
        const opacity = isRecording
          ? clamped > 0.65
            ? 0.98
            : clamped > 0.35
              ? 0.88
              : 0.72
          : clamped > 0.65
            ? 0.9
            : clamped > 0.35
              ? 0.76
              : 0.58;

        return (
          <span
            key={index}
            className="nova-wave-bar h-[46px] w-[2.5px] shrink-0 rounded-full"
            style={{
              transform: `scaleY(${clamped})`,
              backgroundColor: `rgba(255, 255, 255, ${opacity})`,
            }}
          />
        );
      })}
    </div>
  );
}

export default memo(Waveform);
