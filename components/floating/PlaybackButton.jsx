"use client";

import { memo } from "react";

/**
 * Circular purple glass playback toggle button (Play / Pause).
 */
function PlaybackButton({ isPlaying, onToggle }) {
  const stopDrag = (event) => {
    event.stopPropagation();
  };

  return (
    <button
      type="button"
      onClick={onToggle}
      onMouseDown={stopDrag}
      onPointerDown={stopDrag}
      aria-label={isPlaying ? "Pause voice playback" : "Play voice playback"}
      aria-pressed={isPlaying}
      className="nova-circle-btn nova-playback-btn relative flex h-[54px] w-[54px] shrink-0 cursor-pointer items-center justify-center rounded-full text-white outline-none transition-transform duration-150 ease-out hover:scale-[1.04] active:scale-[0.95] focus-visible:ring-2 focus-visible:ring-purple-200/70"
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-[2.5px] rounded-full border border-white/25"
      />
      {isPlaying ? (
        <svg
          width="19"
          height="19"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
          className="relative z-10"
        >
          <rect x="6" y="4.5" width="4.4" height="15" rx="2.2" />
          <rect x="13.6" y="4.5" width="4.4" height="15" rx="2.2" />
        </svg>
      ) : (
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
          className="relative z-10 translate-x-[1.5px]"
        >
          <path d="M7.8 5.25c0-1.15 1.26-1.86 2.25-1.26l10.2 6.07a1.46 1.46 0 0 1 0 2.52l-10.2 6.07c-.99.59-2.25-.12-2.25-1.27V5.25Z" />
        </svg>
      )}
    </button>
  );
}

export default memo(PlaybackButton);
