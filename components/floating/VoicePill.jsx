"use client";

import PlaybackButton from "./PlaybackButton";
import SendButton from "./SendButton";
import Timer from "./Timer";
import Waveform from "./Waveform";

/**
 * Horizontal translucent purple glass voice pill.
 */
export default function VoicePill({
  isPlaying,
  elapsedSeconds,
  isSentFeedback,
  onTogglePlay,
  onSend,
}) {
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
        <PlaybackButton isPlaying={isPlaying} onToggle={onTogglePlay} />

        <div
          data-tauri-drag-region
          className="flex min-w-0 flex-1 items-center gap-4"
        >
          <Waveform isPlaying={isPlaying} />
          <Timer seconds={elapsedSeconds} />
        </div>

        <SendButton onSend={onSend} isSentFeedback={isSentFeedback} />
      </div>
    </div>
  );
}
