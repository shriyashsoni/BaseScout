"""BaseScout web app — FastAPI backend + a single-page demo UI.

Run:
    uvicorn app:app --reload
    # then open http://127.0.0.1:8000

Endpoints:
    GET  /                  → the demo UI
    GET  /api/health        → status + whether the AI key is configured
    POST /api/signals       → keyless rule-based risk signals for an address
    GET  /api/analyze/stream → Server-Sent Events: live agent trace + final report
"""

from __future__ import annotations

import json
import queue
import threading

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from basescout import agent, config, risk

app = FastAPI(title="BaseScout", version="0.1.0")

_STATIC_DIR = "static"


class SignalsRequest(BaseModel):
    address: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(f"{_STATIC_DIR}/index.html")


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "ai_enabled": bool(config.ANTHROPIC_API_KEY),
        "model": config.MODEL,
        "network": "base-mainnet",
    })


@app.post("/api/signals")
def signals(req: SignalsRequest) -> JSONResponse:
    """Keyless deterministic risk signals — works with no Anthropic key."""
    try:
        result = risk.compute_risk_signals(req.address)
        return JSONResponse(result)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.get("/api/analyze/stream")
def analyze_stream(q: str) -> StreamingResponse:
    """Stream the agent's tool calls and final report as SSE events."""

    def event_gen():
        events: "queue.Queue[dict]" = queue.Queue()
        done = object()

        def on_event(ev: dict) -> None:
            events.put(ev)

        def worker() -> None:
            try:
                agent.analyze(q, on_event=on_event)
            except Exception as exc:  # noqa: BLE001 - report to the client
                events.put({"type": "error", "message": str(exc)})
            finally:
                events.put(done)  # type: ignore[arg-type]

        threading.Thread(target=worker, daemon=True).start()

        while True:
            ev = events.get()
            if ev is done:
                yield "event: end\ndata: {}\n\n"
                break
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
