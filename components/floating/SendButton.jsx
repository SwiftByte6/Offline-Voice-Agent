"use client";

import { memo } from "react";

/**
 * Circular translucent purple glass action button:
 * stops & sends during recording, retries on error when audio is cached.
 */
function SendButton({ status, canRetry, disabled, onClick }) {
  const isRecording = status === "recording";
  const isProcessing = status === "processing";
  const isRetry = status === "error" && canRetry;

  const stopDrag = (event) => {
    event.stopPropagation();
  };

  const label = isRecording
    ? "Stop recording and transcribe"
    : isRetry
      ? "Retry transcription"
      : isProcessing
        ? "Processing audio"
        : "Transcribe audio";

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseDown={stopDrag}
      onPointerDown={stopDrag}
      disabled={disabled}
      aria-label={label}
      className={`nova-circle-btn nova-send-btn group relative flex h-[50px] w-[50px] shrink-0 items-center justify-center rounded-full text-white outline-none transition-all duration-150 ease-out focus-visible:ring-2 focus-visible:ring-purple-200/70 ${
        disabled
          ? "cursor-default opacity-45"
          : "cursor-pointer hover:scale-[1.04] active:scale-[0.95]"
      } ${isRecording ? "ring-1 ring-purple-200/65" : ""}`}
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-[2.5px] rounded-full border border-white/22"
      />
      <svg
        width="19"
        height="19"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        className={`pointer-events-none relative z-10 transition-transform duration-150 ${
          disabled ? "" : "group-hover:-translate-y-0.5"
        }`}
      >
        <path d="M12 19V5" />
        <path d="m6.5 10.5 5.5-5.5 5.5 5.5" />
      </svg>
    </button>
  );
}

export default memo(SendButton);
