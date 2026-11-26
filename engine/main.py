"""FastAPI application entrypoint for the NOVA speech recognition backend."""

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from engine.api.routes import router
from engine.config import load_config
from engine.speech.whisper_service import WhisperService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = app.state.config
    whisper_service = WhisperService(config.whisper)
    app.state.whisper_service = whisper_service
    app.state.transcription_lock = asyncio.Lock()

    # Load model in a background worker thread so /health responds immediately during startup.
    load_task = asyncio.create_task(asyncio.to_thread(whisper_service.load_model))

    try:
        yield
    finally:
        if not load_task.done():
            load_task.cancel()
            try:
                await load_task
            except asyncio.CancelledError:
                pass


def create_app() -> FastAPI:
    config = load_config()
    app = FastAPI(
        title="NOVA Speech Engine",
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
