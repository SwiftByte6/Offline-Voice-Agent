"use client";

import PlaybackButton from "./PlaybackButton";
import SendButton from "./SendButton";
import Timer from "./Timer";
import Waveform from "./Waveform";

/**
 * Horizontal translucent purple glass voice pill preserving existing dimensions
 * while displaying idle, starting, recording, processing, transcript success, and error states.
 */
export default function VoicePill({
  status,
  audioLevels,
  elapsedSeconds,
  transcript,
  transcriptMeta,
  errorMessage,
  canRetry,
  backendHealth,
  onPrimaryAction,
  onSendAction,
  onRetry,
  onDismiss,
}) {
  const isStarting = status === "starting";
  const isRecording = status === "recording";
  const isProcessing = status === "processing";
  const isSuccess = status === "success";
  const isError = status === "error";

  const stopDrag = (event) => {
    event.stopPropagation();
  };

  const canSendOrRetry = isRecording || (isError && canRetry);

  const backendNotice =
    !backendHealth.reachable
      ? "Engine offline"
      : backendHealth.modelStatus === "loading"
        ? "Loading model..."
        : null;

  return (
    <div
      data-tauri-drag-region
      role="region"
      aria-label="NOVA voice interface"
      className="nova-glass-pill relative flex h-[104px] w-[596px] max-w-[calc(100vw-32px)] cursor-grab items-center gap-5 rounded-full px-[24px] active:cursor-grabbing"
    >
      <span
        aria-hidden="true"
        className="nova-glass-rim pointer-events-none absolute inset-0 rounded-full"
      />

      <div
        className="relative z-10 flex w-full items-center gap-5"
        data-tauri-drag-region
      >
        <PlaybackButton
          status={status}
          disabled={isStarting || isProcessing}
          onClick={onPrimaryAction}
        />

        {isSuccess ? (
          <div
            data-tauri-drag-region
            className="flex min-w-0 flex-1 flex-col justify-center gap-1"
          >
            <div className="flex items-center justify-between gap-2" data-tauri-drag-region>
              <span className="pointer-events-none text-[10px] font-semibold tracking-[0.12em] text-purple-100/75 uppercase">
                {transcriptMeta?.language
                  ? `${transcriptMeta.language.toUpperCase()} · ${transcriptMeta.duration.toFixed(1)}s`
                  : "Transcribed"}
              </span>
              <button
                type="button"
                onClick={onDismiss}
                onMouseDown={stopDrag}
                onPointerDown={stopDrag}
                aria-label="Dismiss transcript"
                className="cursor-pointer rounded-full px-1.5 py-0.5 text-[11px] font-medium text-white/75 transition-colors hover:bg-white/15 hover:text-white"
              >
                ×
              </button>
            </div>
            <div
              onMouseDown={stopDrag}
              onPointerDown={stopDrag}
              className="nova-transcript-scroll max-h-[54px] cursor-text select-text overflow-y-auto pr-1 text-[13.5px] leading-[1.35] font-normal text-white/95"
              title={transcript || "No speech detected"}
            >
              {transcript || "No speech detected in the recording."}
            </div>
          </div>
        ) : isError ? (
          <div
            data-tauri-drag-region
            className="flex min-w-0 flex-1 items-center justify-between gap-3"
          >
            <p className="pointer-events-none line-clamp-2 min-w-0 flex-1 text-[12.5px] leading-[1.35] font-medium text-rose-100">
              {errorMessage}
            </p>
            <div className="flex shrink-0 items-center gap-1.5">
              {canRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  onMouseDown={stopDrag}
                  onPointerDown={stopDrag}
                  className="cursor-pointer rounded-full border border-white/25 bg-white/15 px-2.5 py-1 text-[11.5px] font-medium text-white transition-colors hover:bg-white/25"
                >
                  Retry
                </button>
              )}
              <button
                type="button"
                onClick={onDismiss}
                onMouseDown={stopDrag}
                onPointerDown={stopDrag}
                aria-label="Dismiss error"
                className="cursor-pointer rounded-full px-1.5 py-0.5 text-[12px] font-medium text-white/75 transition-colors hover:bg-white/15 hover:text-white"
              >
                ×
              </button>
            </div>
          </div>
        ) : isStarting || isProcessing ? (
          <div
            data-tauri-drag-region
            className="flex min-w-0 flex-1 items-center justify-between gap-4"
          >
            <div className="pointer-events-none flex items-center gap-2.5 text-[13.5px] font-medium text-white/90">
              <span className="h-2 w-2 animate-pulse rounded-full bg-purple-200" />
              <span>
                {isStarting ? "Starting microphone..." : "Transcribing audio..."}
              </span>
            </div>
            <Timer seconds={elapsedSeconds} />
          </div>
        ) : (
          <div
            data-tauri-drag-region
            className="flex min-w-0 flex-1 items-center gap-4"
          >
            <div className="pointer-events-none flex min-w-0 flex-1 flex-col justify-center">
              <Waveform levels={audioLevels} isRecording={isRecording} />
              {!isRecording && backendNotice && (
                <span className="-mt-1 pl-1 text-[10px] font-medium tracking-[0.04em] text-purple-100/65">
                  {backendNotice}
                </span>
              )}
            </div>
            <div className="pointer-events-none flex shrink-0 items-center gap-2">
              {isRecording && (
                <span
                  className="h-2 w-2 animate-pulse rounded-full bg-rose-300"
                  title="Recording"
                />
              )}
              <Timer seconds={elapsedSeconds} />
            </div>
          </div>
        )}

        <SendButton
          status={status}
          canRetry={canRetry}
          disabled={!canSendOrRetry}
          onClick={onSendAction}
        />
      </div>
    </div>
  );
}
