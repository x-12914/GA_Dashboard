"""FastAPI app: serves the dashboard and the analytics + insights API."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ga4_client, analyzer, store_audit
from .config import settings

app = FastAPI(title="GA Money Advisor", version="0.1.0")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/api/status")
def status() -> dict:
    provider = settings.provider
    analyzer_label = {
        "openai": f"openai:{settings.OPENAI_MODEL}",
        "claude": f"claude:{settings.ANTHROPIC_MODEL}",
        "heuristic": "heuristic",
    }[provider]
    return {
        "mode": "ga4" if (settings.ga4_ready and not settings.USE_MOCK) else "mock",
        "ga4_ready": settings.ga4_ready,
        "provider": provider,
        "analyzer": analyzer_label,
    }


@app.get("/api/report")
def report(days: int = Query(28, ge=1, le=365)) -> dict:
    return ga4_client.get_report(days)


@app.get("/api/insights")
def insights(days: int = Query(28, ge=1, le=365)) -> JSONResponse:
    data = ga4_client.get_report(days)
    advice = analyzer.analyze(data)
    return JSONResponse({"report": data, "advice": advice})


@app.get("/api/audit")
def audit(url: str = Query(..., min_length=3), email: bool = False) -> JSONResponse:
    result = store_audit.audit(url)
    if email and result.get("ok"):
        result["cold_email"] = analyzer.cold_email(result)
    return JSONResponse(result)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


# Serve css/js
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
