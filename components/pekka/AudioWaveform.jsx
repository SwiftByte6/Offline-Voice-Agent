"use client";

import { sampleAudioLevels } from "@/hooks/useVoiceRecorder";

const BAR_HEIGHTS_PX = [9, 13, 16, 13, 9];
const REST_LEVELS = [0.22, 0.34, 0.48, 0.38, 0.26];

/**
 * Minimal restrained vertical-bar audio waveform for the bottom-left strip.
 * Uses real microphone `levels` / `audioLevels` when active, or static rest bars when idle.
 */
export default function AudioWaveform({
  active,
  levels = null,
  audioLevels = null,
}) {
  const activeLevels = !active
    ? REST_LEVELS
    : levels ?? sampleAudioLevels(audioLevels, BAR_HEIGHTS_PX.length, REST_LEVELS);

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
