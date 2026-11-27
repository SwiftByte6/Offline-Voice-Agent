"""Local LFM3 planner backed by the Q4_K_M GGUF checkpoint."""

from __future__ import annotations

import logging
from pathlib import Path
import threading
from typing import Any

from huggingface_hub import hf_hub_download

from engine.config import LLMConfig

logger = logging.getLogger("nova.lfm")

PLAN_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "complete": {"type": "boolean"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "text": {"type": "string"},
                    "keys": {"type": "array", "items": {"type": "string"}},
                    "amount": {"type": "integer"},
                    "target": {"type": "string"},
                    "query": {"type": "string"},
                    "location": {"type": "string"},
                    "source": {"type": "string"},
                    "new_name": {"type": "string"},
                    "destination_dir": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    "required": ["summary", "actions"],
}


class LLMLoadingError(RuntimeError):
    """Raised when the local planner is still loading."""


class LLMUnavailableError(RuntimeError):
    """Raised when the local planner cannot be used."""


class LFMService:
    """Loads LFM3 once and produces deterministic structured plans."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._model: Any | None = None
        self._plan_grammar: Any | None = None
        self._status = "unloaded"
        self._error: str | None = None
        self._init_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def status(self) -> str:
        return self._status

    @property
    def ready(self) -> bool:
        return self._status == "ready" and self._model is not None

    @property
    def error(self) -> str | None:
        return self._error

    def load_model(self) -> None:
        """Download the quantized model once and initialize llama.cpp."""
        with self._init_lock:
            if self.ready:
                return
            self._status = "loading"
            self._error = None
            try:
                from llama_cpp import Llama, LlamaGrammar

                model_path = self._resolve_model_path()
                logger.info(
                    "Initializing LFM3 model=%s file=%s context=%s gpu_layers=%s",
                    self.config.model_repo,
                    self.config.model_file,
                    self.config.context_tokens,
                    self.config.gpu_layers,
                )
                self._model = Llama(
                    model_path=model_path,
                    n_ctx=self.config.context_tokens,
                    n_gpu_layers=self.config.gpu_layers,
                    n_threads=self.config.threads,
                    verbose=False,
                )
                self._plan_grammar = LlamaGrammar.from_json_schema(PLAN_JSON_SCHEMA)
                self._status = "ready"
                logger.info("LFM3 planner is ready.")
            except Exception as exc:  # noqa: BLE001
                self._model = None
                self._plan_grammar = None
                self._status = "error"
                self._error = str(exc)
                logger.exception("Failed to initialize LFM3 planner.")

    def _resolve_model_path(self) -> str:
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        local_path = self.config.cache_dir / self.config.model_file
        if local_path.is_file():
            return str(local_path)
        if self.config.local_files_only:
            raise FileNotFoundError(
                f"LFM3 model is not cached at {local_path}. "
                "Start once without NOVA_LLM_OFFLINE_ONLY to download it."
            )
        logger.info("Downloading LFM3 model to %s...", local_path)
        return hf_hub_download(
            repo_id=self.config.model_repo,
            filename=self.config.model_file,
            local_dir=str(self.config.cache_dir),
        )

    def create_plan(self, system_prompt: str, user_prompt: str) -> str:
        """Generate one plan response while serializing llama.cpp inference."""
        if self.status == "loading":
            raise LLMLoadingError("LFM3 is still loading. Please try again shortly.")
        if not self.ready or self._model is None:
            raise LLMUnavailableError(self.error or "LFM3 is unavailable.")

        with self._inference_lock:
            prompt = (
                f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
                f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
                "<|im_start|>assistant\n<think></think>"
            )
            logger.info("Agent LLM system prompt:\n%s", system_prompt)
            response = self._model.create_completion(
                prompt=prompt,
                temperature=0.1,
                top_k=50,
                repeat_penalty=1.1,
                max_tokens=512,
                grammar=self._plan_grammar,
            )
        return str(response["choices"][0]["text"] or "")
