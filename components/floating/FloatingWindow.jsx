"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { IDLE_WAVEFORM_LEVELS, useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import {
  checkBackendHealth,
  executeVoiceCommand,
  transcribeAudioBlob,
} from "@/lib/speechApi";
import {
  PILL_WINDOW_SIZE,
  enforceFloatingWindowBehavior,
  positionInitialFloatingWindow,
} from "@/lib/tauriWindow";
import GlassSurface from "./GlassSurface";

const INITIAL_STATE = {
  status: "idle", // "idle" | "starting" | "recording" | "processing" | "success" | "error"
  transcript: "",
  transcriptMeta: null,
  actionResult: null,
  errorMessage: "",
};

const COMPACT_WAVE_PROFILE = [
  { index: 3, shape: 0.22 },
  { index: 7, shape: 0.34 },
  { index: 11, shape: 0.52 },
  { index: 15, shape: 0.72 },
  { index: 19, shape: 0.9 },
  { index: 22, shape: 1.0 },
  { index: 25, shape: 0.9 },
  { index: 29, shape: 0.72 },
  { index: 33, shape: 0.52 },
  { index: 37, shape: 0.34 },
  { index: 41, shape: 0.22 },
];

function voiceReducer(state, action) {
  switch (action.type) {
    case "START_MIC":
      return {
        status: "starting",
        transcript: "",
        transcriptMeta: null,
        actionResult: null,
        errorMessage: "",
      };
    case "START_RECORDING":
      return {
        ...state,
        status: "recording",
        errorMessage: "",
      };
    case "START_PROCESSING":
      return {
        ...state,
        status: "processing",
        errorMessage: "",
      };
    case "TRANSCRIBE_SUCCESS":
      return {
        ...state,
        status: "success",
        transcript: action.text,
        transcriptMeta: {
          language: action.language,
          duration: action.duration,
        },
        actionResult: action.actionResult || null,
        errorMessage: "",
      };
    case "SET_ERROR":
      return {
        ...state,
        status: "error",
        errorMessage: action.message,
      };
    case "DISMISS":
      return {
        ...INITIAL_STATE,
      };
    default:
      return state;
  }
}

/**
 * Unified floating voice overlay: starts as a compact circular glass mic button
 * and expands into a small frosted glass pill with cancel, live waveform, and send actions.
 */
export default function FloatingWindow() {
  const [state, dispatch] = useReducer(voiceReducer, INITIAL_STATE);
  const [backendHealth, setBackendHealth] = useState({
    reachable: true,
    ready: false,
    modelStatus: "loading",
  });
  const [hasRetryBlob, setHasRetryBlob] = useState(false);
  const [showTapGuide, setShowTapGuide] = useState(true);

  const lastAudioBlobRef = useRef(null);
  const requestAbortRef = useRef(null);
  const isSubmittingRef = useRef(false);

  const handleRecorderError = useCallback((message) => {
    dispatch({ type: "SET_ERROR", message });
  }, []);

  const { audioLevels, startRecording, stopRecording, cleanupAudioResources } =
    useVoiceRecorder({
      onUnexpectedError: handleRecorderError,
    });

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
      requestAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    let active = true;
    let pollTimerId = null;

    async function pollHealth() {
      const health = await checkBackendHealth();
      if (!active) return;

      setBackendHealth(health);

      if (!health.ready) {
        const delayMs = health.reachable ? 2000 : 5000;
        pollTimerId = window.setTimeout(pollHealth, delayMs);
      }
    }

    pollHealth();

    return () => {
      active = false;
      if (pollTimerId) {
        window.clearTimeout(pollTimerId);
      }
    };
  }, []);

  const submitAudioForTranscription = useCallback(async (audioBlob) => {
    if (!audioBlob || audioBlob.size === 0) {
      lastAudioBlobRef.current = null;
      setHasRetryBlob(false);
      dispatch({
        type: "SET_ERROR",
        message: "No audio captured. Try speaking again.",
      });
      return;
    }

    if (isSubmittingRef.current) return;
    isSubmittingRef.current = true;

    lastAudioBlobRef.current = audioBlob;
    setHasRetryBlob(true);
    dispatch({ type: "START_PROCESSING" });

    requestAbortRef.current?.abort();
    const controller = new AbortController();
    requestAbortRef.current = controller;

    try {
      const result = await transcribeAudioBlob(audioBlob, {
        signal: controller.signal,
      });

      lastAudioBlobRef.current = null;
      setHasRetryBlob(false);
      setBackendHealth((prev) => ({
        ...prev,
        reachable: true,
        ready: true,
        modelStatus: "ready",
      }));

      let actionResult = null;
      if (result.text) {
        try {
          actionResult = await executeVoiceCommand(result.text, {
            signal: controller.signal,
          });
        } catch (actionError) {
          if (actionError?.name === "AbortError") return;
          actionResult = {
            success: false,
            action: "error",
            executed: false,
            message: actionError?.message || "Voice action failed.",
          };
        }
      }

      dispatch({
        type: "TRANSCRIBE_SUCCESS",
        text: result.text,
        language: result.language,
        duration: result.duration,
        actionResult,
      });
    } catch (error) {
      if (error?.name === "AbortError") return;
      dispatch({
        type: "SET_ERROR",
        message: error?.message || "Failed to transcribe recording.",
      });
    } finally {
      isSubmittingRef.current = false;
      if (requestAbortRef.current === controller) {
        requestAbortRef.current = null;
      }
    }
  }, []);

  const handleStopAndTranscribe = useCallback(async () => {
    if (state.status !== "recording" || isSubmittingRef.current) return;

    try {
      const audioBlob = await stopRecording();
      await submitAudioForTranscription(audioBlob);
    } catch (error) {
      dispatch({
        type: "SET_ERROR",
        message: error?.message || "Could not finalize audio recording.",
      });
    }
  }, [state.status, stopRecording, submitAudioForTranscription]);

  const handleStartRecording = useCallback(async () => {
    if (
      state.status === "starting" ||
      state.status === "recording" ||
      state.status === "processing"
    ) {
      return;
    }

    lastAudioBlobRef.current = null;
    setHasRetryBlob(false);
    setShowTapGuide(false);
    dispatch({ type: "START_MIC" });

    try {
      const started = await startRecording();
      if (started) {
        dispatch({ type: "START_RECORDING" });
      } else {
        dispatch({
          type: "SET_ERROR",
          message: "Microphone is busy. Please try again.",
        });
      }
    } catch (error) {
      dispatch({
        type: "SET_ERROR",
        message: error?.message || "Unable to start microphone recording.",
      });
    }
  }, [state.status, startRecording]);

  const handleRetry = useCallback(() => {
    if (state.status !== "error" || !lastAudioBlobRef.current) return;
    submitAudioForTranscription(lastAudioBlobRef.current);
  }, [state.status, submitAudioForTranscription]);

  const handleSendAction = useCallback(() => {
    if (state.status === "recording") {
      handleStopAndTranscribe();
    } else if (state.status === "error" && lastAudioBlobRef.current) {
      handleRetry();
    } else if (state.status === "success") {
      handleStartRecording();
    }
  }, [state.status, handleStopAndTranscribe, handleRetry, handleStartRecording]);

  const handleDismiss = useCallback(() => {
    requestAbortRef.current?.abort();
    requestAbortRef.current = null;
    isSubmittingRef.current = false;
    cleanupAudioResources();
    lastAudioBlobRef.current = null;
    setHasRetryBlob(false);
    dispatch({ type: "DISMISS" });
  }, [cleanupAudioResources]);

  const stopDrag = (event) => {
    event.stopPropagation();
  };

  const isIdle = state.status === "idle";
  const isStarting = state.status === "starting";
  const isRecording = state.status === "recording";
  const isProcessing = state.status === "processing";
  const isSuccess = state.status === "success";
  const isError = state.status === "error";

  const canSendAction =
    isRecording || (isError && hasRetryBlob) || isSuccess;

  const backendNotice = !backendHealth.reachable
    ? "Speech engine offline"
    : backendHealth.modelStatus === "loading"
      ? "Loading speech model..."
      : "Start voice recording";

  const pillWidth = isSuccess || isError ? 308 : 224;
  const pillHeight = isSuccess || isError ? 58 : 52;
  const pillRadius = pillHeight / 2;

  return (
    <main className="flex h-screen w-screen items-center justify-center bg-transparent">
      {isIdle ? (
        <div className="flex flex-col items-center gap-1.5">
          {showTapGuide && (
            <button
              type="button"
              onClick={handleStartRecording}
              className="cursor-pointer rounded-full border border-white/60 bg-white/65 px-2.5 py-0.5 text-[11px] font-medium tracking-tight text-neutral-900 shadow-sm backdrop-blur-md transition-all duration-150 hover:bg-white/80"
            >
              Tap to speech
            </button>
          )}
          <GlassSurface
            width={52}
            height={52}
            borderRadius={26}
            borderWidth={0.08}
            brightness={50}
            opacity={0.93}
            blur={10}
            displace={0.5}
            backgroundOpacity={0.2}
            saturation={1.2}
            distortionScale={-180}
            redOffset={0}
            greenOffset={10}
            blueOffset={20}
            className="transition-transform duration-200 ease-out hover:scale-105 active:scale-95"
          >
            <span
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 rounded-[inherit]"
              style={{
                background: "rgba(255, 255, 255, 0.5)",
                border: "1px solid rgba(255, 255, 255, 0.65)",
              }}
            />
            <button
              type="button"
              onClick={handleStartRecording}
              aria-label={backendNotice}
              title={backendNotice}
              className="relative z-10 flex h-full w-full cursor-pointer items-center justify-center rounded-full text-neutral-900 outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/40"
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.1"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <rect x="9" y="2.8" width="6" height="11.2" rx="3" fill="currentColor" stroke="none" />
                <path d="M5.5 10.8a6.5 6.5 0 0 0 13 0" />
                <path d="M12 17.5v3.5" />
                <path d="M8.8 21h6.4" />
              </svg>
              {(!backendHealth.reachable || backendHealth.modelStatus === "loading") && (
                <span
                  aria-hidden="true"
                  className={`absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full ${
                    !backendHealth.reachable
                      ? "bg-rose-500"
                      : "animate-pulse bg-amber-500"
                  }`}
                />
              )}
            </button>
          </GlassSurface>
        </div>
      ) : (
        <GlassSurface
          width={pillWidth}
          height={pillHeight}
          borderRadius={pillRadius}
          borderWidth={0.07}
          brightness={50}
          opacity={0.93}
          blur={11}
          displace={0.5}
          backgroundOpacity={0.22}
          saturation={1.2}
          distortionScale={-180}
          redOffset={0}
          greenOffset={10}
          blueOffset={20}
          data-tauri-drag-region
          role="region"
          aria-label="NOVA voice pill"
          className="max-w-[calc(100vw-24px)] cursor-grab transition-[width,height] duration-200 ease-out active:cursor-grabbing"
        >
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 rounded-[inherit]"
            style={{
              background: "rgba(255, 255, 255, 0.5)",
              border: "1px solid rgba(255, 255, 255, 0.65)",
            }}
          />
          <div
            data-tauri-drag-region
            className="relative z-10 flex h-full w-full items-center justify-between gap-2.5"
          >
            <button
              type="button"
              onClick={handleDismiss}
              onMouseDown={stopDrag}
              onPointerDown={stopDrag}
              aria-label={isRecording ? "Cancel recording" : "Close voice pill"}
              className="flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full bg-neutral-950 text-white shadow-sm transition-transform duration-150 hover:scale-105 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/50"
            >
              <svg
                width="14"
                height="14"
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

            {isSuccess ? (
              <div
                onMouseDown={stopDrag}
                onPointerDown={stopDrag}
                className="flex max-h-[44px] min-w-0 flex-1 cursor-text select-text flex-col justify-center overflow-y-auto px-1"
                title={
                  state.actionResult?.screenText ||
                  state.actionResult?.message ||
                  state.transcript ||
                  "No speech detected"
                }
              >
                {state.actionResult &&
                  state.actionResult.action !== "dictate" && (
                    <span
                      className={`truncate text-[10px] font-semibold tracking-tight ${
                        state.actionResult.success
                          ? "text-emerald-800"
                          : "text-rose-700"
                      }`}
                    >
                      {state.actionResult.matchedBy === "gemini"
                        ? state.actionResult.message
                        : state.actionResult.executed && state.actionResult.target
                          ? `${state.actionResult.action}: ${state.actionResult.target} (${state.actionResult.matchedBy})`
                          : state.actionResult.message}
                    </span>
                  )}
                <span className="text-[12.5px] leading-[1.25] font-medium text-neutral-900">
                  {state.actionResult?.screenText &&
                  state.actionResult?.matchedBy === "gemini"
                    ? state.actionResult.screenText
                    : state.transcript || "No speech detected."}
                </span>
              </div>
            ) : isError ? (
              <p
                data-tauri-drag-region
                className="pointer-events-none line-clamp-2 min-w-0 flex-1 px-1 text-[11.5px] leading-[1.25] font-medium text-rose-700"
                title={state.errorMessage}
              >
                {state.errorMessage}
              </p>
            ) : (
              <div
                data-tauri-drag-region
                aria-hidden="true"
                className="pointer-events-none flex min-w-0 flex-1 items-center justify-center"
                style={{ height: "28px", gap: "5px" }}
              >
                {COMPACT_WAVE_PROFILE.map(({ index, shape }, barIdx) => {
                  const sourceLevel = isRecording
                    ? audioLevels[index] ?? 0.14
                    : IDLE_WAVEFORM_LEVELS[index] ?? 0.25;
                  const baseRest = 0.12 + shape * 0.22;
                  const scaleY = isRecording
                    ? Math.min(1, Math.max(0.12, baseRest + shape * sourceLevel * 0.72))
                    : Math.min(1, Math.max(0.12, baseRest + (isStarting || isProcessing ? 0.1 : 0.18)));

                  return (
                    <span
                      key={barIdx}
                      className={`shrink-0 rounded-full transition-transform duration-75 ease-out ${
                        isStarting || isProcessing ? "animate-pulse opacity-65" : ""
                      }`}
                      style={{
                        display: "block",
                        width: "3px",
                        height: "26px",
                        backgroundColor: "rgba(17, 24, 39, 0.88)",
                        transformOrigin: "center",
                        transform: `scaleY(${scaleY.toFixed(3)})`,
                      }}
                    />
                  );
                })}
              </div>
            )}

            <button
              type="button"
              onClick={handleSendAction}
              onMouseDown={stopDrag}
              onPointerDown={stopDrag}
              disabled={!canSendAction}
              aria-label={
                isRecording
                  ? "Stop and transcribe"
                  : isError && hasRetryBlob
                    ? "Retry transcription"
                    : isSuccess
                      ? "Record again"
                      : isStarting
                        ? "Starting microphone"
                        : "Transcribing audio"
              }
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-white/60 bg-white/55 text-neutral-900 shadow-sm transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/40 ${
                canSendAction
                  ? "cursor-pointer hover:scale-105 hover:bg-white/75 active:scale-95"
                  : "cursor-default opacity-60"
              }`}
            >
              {isStarting || isProcessing ? (
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                  className="animate-spin"
                >
                  <circle
                    cx="12"
                    cy="12"
                    r="8"
                    stroke="currentColor"
                    strokeOpacity="0.25"
                    strokeWidth="2.4"
                  />
                  <path
                    d="M20 12a8 8 0 0 0-8-8"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                  />
                </svg>
              ) : isSuccess ? (
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.1"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <rect x="9" y="2.8" width="6" height="11.2" rx="3" fill="currentColor" stroke="none" />
                  <path d="M5.5 10.8a6.5 6.5 0 0 0 13 0" />
                  <path d="M12 17.5v3.5" />
                  <path d="M8.8 21h6.4" />
                </svg>
              ) : isError && hasRetryBlob ? (
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M21 12a9 9 0 1 1-2.64-6.36" />
                  <path d="M21 3v6h-6" />
                </svg>
              ) : (
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 19V5" />
                  <path d="m6.5 10.5 5.5-5.5 5.5 5.5" />
                </svg>
              )}
            </button>
          </div>
        </GlassSurface>
      )}
    </main>
  );
}
