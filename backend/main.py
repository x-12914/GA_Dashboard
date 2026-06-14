"""FastAPI app: serves the dashboard and the analytics + insights API."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from . import ga4_client, analyzer, store_audit, prospector
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


@app.get("/api/pagespeed")
def pagespeed(url: str = Query(..., min_length=3)) -> JSONResponse:
    # Slow (PSI can take 30-120s); the frontend calls this lazily after the
    # main audit renders, so the audit itself stays fast.
    return JSONResponse({"check": store_audit.pagespeed_check(url)})


class ProspectRequest(BaseModel):
    niche: str = ""          # discover stores by niche (needs Custom Search)
    urls: list[str] = []     # or audit a pasted list of store URLs/domains
    want_email: bool = True
    limit: int = 20


@app.get("/api/prospect/status")
def prospect_status() -> dict:
    return {
        "discovery_ready": settings.discovery_ready,
        "search_provider": settings.search_provider,
    }


@app.post("/api/prospect")
def prospect(req: ProspectRequest) -> JSONResponse:
    targets = [u for u in req.urls if u.strip()]
    discovered_from = None
    if not targets and req.niche.strip():
        targets = store_audit.discover_stores(req.niche, limit=min(req.limit, 30))
        discovered_from = req.niche.strip()
    results = prospector.find_prospects(targets, want_email=req.want_email)
    return JSONResponse({
        "discovered_from": discovered_from,
        "discovery_ready": settings.discovery_ready,
        "candidates": len(targets),   # stores found before the Shopify filter
        "count": len(results),        # actual Shopify prospects
        "prospects": results,
    })


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


# Serve css/js
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
