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
      agent: payload?.agent || null,
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

export async function confirmAgentAction(confirmationId, approved) {
  const response = await fetch(`${getSpeechApiBaseUrl()}/api/agent/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirmation_id: confirmationId, approved }),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.detail || "Could not confirm the protected action.");
  }
  return payload;
}
