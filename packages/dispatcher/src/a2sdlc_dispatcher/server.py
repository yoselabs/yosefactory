"""FastAPI app entry point."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="a2sdlc-dispatcher", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    """Run the service via uvicorn — used by the `a2sdlc-dispatcher` script."""
    import uvicorn

    uvicorn.run(
        "a2sdlc_dispatcher.server:app", host="0.0.0.0", port=8000, log_level="info"
    )
