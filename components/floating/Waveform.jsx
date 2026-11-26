"use client";

import { memo } from "react";

/**
 * Deterministic placeholder waveform envelope (normalized 0..1).
 */
const WAVEFORM_BARS = [
  0.22, 0.72, 0.44, 0.92, 0.61, 0.34, 0.56, 0.2, 0.78, 0.96,
  0.48, 0.28, 0.64, 0.84, 0.42, 0.31, 0.88, 0.74, 0.52, 0.24,
  0.46, 0.94, 0.68, 0.37, 0.59, 0.81, 0.44, 0.19, 0.33, 0.67,
  0.86, 0.51, 0.29, 0.75, 0.91, 0.57, 0.35, 0.49, 0.79, 0.43,
  0.23, 0.62, 0.41, 0.22,
];

/**
 * Horizontal multi-bar audio waveform rendered with lightweight CSS flex bars.
 */
function Waveform({ isPlaying }) {
  return (
    <div
      className="pointer-events-none flex h-[50px] min-w-0 flex-1 items-center justify-between gap-[4px] px-1 [contain:layout_style]"
      aria-hidden="true"
    >
      {WAVEFORM_BARS.map((amplitude, index) => {
        const heightPx = Math.max(5, Math.round(amplitude * 46));
        const opacity = amplitude > 0.65 ? 0.95 : amplitude > 0.35 ? 0.82 : 0.66;

        return (
          <span
            key={index}
            className={
              isPlaying
                ? "nova-wave-bar nova-wave-bar-playing w-[2.5px] shrink-0 rounded-full"
                : "nova-wave-bar w-[2.5px] shrink-0 rounded-full"
            }
            style={{
              height: `${heightPx}px`,
              backgroundColor: `rgba(255, 255, 255, ${opacity})`,
              animationDelay: `${(index % 9) * 85}ms`,
            }}
          />
        );
      })}
    </div>
  );
}

export default memo(Waveform);
