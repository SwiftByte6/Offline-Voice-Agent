"use client";

import { memo } from "react";

function formatElapsedTime(totalSeconds) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/**
 * Elapsed placeholder timer with tabular numerals.
 */
function Timer({ seconds }) {
  const label = formatElapsedTime(seconds);

  return (
    <span
      className="pointer-events-none shrink-0 select-none font-sans text-[15px] font-medium tracking-[-0.01em] text-white/95 tabular-nums"
      aria-label={`Elapsed time ${label}`}
    >
      {label}
    </span>
  );
}

export default memo(Timer);
