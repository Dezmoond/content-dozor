# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from platform_core.config import get_settings
from platform_plugins.exporters.html.plugin import build_html_report

app = FastAPI(title="Reports Service", version="0.1.0")


class ReportRequest(BaseModel):
    case_id: str
    format: str = "json"


@app.get("/health")
async def health():
    return {"status": "ok", "service": "reports"}


def _pick_run(runs: list) -> dict:
    """Берём первый (newest) прогон с полезными артефактами."""
    for run in runs or []:
        result = run.get("result") or {}
        arts = result.get("artifacts") if isinstance(result, dict) else None
        if not isinstance(arts, dict):
            continue
        if arts.get("html_preview") or arts.get("raw_text") or arts.get("extremism") is not None:
            return run
    return (runs or [{}])[0] if runs else {}


def _html_from_artifacts(arts: Dict[str, Any]) -> str:
    preview = arts.get("html_preview")
    if isinstance(preview, str) and preview.strip() and "No HTML report" not in preview:
        if "<html" in preview.lower() or "<mark" in preview or "<pre" in preview:
            return preview
    text = arts.get("raw_text") or ""
    if not text and isinstance(arts.get("final_report"), dict):
        # fallback — без полного текста хотя бы каркас
        text = ""
    return build_html_report(str(text or ""), arts)


@app.post("/reports/generate")
async def generate_report(body: ReportRequest):
    settings = get_settings()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{settings.cases_service_url}/cases/{body.case_id}")
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, resp.text)
        case_data = resp.json()
    runs = case_data.get("pipeline_runs") or []
    last = _pick_run(runs)
    result = last.get("result") or {}
    arts = result.get("artifacts") if isinstance(result, dict) else {}
    if not isinstance(arts, dict):
        arts = {}
    if body.format == "html":
        html = _html_from_artifacts(arts) if arts else "<p>Нет HTML-отчёта: анализ ещё не завершён</p>"
        return HTMLResponse(content=html, media_type="text/html; charset=utf-8")
    return JSONResponse(case_data)


@app.get("/reports/{case_id}/json")
async def report_json(case_id: str):
    return await generate_report(ReportRequest(case_id=case_id, format="json"))


@app.get("/reports/{case_id}/html")
async def report_html(case_id: str):
    return await generate_report(ReportRequest(case_id=case_id, format="html"))
