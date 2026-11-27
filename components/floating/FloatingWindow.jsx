"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { checkBackendHealth, transcribeAudioBlob } from "@/lib/speechApi";
import {
  PILL_WINDOW_SIZE,
  enforceFloatingWindowBehavior,
  positionInitialFloatingWindow,
} from "@/lib/tauriWindow";
import VoicePill from "./VoicePill";

const INITIAL_STATE = {
  status: "idle", // "idle" | "starting" | "recording" | "processing" | "success" | "error"
  elapsedSeconds: 0,
  transcript: "",
  transcriptMeta: null,
  errorMessage: "",
};

function voiceReducer(state, action) {
  switch (action.type) {
    case "START_MIC":
      return {
        status: "starting",
        elapsedSeconds: 0,
        transcript: "",
        transcriptMeta: null,
        errorMessage: "",
      };
    case "START_RECORDING":
      return {
        ...state,
        status: "recording",
        elapsedSeconds: 0,
        errorMessage: "",
      };
    case "TICK_TIMER":
      if (state.status !== "recording") return state;
      return {
        ...state,
        elapsedSeconds: state.elapsedSeconds + 1,
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
 * Top-level floating voice overlay controller.
 * Coordinates microphone capture, FastAPI Qwen3-ASR transcription, and Tauri window setup.
 */
export default function FloatingWindow() {
  const [state, dispatch] = useReducer(voiceReducer, INITIAL_STATE);
  const [backendHealth, setBackendHealth] = useState({
    reachable: true,
    ready: false,
    modelStatus: "loading",
  });
  const [hasRetryBlob, setHasRetryBlob] = useState(false);

  const lastAudioBlobRef = useRef(null);
  const requestAbortRef = useRef(null);
  const isSubmittingRef = useRef(false);

  const handleRecorderError = useCallback((message) => {
    dispatch({ type: "SET_ERROR", message });
  }, []);

  const { audioLevels, startRecording, stopRecording } = useVoiceRecorder({
    onUnexpectedError: handleRecorderError,
  });

  // Initialize native Tauri floating window behavior once on mount
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

  // Poll backend health lightly until model is ready (and recover if backend starts later)
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

  // Recording elapsed timer
  useEffect(() => {
    if (state.status !== "recording") return undefined;

    const intervalId = window.setInterval(() => {
      dispatch({ type: "TICK_TIMER" });
    }, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [state.status]);

  const submitAudioForTranscription = useCallback(async (audioBlob) => {
    if (!audioBlob || audioBlob.size === 0) {
      lastAudioBlobRef.current = null;
      setHasRetryBlob(false);
      dispatch({
        type: "SET_ERROR",
        message: "No audio captured. Hold a moment and try speaking again.",
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

      dispatch({
        type: "TRANSCRIBE_SUCCESS",
        text: result.text,
        language: result.language,
        duration: result.duration,
      });
    } catch (error) {
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

  const handlePrimaryAction = useCallback(() => {
    if (state.status === "recording") {
      handleStopAndTranscribe();
    } else if (state.status !== "starting" && state.status !== "processing") {
      handleStartRecording();
    }
  }, [state.status, handleStopAndTranscribe, handleStartRecording]);

  const handleRetry = useCallback(() => {
    if (state.status !== "error" || !lastAudioBlobRef.current) return;
    submitAudioForTranscription(lastAudioBlobRef.current);
  }, [state.status, submitAudioForTranscription]);

  const handleSendAction = useCallback(() => {
    if (state.status === "recording") {
      handleStopAndTranscribe();
    } else if (state.status === "error" && lastAudioBlobRef.current) {
      handleRetry();
    }
  }, [state.status, handleStopAndTranscribe, handleRetry]);

  const handleDismiss = useCallback(() => {
    lastAudioBlobRef.current = null;
    setHasRetryBlob(false);
    dispatch({ type: "DISMISS" });
  }, []);

  return (
    <main className="flex h-screen w-screen items-center justify-center bg-transparent">
      <VoicePill
        status={state.status}
        audioLevels={audioLevels}
        elapsedSeconds={state.elapsedSeconds}
        transcript={state.transcript}
        transcriptMeta={state.transcriptMeta}
        errorMessage={state.errorMessage}
        canRetry={hasRetryBlob}
        backendHealth={backendHealth}
        onPrimaryAction={handlePrimaryAction}
        onSendAction={handleSendAction}
        onRetry={handleRetry}
        onDismiss={handleDismiss}
      />
    </main>
  );
}
