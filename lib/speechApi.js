const DEFAULT_SPEECH_API_URL = "http://127.0.0.1:8000";

export function getSpeechApiBaseUrl() {
  const configured = process.env.NEXT_PUBLIC_SPEECH_API_URL;
  const base =
    configured && configured.trim()
      ? configured.trim()
      : DEFAULT_SPEECH_API_URL;
  return base.replace(/\/+$/, "");
}

function extensionForMimeType(mimeType = "") {
  const clean = mimeType.split(";")[0].trim().toLowerCase();
  const map = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/flac": "flac",
  };
  return map[clean] || "webm";
}

function createTimeoutSignal(timeoutMs, externalSignal) {
  const controller = new AbortController();
  const timerId = window.setTimeout(() => controller.abort(), timeoutMs);

  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }

  return {
    signal: controller.signal,
    cleanup: () => {
      window.clearTimeout(timerId);
      if (externalSignal) {
        externalSignal.removeEventListener("abort", onExternalAbort);
      }
    },
  };
}

/**
 * Checks whether the local FastAPI Qwen3-ASR backend is reachable and ready.
 */
export async function checkBackendHealth({ timeoutMs = 4000, signal } = {}) {
  const baseUrl = getSpeechApiBaseUrl();
  const { signal: combinedSignal, cleanup } = createTimeoutSignal(
    timeoutMs,
    signal
  );

  try {
    const response = await fetch(`${baseUrl}/health`, {
      method: "GET",
      signal: combinedSignal,
      cache: "no-store",
    });

    if (!response.ok) {
      return {
        reachable: true,
        ready: false,
        modelStatus: "error",
        model: null,
        error: `Speech backend returned HTTP ${response.status}.`,
      };
    }

    const data = await response.json();
    return {
      reachable: true,
      ready: Boolean(data.ready),
      modelStatus: data.model_status || "unknown",
      model: data.model || null,
      error: data.error || null,
    };
  } catch (error) {
    if (error?.name === "AbortError") {
      return {
        reachable: false,
        ready: false,
        modelStatus: "offline",
        model: null,
        error: "Timed out connecting to speech backend.",
      };
    }

    return {
      reachable: false,
      ready: false,
      modelStatus: "offline",
      model: null,
      error: `Cannot reach speech backend at ${baseUrl}.`,
    };
  } finally {
    cleanup();
  }
}

/**
 * Uploads a recorded audio Blob to POST /api/transcribe and returns the transcript payload.
 */
export async function transcribeAudioBlob(
  blob,
  { filename, timeoutMs = 120000, signal } = {}
) {
  if (!blob || blob.size === 0) {
    throw new Error("Recorded audio is empty. Please try speaking again.");
  }

  const baseUrl = getSpeechApiBaseUrl();
  const ext = extensionForMimeType(blob.type);
  const uploadName = filename || `nova_recording.${ext}`;

  const formData = new FormData();
  formData.append("file", blob, uploadName);

  const { signal: combinedSignal, cleanup } = createTimeoutSignal(
    timeoutMs,
    signal
  );

  try {
    const response = await fetch(`${baseUrl}/api/transcribe`, {
      method: "POST",
      body: formData,
      signal: combinedSignal,
    });

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (!response.ok) {
      const detail =
        payload?.detail ||
        payload?.error ||
        `Transcription failed (HTTP ${response.status}).`;
      throw new Error(detail);
    }

    return {
      success: Boolean(payload?.success ?? true),
      text: typeof payload?.text === "string" ? payload.text.trim() : "",
      language: payload?.language || null,
      duration: typeof payload?.duration === "number" ? payload.duration : 0,
    };
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("Transcription request timed out or was cancelled.");
    }
    if (error instanceof TypeError) {
      throw new Error(
        `Cannot connect to speech backend at ${baseUrl}. Start the Python engine and retry.`
      );
    }
    throw error;
  } finally {
    cleanup();
  }
}

/**
 * Sends a transcribed voice command to POST /api/voice-act for UIA/OCR grounding and execution.
 */
export async function executeVoiceCommand(
  command,
  { execute = true, timeoutMs = 15000, signal } = {}
) {
  const trimmed = typeof command === "string" ? command.trim() : "";
  if (!trimmed) {
    return {
      success: true,
      action: "dictate",
      executed: false,
      target: null,
      matchedBy: null,
      coordinates: null,
      message: "",
      screenText: null,
    };
  }

  const baseUrl = getSpeechApiBaseUrl();
  const { signal: combinedSignal, cleanup } = createTimeoutSignal(
    timeoutMs,
    signal
  );

  try {
    const response = await fetch(`${baseUrl}/api/voice-act`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: trimmed, execute }),
      signal: combinedSignal,
    });

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (!response.ok) {
      const detail =
        payload?.detail ||
        payload?.error ||
        `Voice command failed (HTTP ${response.status}).`;
      throw new Error(detail);
    }

    return {
      success: Boolean(payload?.success),
      action: payload?.action || "dictate",
      executed: Boolean(payload?.executed),
      target: payload?.target || null,
      matchedBy: payload?.matched_by || null,
      coordinates: Array.isArray(payload?.coordinates) ? payload.coordinates : null,
      message: payload?.message || "",
      screenText: payload?.screen_text || null,
      steps: Array.isArray(payload?.steps) ? payload.steps : [],
    };
  } catch (error) {
    if (error?.name === "AbortError") {
      throw error;
    }
    if (error instanceof TypeError) {
      throw new Error(`Cannot connect to speech backend at ${baseUrl}.`);
    }
    throw error;
  } finally {
    cleanup();
  }
}
