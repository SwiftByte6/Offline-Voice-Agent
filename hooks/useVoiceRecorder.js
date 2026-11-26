"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export const WAVEFORM_BAR_COUNT = 44;

export const IDLE_WAVEFORM_LEVELS = [
  0.22, 0.72, 0.44, 0.92, 0.61, 0.34, 0.56, 0.2, 0.78, 0.96,
  0.48, 0.28, 0.64, 0.84, 0.42, 0.31, 0.88, 0.74, 0.52, 0.24,
  0.46, 0.94, 0.68, 0.37, 0.59, 0.81, 0.44, 0.19, 0.33, 0.67,
  0.86, 0.51, 0.29, 0.75, 0.91, 0.57, 0.35, 0.49, 0.79, 0.43,
  0.23, 0.62, 0.41, 0.22,
];

const PREFERRED_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

const METER_FRAME_INTERVAL_MS = 40;
const MIC_REQUEST_TIMEOUT_MS = 10000;

function selectSupportedMimeType() {
  if (
    typeof MediaRecorder === "undefined" ||
    typeof MediaRecorder.isTypeSupported !== "function"
  ) {
    return "";
  }
  for (const mimeType of PREFERRED_MIME_TYPES) {
    if (MediaRecorder.isTypeSupported(mimeType)) {
      return mimeType;
    }
  }
  return "";
}

function mapMicrophoneError(error) {
  const name = error?.name || "";
  const detail = error?.message ? ` (${error.message})` : "";

  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return "Microphone permission denied. Allow mic access and try again.";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "No microphone found. Connect a microphone and try again.";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return `Mic unavailable${detail}. Check Windows Mic Privacy, mute switch, or other mic apps.`;
  }
  if (name === "SecurityError") {
    return "Microphone access requires a secure local context.";
  }
  return error?.message || "Unable to access the microphone.";
}

function requestMicWithTimeout(constraints = { audio: true }) {
  let timeoutId = null;

  const micPromise = navigator.mediaDevices.getUserMedia(constraints);
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = window.setTimeout(() => {
      reject(
        new Error(
          "Microphone request timed out. Check Windows microphone permissions and retry."
        )
      );
    }, MIC_REQUEST_TIMEOUT_MS);
  });

  return Promise.race([micPromise, timeoutPromise]).finally(() => {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
    }
  });
}

async function acquireAudioStream() {
  try {
    return await requestMicWithTimeout({ audio: true });
  } catch (primaryError) {
    const name = primaryError?.name || "";
    if (name !== "NotReadableError" && name !== "TrackStartError") {
      throw primaryError;
    }

    // If the Windows default input fails (e.g. disconnected virtual mic or exclusive lock),
    // try other enumerated audioinput devices before surfacing an error.
    if (typeof navigator.mediaDevices.enumerateDevices === "function") {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const fallbackInputs = devices.filter(
          (device) =>
            device.kind === "audioinput" &&
            device.deviceId &&
            device.deviceId !== "default" &&
            device.deviceId !== "communications"
        );

        for (const device of fallbackInputs) {
          try {
            return await requestMicWithTimeout({
              audio: { deviceId: { exact: device.deviceId } },
            });
          } catch {
            // Try next available audio input device.
          }
        }
      } catch {
        // Fall through to primary error.
      }
    }

    throw primaryError;
  }
}

/**
 * Manages microphone permission, MediaRecorder capture, Web Audio analyser levels,
 * and strict resource cleanup.
 */
export function useVoiceRecorder({ onUnexpectedError } = {}) {
  const [audioLevels, setAudioLevels] = useState(IDLE_WAVEFORM_LEVELS);

  const mediaStreamRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const rafIdRef = useRef(null);
  const chunksRef = useRef([]);
  const isStartingRef = useRef(false);
  const isStoppingRef = useRef(false);
  const lastMeterUpdateRef = useRef(0);
  const onUnexpectedErrorRef = useRef(onUnexpectedError);

  useEffect(() => {
    onUnexpectedErrorRef.current = onUnexpectedError;
  }, [onUnexpectedError]);

  const cleanupAudioResources = useCallback(() => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }

    if (audioContextRef.current) {
      const ctx = audioContextRef.current;
      audioContextRef.current = null;
      analyserRef.current = null;
      if (ctx.state !== "closed") {
        ctx.close().catch(() => {});
      }
    }

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => {
        try {
          track.stop();
        } catch {
          // Ignore track stop errors during teardown.
        }
      });
      mediaStreamRef.current = null;
    }

    mediaRecorderRef.current = null;
    isStartingRef.current = false;
    isStoppingRef.current = false;
    setAudioLevels(IDLE_WAVEFORM_LEVELS);
  }, []);

  useEffect(() => {
    return () => {
      const recorder = mediaRecorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        try {
          recorder.onstop = null;
          recorder.onerror = null;
          recorder.stop();
        } catch {
          // Ignore stop errors on unmount.
        }
      }
      cleanupAudioResources();
    };
  }, [cleanupAudioResources]);

  const startMeterLoop = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;

    const frequencyData = new Uint8Array(analyser.frequencyBinCount);
    const usableBins = Math.min(frequencyData.length, 48);

    const tick = (timestamp) => {
      if (!analyserRef.current) return;

      if (timestamp - lastMeterUpdateRef.current >= METER_FRAME_INTERVAL_MS) {
        lastMeterUpdateRef.current = timestamp;
        analyser.getByteFrequencyData(frequencyData);

        const nextLevels = new Array(WAVEFORM_BAR_COUNT);
        for (let i = 0; i < WAVEFORM_BAR_COUNT; i += 1) {
          const mirroredIdx =
            i < WAVEFORM_BAR_COUNT / 2 ? i : WAVEFORM_BAR_COUNT - 1 - i;
          const binIndex = Math.min(
            usableBins - 1,
            Math.floor(
              (mirroredIdx / (WAVEFORM_BAR_COUNT / 2)) * usableBins * 0.75
            ) + 1
          );
          const raw = frequencyData[binIndex] / 255;
          const shaped = Math.min(1, Math.max(0.12, Math.pow(raw, 0.78) * 1.15));
          nextLevels[i] = Number(shaped.toFixed(3));
        }

        setAudioLevels(nextLevels);
      }

      rafIdRef.current = requestAnimationFrame(tick);
    };

    lastMeterUpdateRef.current = 0;
    rafIdRef.current = requestAnimationFrame(tick);
  }, []);

  const startRecording = useCallback(async () => {
    if (isStartingRef.current) {
      return false;
    }

    if (mediaRecorderRef.current) {
      if (mediaRecorderRef.current.state !== "inactive") {
        return false;
      }
      cleanupAudioResources();
    }

    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices ||
      typeof navigator.mediaDevices.getUserMedia !== "function"
    ) {
      throw new Error("Microphone capture is not supported in this environment.");
    }

    if (typeof MediaRecorder === "undefined") {
      throw new Error("Audio recording (MediaRecorder) is unavailable.");
    }

    isStartingRef.current = true;
    chunksRef.current = [];

    try {
      const stream = await acquireAudioStream();
      mediaStreamRef.current = stream;

      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (AudioCtx) {
          const audioContext = new AudioCtx();
          if (audioContext.state === "suspended") {
            await audioContext.resume().catch(() => {});
          }
          const source = audioContext.createMediaStreamSource(stream);
          const analyser = audioContext.createAnalyser();
          analyser.fftSize = 128;
          analyser.smoothingTimeConstant = 0.72;
          source.connect(analyser);

          audioContextRef.current = audioContext;
          analyserRef.current = analyser;
        }
      } catch {
        audioContextRef.current = null;
        analyserRef.current = null;
      }

      const mimeType = selectSupportedMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onerror = () => {
        cleanupAudioResources();
        onUnexpectedErrorRef.current?.("Audio recording failed unexpectedly.");
      };

      mediaRecorderRef.current = recorder;
      recorder.start(250);
      startMeterLoop();
      isStartingRef.current = false;
      return true;
    } catch (error) {
      cleanupAudioResources();
      throw new Error(mapMicrophoneError(error));
    }
  }, [cleanupAudioResources, startMeterLoop]);

  const stopRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;

    if (!recorder) {
      cleanupAudioResources();
      return Promise.resolve(null);
    }

    if (isStoppingRef.current) {
      return Promise.resolve(null);
    }
    isStoppingRef.current = true;

    return new Promise((resolve, reject) => {
      if (recorder.state === "inactive") {
        const blobType = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type: blobType });
        chunksRef.current = [];
        cleanupAudioResources();
        resolve(blob.size > 0 ? blob : null);
        return;
      }

      recorder.onstop = () => {
        const blobType = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type: blobType });
        chunksRef.current = [];
        cleanupAudioResources();
        resolve(blob.size > 0 ? blob : null);
      };

      recorder.onerror = () => {
        chunksRef.current = [];
        cleanupAudioResources();
        reject(new Error("Failed while finalizing audio recording."));
      };

      try {
        recorder.stop();
      } catch (error) {
        chunksRef.current = [];
        cleanupAudioResources();
        reject(new Error(error?.message || "Unable to stop audio recording."));
      }
    });
  }, [cleanupAudioResources]);

  return {
    audioLevels,
    startRecording,
    stopRecording,
    cleanupAudioResources,
  };
}
