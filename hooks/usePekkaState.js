"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { checkBackendHealth, transcribeAudioBlob } from "@/lib/speechApi";

export const PEKKA_STATES = Object.freeze({
  SLEEPING: "SLEEPING",
  LISTENING: "LISTENING",
  EXECUTING: "EXECUTING",
  SUCCESS: "SUCCESS",
  ERROR: "ERROR",
});

export const SUCCESS_HOLD_MS = 2400;

const INITIAL_STATE = {
  status: PEKKA_STATES.SLEEPING,
  transcript: "",
  executionStatus: "",
  errorMessage: "",
  isStartingMic: false,
  sessionId: 0,
};

function pekkaReducer(state, action) {
  switch (action.type) {
    case "ACTIVATE": {
      if (state.status !== PEKKA_STATES.SLEEPING) return state;
      return {
        ...state,
        status: PEKKA_STATES.LISTENING,
        transcript: "",
        executionStatus: "",
        errorMessage: "",
        isStartingMic: true,
        sessionId: action.sessionId,
      };
    }
    case "MIC_READY": {
      if (
        state.status !== PEKKA_STATES.LISTENING ||
        action.sessionId !== state.sessionId
      ) {
        return state;
      }
      return {
        ...state,
        isStartingMic: false,
      };
    }
    case "SET_TRANSCRIPT": {
      if (
        state.status !== PEKKA_STATES.LISTENING ||
        action.sessionId !== state.sessionId
      ) {
        return state;
      }
      return {
        ...state,
        transcript: action.transcript,
      };
    }
    case "START_EXECUTING": {
      if (
        (state.status !== PEKKA_STATES.LISTENING &&
          state.status !== PEKKA_STATES.EXECUTING &&
          state.status !== PEKKA_STATES.ERROR) ||
        action.sessionId !== state.sessionId
      ) {
        return state;
      }
      return {
        ...state,
        status: PEKKA_STATES.EXECUTING,
        isStartingMic: false,
        errorMessage: "",
        executionStatus: action.executionStatus || "Transcribing...",
      };
    }
    case "MARK_SUCCESS": {
      if (
        state.status !== PEKKA_STATES.EXECUTING ||
        action.sessionId !== state.sessionId
      ) {
        return state;
      }
      return {
        ...state,
        status: PEKKA_STATES.SUCCESS,
        transcript: action.transcript ?? state.transcript,
        executionStatus: "",
        errorMessage: "",
      };
    }
    case "SET_ERROR": {
      if (
        state.status === PEKKA_STATES.SLEEPING ||
        action.sessionId !== state.sessionId
      ) {
        return state;
      }
      return {
        ...state,
        status: PEKKA_STATES.ERROR,
        isStartingMic: false,
        executionStatus: "",
        errorMessage: action.message || "Speech recognition failed.",
      };
    }
    case "SLEEP": {
      if (state.status === PEKKA_STATES.SLEEPING) return state;
      return {
        ...state,
        status: PEKKA_STATES.SLEEPING,
        transcript: "",
        executionStatus: "",
        errorMessage: "",
        isStartingMic: false,
      };
    }
    default:
      return state;
  }
}

/**
 * Controlled state machine for the PEKKA voice pill backed by real microphone
 * capture (`useVoiceRecorder`) and the local FastAPI Qwen3-ASR backend (`/api/transcribe`).
 */
export function usePekkaState({
  successHoldMs = SUCCESS_HOLD_MS,
  onStateChange,
  onTranscript,
} = {}) {
  const [state, dispatch] = useReducer(pekkaReducer, INITIAL_STATE);
  const [backendHealth, setBackendHealth] = useState({
    reachable: true,
    ready: false,
    modelStatus: "loading",
    model: null,
    error: null,
  });
  const [hasRetryBlob, setHasRetryBlob] = useState(false);

  const timersRef = useRef(new Set());
  const activeSessionIdRef = useRef(0);
  const statusRef = useRef(state.status);
  const isStartingMicRef = useRef(false);
  const isSubmittingRef = useRef(false);
  const lastAudioBlobRef = useRef(null);
  const requestAbortRef = useRef(null);
  const healthPollTimerRef = useRef(null);
  const isMountedRef = useRef(true);
  const onTranscriptRef = useRef(onTranscript);

  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  }, [onTranscript]);

  useEffect(() => {
    statusRef.current = state.status;
    onStateChange?.(state.status);
  }, [state.status, onStateChange]);

  const handleRecorderError = useCallback((message) => {
    if (statusRef.current !== PEKKA_STATES.LISTENING) return;
    isStartingMicRef.current = false;
    dispatch({
      type: "SET_ERROR",
      sessionId: activeSessionIdRef.current,
      message,
    });
  }, []);

  const { audioLevels, startRecording, stopRecording, cleanupAudioResources } =
    useVoiceRecorder({
      onUnexpectedError: handleRecorderError,
    });

  const clearAllTimers = useCallback(() => {
    timersRef.current.forEach((timerId) => {
      window.clearTimeout(timerId);
    });
    timersRef.current.clear();
  }, []);

  const scheduleTimer = useCallback((fn, delayMs) => {
    const timerId = window.setTimeout(() => {
      timersRef.current.delete(timerId);
      fn();
    }, delayMs);
    timersRef.current.add(timerId);
    return timerId;
  }, []);

  const scheduleHealthPoll = useCallback((delayMs) => {
    if (healthPollTimerRef.current !== null) {
      window.clearTimeout(healthPollTimerRef.current);
    }

    const scheduleNext = (nextDelayMs) => {
      healthPollTimerRef.current = window.setTimeout(async () => {
        healthPollTimerRef.current = null;
        const health = await checkBackendHealth();
        if (!isMountedRef.current) return;
        setBackendHealth(health);
        if (!health.ready) {
          scheduleNext(health.reachable ? 2000 : 5000);
        }
      }, nextDelayMs);
    };

    scheduleNext(delayMs);
  }, []);

  useEffect(() => {
    isMountedRef.current = true;

    async function initHealthCheck() {
      const health = await checkBackendHealth();
      if (!isMountedRef.current) return;
      setBackendHealth(health);
      if (!health.ready) {
        scheduleHealthPoll(health.reachable ? 2000 : 5000);
      }
    }

    initHealthCheck();

    return () => {
      isMountedRef.current = false;
      clearAllTimers();
      requestAbortRef.current?.abort();
      if (healthPollTimerRef.current !== null) {
        window.clearTimeout(healthPollTimerRef.current);
        healthPollTimerRef.current = null;
      }
    };
  }, [clearAllTimers, scheduleHealthPoll]);

  const scheduleSuccessHold = useCallback(
    (targetSessionId) => {
      scheduleTimer(() => {
        if (activeSessionIdRef.current !== targetSessionId) return;
        dispatch({ type: "SLEEP" });
      }, successHoldMs);
    },
    [scheduleTimer, successHoldMs]
  );

  const submitAudioForTranscription = useCallback(
    async (audioBlob, targetSessionId) => {
      if (!audioBlob || audioBlob.size === 0) {
        lastAudioBlobRef.current = null;
        setHasRetryBlob(false);
        dispatch({
          type: "SET_ERROR",
          sessionId: targetSessionId,
          message: "No audio captured. Try speaking again.",
        });
        return;
      }

      lastAudioBlobRef.current = audioBlob;
      setHasRetryBlob(true);
      dispatch({
        type: "START_EXECUTING",
        sessionId: targetSessionId,
        executionStatus: "Transcribing...",
      });

      requestAbortRef.current?.abort();
      const controller = new AbortController();
      requestAbortRef.current = controller;

      try {
        const result = await transcribeAudioBlob(audioBlob, {
          signal: controller.signal,
        });

        if (
          controller.signal.aborted ||
          activeSessionIdRef.current !== targetSessionId
        ) {
          return;
        }

        lastAudioBlobRef.current = null;
        setHasRetryBlob(false);
        setBackendHealth((prev) => ({
          ...prev,
          reachable: true,
          ready: true,
          modelStatus: "ready",
          error: null,
        }));

        const finalText = result.text || "No speech detected.";
        dispatch({
          type: "MARK_SUCCESS",
          sessionId: targetSessionId,
          transcript: finalText,
        });
        onTranscriptRef.current?.(result);
        scheduleSuccessHold(targetSessionId);
      } catch (error) {
        if (
          controller.signal.aborted ||
          activeSessionIdRef.current !== targetSessionId
        ) {
          return;
        }
        scheduleHealthPoll(200);
        dispatch({
          type: "SET_ERROR",
          sessionId: targetSessionId,
          message: error?.message || "Failed to transcribe recording.",
        });
      } finally {
        if (requestAbortRef.current === controller) {
          requestAbortRef.current = null;
        }
      }
    },
    [scheduleHealthPoll, scheduleSuccessHold]
  );

  const activate = useCallback(async () => {
    if (
      statusRef.current !== PEKKA_STATES.SLEEPING ||
      isStartingMicRef.current ||
      isSubmittingRef.current
    ) {
      return;
    }

    clearAllTimers();
    isStartingMicRef.current = true;
    lastAudioBlobRef.current = null;
    setHasRetryBlob(false);

    const targetSessionId = activeSessionIdRef.current + 1;
    activeSessionIdRef.current = targetSessionId;
    dispatch({ type: "ACTIVATE", sessionId: targetSessionId });

    try {
      const started = await startRecording();
      isStartingMicRef.current = false;

      if (activeSessionIdRef.current !== targetSessionId) {
        cleanupAudioResources();
        return;
      }

      if (!started) {
        dispatch({
          type: "SET_ERROR",
          sessionId: targetSessionId,
          message: "Microphone is busy. Please try again.",
        });
        return;
      }

      dispatch({ type: "MIC_READY", sessionId: targetSessionId });
    } catch (error) {
      isStartingMicRef.current = false;
      if (activeSessionIdRef.current !== targetSessionId) {
        cleanupAudioResources();
        return;
      }
      dispatch({
        type: "SET_ERROR",
        sessionId: targetSessionId,
        message: error?.message || "Unable to start microphone recording.",
      });
    }
  }, [cleanupAudioResources, clearAllTimers, startRecording]);

  const stopAndTranscribe = useCallback(async () => {
    if (
      statusRef.current !== PEKKA_STATES.LISTENING ||
      isStartingMicRef.current ||
      isSubmittingRef.current
    ) {
      return;
    }

    const targetSessionId = activeSessionIdRef.current;
    isSubmittingRef.current = true;
    dispatch({
      type: "START_EXECUTING",
      sessionId: targetSessionId,
      executionStatus: "Finalizing audio...",
    });

    try {
      const audioBlob = await stopRecording();
      if (activeSessionIdRef.current !== targetSessionId) {
        return;
      }
      await submitAudioForTranscription(audioBlob, targetSessionId);
    } catch (error) {
      if (activeSessionIdRef.current !== targetSessionId) {
        return;
      }
      dispatch({
        type: "SET_ERROR",
        sessionId: targetSessionId,
        message: error?.message || "Could not finalize audio recording.",
      });
    } finally {
      isSubmittingRef.current = false;
    }
  }, [stopRecording, submitAudioForTranscription]);

  const retry = useCallback(async () => {
    if (
      statusRef.current !== PEKKA_STATES.ERROR ||
      !lastAudioBlobRef.current ||
      isSubmittingRef.current
    ) {
      return;
    }

    const targetSessionId = activeSessionIdRef.current;
    isSubmittingRef.current = true;
    try {
      await submitAudioForTranscription(lastAudioBlobRef.current, targetSessionId);
    } finally {
      isSubmittingRef.current = false;
    }
  }, [submitAudioForTranscription]);

  const cancel = useCallback(() => {
    activeSessionIdRef.current += 1;
    clearAllTimers();
    requestAbortRef.current?.abort();
    requestAbortRef.current = null;
    isStartingMicRef.current = false;
    isSubmittingRef.current = false;
    cleanupAudioResources();
    lastAudioBlobRef.current = null;
    setHasRetryBlob(false);
    dispatch({ type: "SLEEP" });
  }, [cleanupAudioResources, clearAllTimers]);

  const handlePillClick = useCallback(() => {
    switch (statusRef.current) {
      case PEKKA_STATES.SLEEPING:
        activate();
        break;
      case PEKKA_STATES.LISTENING:
        if (!isStartingMicRef.current) {
          stopAndTranscribe();
        }
        break;
      case PEKKA_STATES.EXECUTING:
      case PEKKA_STATES.SUCCESS:
        cancel();
        break;
      case PEKKA_STATES.ERROR:
        if (lastAudioBlobRef.current) {
          retry();
        } else {
          cancel();
        }
        break;
      default:
        break;
    }
  }, [activate, cancel, retry, stopAndTranscribe]);

  return {
    status: state.status,
    transcript: state.transcript,
    executionStatus: state.executionStatus,
    errorMessage: state.errorMessage,
    isStartingMic: state.isStartingMic,
    sessionId: state.sessionId,
    audioLevels,
    backendHealth,
    hasRetryBlob,
    activate,
    stopAndTranscribe,
    retry,
    cancel,
    handlePillClick,
  };
}
