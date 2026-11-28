"""FastAPI application entrypoint for the P.E.K.K.A offline STT backend."""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engine.api.routes import router
from engine.config import load_config
from engine.speech.stt_service import OfflineSTTService
from engine.voice.listener import VoiceListener
from engine.voice.pipeline import PekkaPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = app.state.config
    speech_service = OfflineSTTService(config.parakeet, config.whisper)
    pipeline = PekkaPipeline(stt=speech_service)
    listener = VoiceListener(
        stt=speech_service,
        on_transcript=lambda text: pipeline.run(transcript=text),
    )
    app.state.speech_service = speech_service
    app.state.transcription_lock = asyncio.Lock()
    app.state.pekka_pipeline = pipeline
    app.state.voice_listener = listener

    # Load model in a background worker thread so /health responds immediately during startup.
    load_task = asyncio.create_task(asyncio.to_thread(speech_service.load_model))

    if os.getenv("PEKKA_CONTINUOUS_LISTEN", "true").strip().lower() in {"1", "true", "yes", "on"}:
        listener.start(loop=asyncio.get_running_loop())

    try:
        yield
    finally:
        listener.stop()
        if not load_task.done():
            load_task.cancel()
            try:
                await load_task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    config = load_config()
    app = FastAPI(
        title="P.E.K.K.A Speech Engine",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.config = config

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run(
        "engine.main:app",
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )
