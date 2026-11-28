"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

export const PEKKA_STATES = Object.freeze({
  SLEEPING: "SLEEPING",
  LISTENING: "LISTENING",
  EXECUTING: "EXECUTING",
  SUCCESS: "SUCCESS",
});

export const SUCCESS_HOLD_MS = 1500;

const SIMULATED_SCENARIOS = [
  {
    transcript: "opening the Chrome and search the PEKKA guide",
    executionStatus: "Opening Chrome...",
  },
  {
    transcript: "launch the workspace and check recent changes",
    executionStatus: "Processing request...",
  },
  {
    transcript: "search for Next.js App Router motion transitions",
    executionStatus: "Searching for results...",
  },
];

const INITIAL_STATE = {
  status: PEKKA_STATES.SLEEPING,
  transcript: "",
  executionStatus: "",
  sessionId: 0,
  scenarioIndex: 0,
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
        sessionId: state.sessionId + 1,
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
        state.status !== PEKKA_STATES.LISTENING ||
        action.sessionId !== state.sessionId
      ) {
        return state;
      }
      return {
        ...state,
        status: PEKKA_STATES.EXECUTING,
        executionStatus: action.executionStatus || "Processing request...",
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
      };
    }
    case "SLEEP": {
      if (state.status === PEKKA_STATES.SLEEPING) return state;
      return {
        ...state,
        status: PEKKA_STATES.SLEEPING,
        transcript: "",
        executionStatus: "",
        scenarioIndex: action.advanceScenario
          ? (state.scenarioIndex + 1) % SIMULATED_SCENARIOS.length
          : state.scenarioIndex,
      };
    }
    default:
      return state;
  }
}

/**
 * Single controlled state machine for the PEKKA voice pill:
 * SLEEPING -> LISTENING -> EXECUTING -> SUCCESS -> SLEEPING
 * Supports immediate cancellation back to SLEEPING from LISTENING or EXECUTING,
 * and exposes direct event hooks for real speech/backend integration later.
 */
export function usePekkaState({
  simulate = true,
  successHoldMs = SUCCESS_HOLD_MS,
  onStateChange,
} = {}) {
  const [state, dispatch] = useReducer(pekkaReducer, INITIAL_STATE);

  const timersRef = useRef(new Set());
  const sessionIdRef = useRef(0);
  const statusRef = useRef(state.status);
  const scenarioIndexRef = useRef(state.scenarioIndex);

  useEffect(() => {
    statusRef.current = state.status;
    sessionIdRef.current = state.sessionId;
    scenarioIndexRef.current = state.scenarioIndex;
    onStateChange?.(state.status);
  }, [state.status, state.sessionId, state.scenarioIndex, onStateChange]);

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

  useEffect(() => {
    return () => {
      clearAllTimers();
    };
  }, [clearAllTimers]);

  const scheduleSuccessHold = useCallback(
    (targetSessionId) => {
      scheduleTimer(() => {
        if (sessionIdRef.current !== targetSessionId) return;
        dispatch({ type: "SLEEP", advanceScenario: true });
      }, successHoldMs);
    },
    [scheduleTimer, successHoldMs]
  );

  const runSimulatedFlow = useCallback(
    (targetSessionId, scenario) => {
      const words = scenario.transcript.split(" ");
      let currentWordIndex = 0;

      // Progressive word-by-word reveal after wake-up expansion settles.
      const stepMs = 195;
      const startDelayMs = 460;

      const revealNextWord = () => {
        if (
          sessionIdRef.current !== targetSessionId ||
          statusRef.current !== PEKKA_STATES.LISTENING
        ) {
          return;
        }

        currentWordIndex += 1;
        const partial = words.slice(0, currentWordIndex).join(" ");
        dispatch({
          type: "SET_TRANSCRIPT",
          sessionId: targetSessionId,
          transcript: partial,
        });

        if (currentWordIndex < words.length) {
          scheduleTimer(revealNextWord, stepMs);
        } else {
          // Pause briefly after final word before transitioning to EXECUTING.
          scheduleTimer(() => {
            if (
              sessionIdRef.current !== targetSessionId ||
              statusRef.current !== PEKKA_STATES.LISTENING
            ) {
              return;
            }
            dispatch({
              type: "START_EXECUTING",
              sessionId: targetSessionId,
              executionStatus: scenario.executionStatus,
            });

            // Simulate task execution, then enter SUCCESS for 1500ms.
            scheduleTimer(() => {
              if (
                sessionIdRef.current !== targetSessionId ||
                statusRef.current !== PEKKA_STATES.EXECUTING
              ) {
                return;
              }
              dispatch({
                type: "MARK_SUCCESS",
                sessionId: targetSessionId,
              });
              scheduleSuccessHold(targetSessionId);
            }, 1750);
          }, 680);
        }
      };

      scheduleTimer(revealNextWord, startDelayMs);
    },
    [scheduleTimer, scheduleSuccessHold]
  );

  const activate = useCallback(() => {
    if (statusRef.current !== PEKKA_STATES.SLEEPING) return;

    clearAllTimers();
    const nextSessionId = sessionIdRef.current + 1;
    const scenario =
      SIMULATED_SCENARIOS[scenarioIndexRef.current % SIMULATED_SCENARIOS.length];

    dispatch({ type: "ACTIVATE" });

    if (simulate) {
      runSimulatedFlow(nextSessionId, scenario);
    }
  }, [clearAllTimers, runSimulatedFlow, simulate]);

  const cancel = useCallback(() => {
    if (
      statusRef.current !== PEKKA_STATES.LISTENING &&
      statusRef.current !== PEKKA_STATES.EXECUTING
    ) {
      return;
    }
    clearAllTimers();
    dispatch({ type: "SLEEP", advanceScenario: false });
  }, [clearAllTimers]);

  const handlePillClick = useCallback(() => {
    if (statusRef.current === PEKKA_STATES.SLEEPING) {
      activate();
    } else if (
      statusRef.current === PEKKA_STATES.LISTENING ||
      statusRef.current === PEKKA_STATES.EXECUTING
    ) {
      cancel();
    }
  }, [activate, cancel]);

  // External integration methods for real microphone + backend events.
  const setLiveTranscript = useCallback((transcript) => {
    if (statusRef.current !== PEKKA_STATES.LISTENING) return;
    dispatch({
      type: "SET_TRANSCRIPT",
      sessionId: sessionIdRef.current,
      transcript,
    });
  }, []);

  const finishListening = useCallback(
    (executionStatus = "Processing request...") => {
      if (statusRef.current !== PEKKA_STATES.LISTENING) return;
      clearAllTimers();
      dispatch({
        type: "START_EXECUTING",
        sessionId: sessionIdRef.current,
        executionStatus,
      });
    },
    [clearAllTimers]
  );

  const finishExecution = useCallback(() => {
    if (statusRef.current !== PEKKA_STATES.EXECUTING) return;
    clearAllTimers();
    const activeSessionId = sessionIdRef.current;
    dispatch({
      type: "MARK_SUCCESS",
      sessionId: activeSessionId,
    });
    scheduleSuccessHold(activeSessionId);
  }, [clearAllTimers, scheduleSuccessHold]);

  return {
    status: state.status,
    transcript: state.transcript,
    executionStatus: state.executionStatus,
    sessionId: state.sessionId,
    activate,
    cancel,
    handlePillClick,
    setLiveTranscript,
    finishListening,
    finishExecution,
  };
}
