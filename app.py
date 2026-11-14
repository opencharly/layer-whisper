#!/usr/bin/env python3
"""charly-owned OpenAI-compatible ASR surface for the `whisper` layer.

WHY THIS FILE EXISTS
    `openai/whisper` ships no HTTP server of any kind. Measured at v20250625: the whole
    tree is 45 files with zero matches for any web framework, any route decorator, and
    `audio/transcriptions`. So the wire surface is ours to own, and it lives here rather
    than in a wrapper script because a per-request `whisper` CLI invocation reloads the
    checkpoint every time (1.5 GiB for the upstream default) and writes five
    basename-colliding output files into the CWD.

    The model is therefore loaded ONCE at import and `model.transcribe` is called
    in-process, which is the same API path the CLI uses.

CONTRACT (measured against Open Web UI 0.13.3, backend/open_webui/routers/audio/__init__.py)
    POST <base>/v1/audio/transcriptions
        multipart/form-data, parts: `file` (required), `model`, `language`
        header: `Authorization: Bearer <AUDIO_STT_OPENAI_API_KEY>` (always sent)
        NOTE: Open Web UI appends `/audio/transcriptions` to the configured base URL, so
        the base must end in `/v1`.
    Response: a JSON object whose TOP-LEVEL `text` is the only field Open Web UI reads;
    everything else is discarded by the caller and kept here only for humans.

CONFIGURATION (all optional, all env, all documented in the candy's skill body)
    WHISPER_MODEL          tiny|base|small|medium|large-v3|turbo   (default base)
    WHISPER_DEVICE         cpu|cuda|cuda:N                          (default cpu)
    WHISPER_FP16           true|false                               (default false)
    WHISPER_LANGUAGE       default language hint; empty = auto-detect
    WHISPER_TASK           transcribe|translate                      (default transcribe)
    WHISPER_BEAM_SIZE      decode beam size                          (default 5)
    WHISPER_MAX_UPLOAD_MB  request body cap                          (default 25)
    WHISPER_API_KEY        optional bearer token; unset = anonymous
    WHISPER_CACHE_DIR      checkpoint cache                          (default ~/.cache/whisper)
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import whisper
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

LOG = logging.getLogger("whisper-asr")


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"{name}: expected a boolean, got {raw!r}")


MODEL = _env("WHISPER_MODEL", "base")
DEVICE = _env("WHISPER_DEVICE", "cpu")
FP16 = _env_bool("WHISPER_FP16", False)
LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "").strip() or None
TASK = _env("WHISPER_TASK", "transcribe")
BEAM_SIZE = int(_env("WHISPER_BEAM_SIZE", "5"))
MAX_UPLOAD_BYTES = int(float(_env("WHISPER_MAX_UPLOAD_MB", "25")) * 1024 * 1024)
API_KEY = os.environ.get("WHISPER_API_KEY", "").strip()
CACHE_DIR = _env("WHISPER_CACHE_DIR", str(Path.home() / ".cache" / "whisper"))

if TASK not in {"transcribe", "translate"}:
    raise SystemExit(f"WHISPER_TASK: expected transcribe|translate, got {TASK!r}")

_model: "whisper.Whisper | None" = None


def load() -> "whisper.Whisper":
    """Load the checkpoint once; the start script normally prefetches it onto the volume."""
    global _model
    if _model is None:
        LOG.info("loading checkpoint %s on %s (cache %s)", MODEL, DEVICE, CACHE_DIR)
        _model = whisper.load_model(MODEL, device=DEVICE, download_root=CACHE_DIR)
    return _model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load()
    # State the auth posture ONCE, loudly. An open endpoint is a decision, not a default
    # that happens to have been inherited.
    if API_KEY:
        LOG.info("auth: bearer token required")
    else:
        LOG.warning("auth: NONE configured (WHISPER_API_KEY empty) — requests are served anonymously")
    LOG.info("ready: model=%s device=%s task=%s", MODEL, DEVICE, TASK)
    yield


app = FastAPI(title="whisper-asr", lifespan=lifespan)


async def _authorize(authorization: str = Header(default="")) -> None:
    """401 only when a key IS configured; an unset key means a deliberately open endpoint."""
    if not API_KEY:
        return
    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or presented.strip() != API_KEY:
        raise HTTPException(status_code=401, detail="invalid bearer token")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "model": MODEL, "device": DEVICE, "task": TASK})


@app.get("/v1/models")
async def models() -> JSONResponse:
    return JSONResponse({"object": "list", "data": [{"id": MODEL, "object": "model"}]})


@app.post("/v1/audio/transcriptions", dependencies=[Depends(_authorize)])
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(default=""),
    language: str = Form(default=""),
) -> JSONResponse:
    # A requested model that this server does not serve is a 400 naming both — never a
    # silent substitution, which would let a misconfigured consumer look healthy.
    requested = (model or "").strip()
    if requested and requested != MODEL:
        raise HTTPException(
            status_code=400,
            detail=f"this server serves {MODEL!r}; the request asked for {requested!r}",
        )

    # Size cap: read in bounded chunks and refuse as soon as the cap is crossed.
    workdir = tempfile.mkdtemp(prefix="whisper-asr-")
    try:
        suffix = Path(file.filename or "audio").suffix or ".bin"
        dest = Path(workdir) / f"upload{suffix}"
        written = 0
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"upload exceeds WHISPER_MAX_UPLOAD_MB ({MAX_UPLOAD_BYTES} bytes)",
                    )
                out.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="empty upload")

        result = load().transcribe(
            str(dest),
            language=(language or LANGUAGE) or None,
            task=TASK,
            beam_size=BEAM_SIZE,
            fp16=FP16,
            verbose=False,
            # Long clips loop without this; the upstream CLI defaults it ON, which is the
            # wrong default for a request/response service.
            condition_on_previous_text=False,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return JSONResponse(
        {
            # Open Web UI reads ONLY this key (routers/audio/__init__.py projects result["text"]).
            "text": result.get("text", ""),
            "language": result.get("language"),
            "model": MODEL,
        }
    )


if __name__ == "__main__":
    import uvicorn

    port = int(_env("WHISPER_PORT", "9000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
