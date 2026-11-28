"""Local LLM access for P.E.K.K.A (Ollama OpenAI-compatible API, zero cloud keys)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "llama3.2"
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LocalLLMUnavailable(RuntimeError):
    """Local LLM is not reachable / not configured / returned no usable JSON."""


def _get_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _NO_PROXY_OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LocalLLMUnavailable(f"Local LLM not reachable at {url}: {exc}") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise LocalLLMUnavailable(f"Local LLM returned non-JSON: {raw[:300]}") from exc


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with _NO_PROXY_OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LocalLLMUnavailable(f"Local LLM not reachable at {url}: {exc}") from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise LocalLLMUnavailable(f"Local LLM returned non-JSON: {raw[:300]}") from exc


def parse_json_loose(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating ```json fences and surrounding prose."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {"value": value}
    except ValueError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            value = json.loads(text[start : end + 1])
            return value if isinstance(value, dict) else {"value": value}
        raise LocalLLMUnavailable(f"Could not parse JSON from local LLM: {text[:300]}")


class LocalLLM:
    """OpenAI-compatible local LLM; works with Ollama, LM Studio, or local gateway."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("PEKKA_LLM_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        self._explicit_model = model or os.getenv("PEKKA_LLM_MODEL")
        self.model = self._explicit_model or DEFAULT_MODEL
        self.api_key = api_key or os.getenv("PEKKA_LLM_API_KEY") or ""
        self.timeout_s = float(timeout_s or os.getenv("PEKKA_LLM_TIMEOUT", "30") or 30)

    async def list_models(self) -> list[str]:
        import asyncio

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = await asyncio.to_thread(_get_json, f"{self.base_url}/models", headers, min(5.0, self.timeout_s))
        return [str(m["id"]) for m in payload.get("data", []) if isinstance(m, dict) and m.get("id")]

    async def resolve_model(self) -> str:
        if self._explicit_model:
            return self._explicit_model
        models = await self.list_models()
        if models:
            self.model = models[0]
        return self.model

    async def chat_messages(self, messages: list[dict[str, str]], *, temperature: float = 0.0) -> dict[str, Any]:
        import asyncio

        await self.resolve_model()
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        payload = await asyncio.to_thread(_post_json, url, body, headers, self.timeout_s)
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LocalLLMUnavailable(f"Local LLM response missing message.content: {payload}") from exc
        return parse_json_loose(content)

    async def chat_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict[str, Any]:
        return await self.chat_messages(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )


def make_local_llm() -> LocalLLM | None:
    """Return LocalLLM unless PEKKA_LLM_DISABLE=true. Does not verify reachability."""
    if _bool(os.getenv("PEKKA_LLM_DISABLE"), False):
        return None
    return LocalLLM()


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
