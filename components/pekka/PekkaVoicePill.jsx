"use client";

import { useEffect } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { PEKKA_STATES } from "@/hooks/usePekkaState";
import {
  computeSpeechEnergy,
  useSimulatedAudio,
} from "@/hooks/useSimulatedAudio";
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

function getAriaLabel(status) {
  switch (status) {
    case PEKKA_STATES.SLEEPING:
      return "PEKKA voice assistant sleeping. Click to wake and listen.";
    case PEKKA_STATES.LISTENING:
      return "PEKKA listening. Click to cancel and return to sleep.";
    case PEKKA_STATES.EXECUTING:
      return "PEKKA executing task. Click to cancel and return to sleep.";
    case PEKKA_STATES.SUCCESS:
      return "PEKKA completed task successfully.";
    default:
      return "PEKKA voice assistant";
  }
}

function PekkaPillShell({
  status,
  transcript,
  executionStatus,
  handlePillClick,
  audioLevels = null,
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
  const isInteractive = isSleeping || isListening || isExecuting;

  const waveLevels = useSimulatedAudio({
    active: isListening,
    barCount: 5,
    externalLevels: audioLevels,
    reducedMotion: prefersReducedMotion,
  });
  const speechEnergy = isListening ? computeSpeechEnergy(waveLevels) : 0;

  const borderVisuals = getBorderVisuals(status);
  const pillPulseScale =
    isListening && !prefersReducedMotion
      ? Number((0.99 + speechEnergy * 0.02).toFixed(3))
      : 1;
  const dynamicBorderColor =
    isListening && !prefersReducedMotion
      ? `rgba(${Math.round(167 + speechEnergy * 48)}, ${Math.round(127 + speechEnergy * 18)}, ${Math.round(192 + speechEnergy * 42)}, 1)`
      : borderVisuals.borderColor;
  const listeningBoxShadow =
    isListening && !prefersReducedMotion
      ? `0 0 0 1px rgba(206, 146, 232, ${(0.22 + speechEnergy * 0.38).toFixed(2)}), 0 0 ${(12 + speechEnergy * 20).toFixed(1)}px rgba(196, 122, 224, ${(0.32 + speechEnergy * 0.45).toFixed(2)}), 0 12px 28px rgba(0, 0, 0, 0.68)`
      : borderVisuals.boxShadow;

  return (
    <div
      className={`pekka-root relative inline-flex items-center justify-center ${
        isSleeping && !prefersReducedMotion ? "pekka-sleep-breathe" : ""
      }`}
    >
      <motion.button
        type="button"
        onClick={handlePillClick}
        aria-label={getAriaLabel(status)}
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
        {/* Dynamic speech-reactive glow strictly around the borders while listening */}
        {isListening && !prefersReducedMotion && (
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

        {/* Bottom strip: waveform + transcription / execution status */}
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
              className="pointer-events-none absolute right-[18px] bottom-[9px] left-[18px] z-20 flex h-[18px] items-center gap-[10px]"
            >
              {isListening && (
                <>
                  <AudioWaveform
                    active={isListening}
                    levels={waveLevels}
                    audioLevels={audioLevels}
                    reducedMotion={prefersReducedMotion}
                  />
                  <Transcription
                    text={transcript}
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
                  <AudioWaveform
                    active={false}
                    reducedMotion={prefersReducedMotion}
                  />
                  <ExecutionStatus
                    statusText={
                      transcript ? `.....${transcript}` : executionStatus || "Done"
                    }
                    isExecuting={false}
                    reducedMotion={prefersReducedMotion}
                  />
                </>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.button>
    </div>
  );
}

/**
 * Main PEKKA Animated Voice Pill composition component.
 * Accepts optional external integration props (`simulate`, `audioLevels`, `onStateChange`)
 * so real speech recognition and backend events can replace simulated flow seamlessly.
 */
export default function PekkaVoicePill({
  simulate = true,
  successHoldMs,
  audioLevels = null,
  onStateChange,
}) {
  return (
    <StateController
      simulate={simulate}
      successHoldMs={successHoldMs}
      onStateChange={onStateChange}
    >
      {(controller) => (
        <PekkaPillShell
          status={controller.status}
          transcript={controller.transcript}
          executionStatus={controller.executionStatus}
          handlePillClick={controller.handlePillClick}
          audioLevels={audioLevels}
        />
      )}
    </StateController>
  );
}
