"use client";

import { useEffect } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { PEKKA_STATES } from "@/hooks/usePekkaState";
import {
  computeSpeechEnergy,
  sampleAudioLevels,
} from "@/hooks/useVoiceRecorder";
import {
  PILL_WINDOW_SIZE,
  enforceFloatingWindowBehavior,
  positionInitialFloatingWindow,
} from "@/lib/tauriWindow";
import AudioWaveform from "./AudioWaveform";
import ExecutionStatus from "./ExecutionStatus";
import PekkaFace from "./PekkaFace";
import SleepingAnimation from "./SleepingAnimation";
import StateController from "./StateController";
import Transcription from "./Transcription";

const EXPAND_TRANSITION = {
  duration: 0.42,
  ease: [0.22, 1, 0.36, 1],
};

function getBorderVisuals(status) {
  switch (status) {
    case PEKKA_STATES.SUCCESS:
      return {
        borderColor: "var(--pekka-border-green)",
        boxShadow:
          "0 0 0 1px rgba(137, 255, 119, 0.22), 0 0 12px var(--pekka-border-green-glow), 0 10px 26px rgba(0, 0, 0, 0.65)",
      };
    case PEKKA_STATES.ERROR:
      return {
        borderColor: "rgba(251, 113, 133, 0.9)",
        boxShadow:
          "0 0 0 1px rgba(251, 113, 133, 0.24), 0 0 14px rgba(244, 63, 94, 0.32), 0 12px 28px rgba(0, 0, 0, 0.68)",
      };
    case PEKKA_STATES.LISTENING:
    case PEKKA_STATES.EXECUTING:
      return {
        borderColor: "var(--pekka-border-purple)",
        boxShadow:
          "0 0 0 1px rgba(167, 127, 192, 0.18), 0 0 12px var(--pekka-border-purple-glow), 0 12px 28px rgba(0, 0, 0, 0.68)",
      };
    case PEKKA_STATES.SLEEPING:
    default:
      return {
        borderColor: "var(--pekka-border-dim)",
        boxShadow:
          "0 0 8px rgba(154, 122, 168, 0.12), 0 8px 22px rgba(0, 0, 0, 0.58)",
      };
  }
}

function getAriaLabel(status, hasRetryBlob, backendHealth) {
  switch (status) {
    case PEKKA_STATES.SLEEPING:
      if (!backendHealth.reachable) {
        return "PEKKA voice assistant sleeping. Speech engine offline. Click to wake.";
      }
      if (backendHealth.modelStatus === "loading") {
        return "PEKKA voice assistant sleeping. Loading speech model. Click to wake.";
      }
      return "PEKKA voice assistant sleeping. Click to wake and speak.";
    case PEKKA_STATES.LISTENING:
      return "PEKKA listening. Click to stop and transcribe.";
    case PEKKA_STATES.EXECUTING:
      return "PEKKA transcribing audio. Click to cancel and return to sleep.";
    case PEKKA_STATES.SUCCESS:
      return "PEKKA completed transcription. Click to return to sleep.";
    case PEKKA_STATES.ERROR:
      return hasRetryBlob
        ? "PEKKA transcription failed. Click to retry."
        : "PEKKA encountered an error. Click to return to sleep.";
    default:
      return "PEKKA voice assistant";
  }
}

function PekkaPillShell({
  status,
  transcript,
  executionStatus,
  errorMessage,
  isStartingMic,
  audioLevels,
  backendHealth,
  hasRetryBlob,
  handlePillClick,
  cancel,
}) {
  const prefersReducedMotion = Boolean(useReducedMotion());

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
    };
  }, []);

  const isSleeping = status === PEKKA_STATES.SLEEPING;
  const isListening = status === PEKKA_STATES.LISTENING;
  const isExecuting = status === PEKKA_STATES.EXECUTING;
  const isSuccess = status === PEKKA_STATES.SUCCESS;
  const isError = status === PEKKA_STATES.ERROR;
  const isInteractive =
    isSleeping ||
    (isListening && !isStartingMic) ||
    isExecuting ||
    isSuccess ||
    isError;

  const waveLevels = isListening
    ? sampleAudioLevels(audioLevels, 5)
    : sampleAudioLevels(null, 5);
  const speechEnergy =
    isListening && !isStartingMic ? computeSpeechEnergy(waveLevels) : 0;

  const borderVisuals = getBorderVisuals(status);
  const pillPulseScale =
    isListening && !isStartingMic && !prefersReducedMotion
      ? Number((0.99 + speechEnergy * 0.02).toFixed(3))
      : 1;
  const dynamicBorderColor =
    isListening && !isStartingMic && !prefersReducedMotion
      ? `rgba(${Math.round(167 + speechEnergy * 48)}, ${Math.round(127 + speechEnergy * 18)}, ${Math.round(192 + speechEnergy * 42)}, 1)`
      : borderVisuals.borderColor;
  const listeningBoxShadow =
    isListening && !isStartingMic && !prefersReducedMotion
      ? `0 0 0 1px rgba(206, 146, 232, ${(0.22 + speechEnergy * 0.38).toFixed(2)}), 0 0 ${(12 + speechEnergy * 20).toFixed(1)}px rgba(196, 122, 224, ${(0.32 + speechEnergy * 0.45).toFixed(2)}), 0 12px 28px rgba(0, 0, 0, 0.68)`
      : borderVisuals.boxShadow;

  const listeningPlaceholder = isStartingMic
    ? "Starting mic..."
    : !backendHealth.reachable
      ? "Listening (engine offline)..."
      : backendHealth.modelStatus === "loading"
        ? "Listening (model loading)..."
        : "Listening... tap to send";

  const handleKeyDown = (event) => {
    if (event.key === "Escape" && !isSleeping) {
      event.preventDefault();
      cancel();
      return;
    }
    if (
      event.target === event.currentTarget &&
      (event.key === "Enter" || event.key === " ")
    ) {
      event.preventDefault();
      handlePillClick();
    }
  };

  const handleCancelClick = (event) => {
    event.stopPropagation();
    cancel();
  };

  return (
    <div
      className={`pekka-root relative inline-flex items-center justify-center ${
        isSleeping && !prefersReducedMotion ? "pekka-sleep-breathe" : ""
      }`}
    >
      <motion.div
        role="button"
        tabIndex={0}
        onClick={handlePillClick}
        onKeyDown={handleKeyDown}
        aria-label={getAriaLabel(status, hasRetryBlob, backendHealth)}
        data-pekka-state={status}
        initial={false}
        animate={{
          width: isSleeping ? 176 : 336,
          height: isSleeping ? 72 : 124,
          borderRadius: isSleeping ? 18 : 22,
          scale: pillPulseScale,
          borderColor: dynamicBorderColor,
          boxShadow: listeningBoxShadow,
        }}
        whileHover={
          isInteractive && !prefersReducedMotion ? { scale: 1.012 } : undefined
        }
        whileTap={
          isInteractive && !prefersReducedMotion ? { scale: 0.99 } : undefined
        }
        transition={
          prefersReducedMotion
            ? { duration: 0.01 }
            : {
                width: EXPAND_TRANSITION,
                height: EXPAND_TRANSITION,
                borderRadius: EXPAND_TRANSITION,
                borderColor: { duration: isListening ? 0.12 : 0.24, ease: "easeOut" },
                boxShadow: { duration: isListening ? 0.12 : 0.28, ease: "easeOut" },
                scale: { duration: isListening ? 0.11 : 0.16, ease: "easeOut" },
              }
        }
        className={`relative max-w-[calc(100vw-24px)] overflow-visible border-[1.5px] bg-[#050508] text-left outline-none focus-visible:ring-2 focus-visible:ring-[#a77fc0]/70 ${
          isInteractive ? "cursor-pointer" : "cursor-default"
        }`}
        style={{ backgroundColor: "var(--pekka-faceplate-bg)" }}
      >
        {/* Subtle backend readiness dot when sleeping and engine is offline or loading */}
        {isSleeping &&
          (!backendHealth.reachable || backendHealth.modelStatus === "loading") && (
            <span
              aria-hidden="true"
              title={
                !backendHealth.reachable
                  ? "Speech engine offline"
                  : "Loading Qwen3-ASR model..."
              }
              className={`pointer-events-none absolute top-2 right-2 z-20 h-1.5 w-1.5 rounded-full ${
                !backendHealth.reachable
                  ? "bg-rose-500"
                  : "animate-pulse bg-amber-400"
              }`}
            />
          )}

        {/* Dynamic speech-reactive glow strictly around the borders while listening */}
        {isListening && !isStartingMic && !prefersReducedMotion && (
          <motion.span
            aria-hidden="true"
            className="pointer-events-none absolute -inset-[2px] z-10 rounded-[inherit]"
            initial={false}
            animate={{
              opacity: Number((0.24 + speechEnergy * 0.72).toFixed(3)),
            }}
            transition={{ duration: 0.11, ease: "easeOut" }}
            style={{
              border: "1.5px solid rgba(214, 152, 238, 0.85)",
              boxShadow:
                "0 0 18px rgba(196, 122, 224, 0.52), inset 0 0 8px rgba(209, 63, 181, 0.35)",
            }}
          />
        )}

        {/* Subtle restrained green light pulse in SUCCESS */}
        {isSuccess && (
          <span
            aria-hidden="true"
            className="pekka-success-halo pointer-events-none absolute -inset-[2px] rounded-[inherit]"
            style={{
              border: "1.5px solid var(--pekka-border-green)",
              boxShadow: "0 0 18px var(--pekka-border-green-glow)",
            }}
          />
        )}

        {/* Inner metallic rim highlight */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 z-10 rounded-[inherit]"
          style={{
            boxShadow: isSuccess
              ? "inset 0 1px 0 rgba(190, 255, 184, 0.28)"
              : isError
                ? "inset 0 1px 0 rgba(254, 205, 211, 0.24)"
                : "inset 0 1px 0 rgba(226, 200, 240, 0.18)",
          }}
        />

        {/* Character faceplate & SVG eyes/armour */}
        <PekkaFace
          status={status}
          speechEnergy={speechEnergy}
          reducedMotion={prefersReducedMotion}
        />

        {/* Organic sleeping Z particles (continue fading out cleanly on wake) */}
        <SleepingAnimation
          isSleeping={isSleeping}
          reducedMotion={prefersReducedMotion}
        />

        {/* Bottom strip: waveform + live status / transcription / error + cancel */}
        <AnimatePresence mode="wait">
          {!isSleeping && (
            <motion.div
              key="pekka-bottom-strip"
              initial={prefersReducedMotion ? false : { opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={
                prefersReducedMotion
                  ? undefined
                  : { opacity: 0, transition: { duration: 0.11, ease: "easeOut" } }
              }
              transition={{
                duration: prefersReducedMotion ? 0.01 : 0.22,
                delay: isListening && !prefersReducedMotion ? 0.14 : 0,
              }}
              className="absolute right-[14px] bottom-[9px] left-[18px] z-20 flex h-[18px] items-center gap-[8px]"
            >
              {isListening && (
                <>
                  <AudioWaveform
                    active={!isStartingMic}
                    levels={waveLevels}
                  />
                  <Transcription
                    text={transcript}
                    placeholder={listeningPlaceholder}
                    reducedMotion={prefersReducedMotion}
                  />
                </>
              )}

              {isExecuting && (
                <ExecutionStatus
                  statusText={executionStatus}
                  isExecuting
                  reducedMotion={prefersReducedMotion}
                />
              )}

              {isSuccess && (
                <>
                  <AudioWaveform active={false} />
                  <ExecutionStatus
                    statusText={transcript || "No speech detected."}
                    isExecuting={false}
                    reducedMotion={prefersReducedMotion}
                  />
                </>
              )}

              {isError && (
                <p
                  className="min-w-0 flex-1 truncate text-[11px] leading-none font-normal tracking-[-0.01em] text-rose-300"
                  title={
                    hasRetryBlob
                      ? `${errorMessage} (Click pill to retry)`
                      : errorMessage
                  }
                >
                  {errorMessage}
                </p>
              )}

              {(isListening || isExecuting || isError) && (
                <button
                  type="button"
                  onClick={handleCancelClick}
                  aria-label="Cancel and return to sleep"
                  title="Cancel"
                  className="flex h-[18px] w-[18px] shrink-0 cursor-pointer items-center justify-center rounded-full text-[rgba(212,212,222,0.58)] transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#a77fc0]"
                >
                  <svg
                    width="10"
                    height="10"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    aria-hidden="true"
                  >
                    <path d="M18 6 6 18" />
                    <path d="m6 6 12 12" />
                  </svg>
                </button>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}

/**
 * Main PEKKA Animated Voice Pill composition component.
 * Connects directly to microphone capture and the local FastAPI Qwen3-ASR backend.
 */
export default function PekkaVoicePill({
  successHoldMs,
  onStateChange,
  onTranscript,
}) {
  return (
    <StateController
      successHoldMs={successHoldMs}
      onStateChange={onStateChange}
      onTranscript={onTranscript}
    >
      {(controller) => (
        <PekkaPillShell
          status={controller.status}
          transcript={controller.transcript}
          executionStatus={controller.executionStatus}
          errorMessage={controller.errorMessage}
          isStartingMic={controller.isStartingMic}
          audioLevels={controller.audioLevels}
          backendHealth={controller.backendHealth}
          hasRetryBlob={controller.hasRetryBlob}
          handlePillClick={controller.handlePillClick}
          cancel={controller.cancel}
        />
      )}
    </StateController>
  );
}
