"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  PILL_WINDOW_SIZE,
  enforceFloatingWindowBehavior,
  positionInitialFloatingWindow,
} from "@/lib/tauriWindow";
import VoicePill from "./VoicePill";

const INITIAL_ELAPSED_SECONDS = 39;

/**
 * Top-level floating voice overlay controller.
 * Keeps the horizontal voice pill at its standard desktop size with Play/Pause state.
 */
export default function FloatingWindow() {
  const [isPlaying, setIsPlaying] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(INITIAL_ELAPSED_SECONDS);
  const [isSentFeedback, setIsSentFeedback] = useState(false);

  const sentTimeoutRef = useRef(null);

  useEffect(() => {
    let active = true;

    async function initDesktopWindow() {
      await enforceFloatingWindowBehavior();
      if (active) {
        await positionInitialFloatingWindow(PILL_WINDOW_SIZE);
      }
    }

    initDesktopWindow();

    return () => {
      active = false;
      if (sentTimeoutRef.current) {
        clearTimeout(sentTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!isPlaying) return undefined;

    const intervalId = window.setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [isPlaying]);

  const handleTogglePlay = useCallback(() => {
    setIsPlaying((prev) => !prev);
  }, []);

  const handleSend = useCallback(() => {
    setIsPlaying(false);
    setIsSentFeedback(true);

    if (sentTimeoutRef.current) {
      clearTimeout(sentTimeoutRef.current);
    }
    sentTimeoutRef.current = window.setTimeout(() => {
      setIsSentFeedback(false);
    }, 350);
  }, []);

  return (
    <main className="flex h-screen w-screen items-center justify-center bg-transparent">
      <VoicePill
        isPlaying={isPlaying}
        elapsedSeconds={elapsedSeconds}
        isSentFeedback={isSentFeedback}
        onTogglePlay={handleTogglePlay}
        onSend={handleSend}
      />
    </main>
  );
}
