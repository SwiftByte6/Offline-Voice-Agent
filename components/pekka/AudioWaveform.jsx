"use client";

import { useSimulatedAudio } from "@/hooks/useSimulatedAudio";

const BAR_HEIGHTS_PX = [9, 13, 16, 13, 9];

/**
 * Minimal restrained vertical-bar audio waveform for the bottom-left strip.
 * Uses shared `levels` when provided or falls back to `useSimulatedAudio`.
 */
export default function AudioWaveform({
  active,
  levels = null,
  audioLevels = null,
  reducedMotion = false,
}) {
  const fallbackLevels = useSimulatedAudio({
    active: active && !levels,
    barCount: BAR_HEIGHTS_PX.length,
    externalLevels: audioLevels,
    reducedMotion,
  });

  const activeLevels = levels ?? fallbackLevels;

  return (
    <div
      aria-hidden="true"
      className="flex shrink-0 items-center"
      style={{ gap: "2px", height: "16px" }}
    >
      {BAR_HEIGHTS_PX.map((maxHeight, index) => {
        const scaleY = activeLevels[index] ?? 0.25;
        return (
          <span
            key={index}
            className="block rounded-full transition-transform duration-100 ease-out"
            style={{
              width: "1.75px",
              height: `${maxHeight}px`,
              backgroundColor: "var(--pekka-wave-bar-color)",
              transformOrigin: "center",
              transform: `scaleY(${scaleY})`,
              transitionDelay: `${index * 18}ms`,
            }}
          />
        );
      })}
    </div>
  );
}
