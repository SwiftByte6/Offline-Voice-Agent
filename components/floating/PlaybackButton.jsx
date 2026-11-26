"use client";

import { memo } from "react";

/**
 * Circular purple glass microphone / recording stop button.
 */
function PlaybackButton({ status, disabled, onClick }) {
  const isRecording = status === "recording";
  const isBusy = status === "starting" || status === "processing";

  const stopDrag = (event) => {
    event.stopPropagation();
  };

  const label = isRecording
    ? "Stop recording"
    : status === "starting"
      ? "Starting microphone"
      : status === "processing"
        ? "Transcribing audio"
        : "Start microphone recording";

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseDown={stopDrag}
      onPointerDown={stopDrag}
      disabled={disabled}
      aria-label={label}
      aria-pressed={isRecording}
      className={`nova-circle-btn relative flex h-[54px] w-[54px] shrink-0 items-center justify-center rounded-full text-white outline-none transition-transform duration-150 ease-out focus-visible:ring-2 focus-visible:ring-purple-200/70 ${
        isRecording
          ? "nova-recording-btn cursor-pointer hover:scale-[1.04] active:scale-[0.95]"
          : isBusy || disabled
            ? "nova-playback-btn cursor-not-allowed opacity-70"
            : "nova-playback-btn cursor-pointer hover:scale-[1.04] active:scale-[0.95]"
      }`}
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-[2.5px] rounded-full border border-white/25"
      />

      {isBusy ? (
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
          className="pointer-events-none relative z-10 animate-spin"
        >
          <circle
            cx="12"
            cy="12"
            r="8.5"
            stroke="rgba(255,255,255,0.28)"
            strokeWidth="2.4"
          />
          <path
            d="M20.5 12a8.5 8.5 0 0 0-8.5-8.5"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
          />
        </svg>
      ) : isRecording ? (
        <svg
          width="17"
          height="17"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
          className="pointer-events-none relative z-10"
        >
          <rect x="5" y="5" width="14" height="14" rx="3.2" />
        </svg>
      ) : (
        <svg
          width="21"
          height="21"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.1"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className="pointer-events-none relative z-10"
        >
          <rect x="9" y="2.8" width="6" height="11.2" rx="3" fill="currentColor" stroke="none" />
          <path d="M5.5 10.8a6.5 6.5 0 0 0 13 0" />
          <path d="M12 17.5v3.5" />
          <path d="M8.8 21h6.4" />
        </svg>
      )}
    </button>
  );
}

export default memo(PlaybackButton);
