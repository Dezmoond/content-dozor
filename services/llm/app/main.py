# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Bootstrap paths
_ROOT = Path(__file__).resolve().parents[3]
_PACKAGES = _ROOT / "packages"
_DIPLOM = _ROOT.parent
_LLAMA = _DIPLOM / "llama_classific" / "llama_train"
for p in (_PACKAGES, _LLAMA):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import platform_plugins  # noqa: F401 — register plugins
from platform_core.runtime_config import resolve_pipeline_config
from platform_core.config import get_settings
from platform_core.context import PipelineContext
from platform_core.llm_provider import get_llm_provider
from platform_core.pipeline import Pipeline
from platform_core.plugin import get_registry
from platform_plugins.exporters.html.plugin import build_html_report

app = FastAPI(title="LLM Service", version="0.1.0")


class AnalyzeTextRequest(BaseModel):
    text: str
    case_id: Optional[str] = None
    document_id: Optional[str] = None
    pipeline_config: Optional[dict] = None


class AnalyzeDocxRequest(BaseModel):
    docx_path: str
    case_id: Optional[str] = None
    document_id: Optional[str] = None
    job_id: Optional[str] = None
    pipeline_config: Optional[dict] = None


class AnalyzeSourceRequest(BaseModel):
    source_type: str = "docx"
    source_path: Optional[str] = None
    source_url: Optional[str] = None
    source_text: Optional[str] = None
    include_comments: bool = True
    case_id: Optional[str] = None
    document_id: Optional[str] = None
    job_id: Optional[str] = None
    pipeline_config: Optional[dict] = None


def _build_pipeline(config: Optional[dict]) -> Pipeline:
    pipeline = Pipeline(registry=get_registry())
    if config and config.get("enabled_steps"):
        pipeline.with_enabled(config["enabled_steps"])
    return pipeline


@app.get("/health")
async def health():
    extremism = get_llm_provider("extremism")
    entities = get_llm_provider("entities")
    validation = get_llm_provider("validation")
    settings = get_settings()
    return {
        "status": "ok",
        "service": "llm",
        "llm_backend": settings.llm_backend,
        "llamacpp": {
            "extremism": await extremism.health(),
            "entities": await entities.health(),
            "validation": await validation.health(),
        },
    }


@app.get("/plugins")
async def list_plugins():
    reg = get_registry()
    return [m.model_dump() if hasattr(m, "model_dump") else m.dict() for m in reg.list_plugins()]


@app.post("/analyze/text")
async def analyze_text(body: AnalyzeTextRequest):
    pipeline_config = await resolve_pipeline_config(body.pipeline_config)
    ctx = PipelineContext(
        case_id=body.case_id,
        document_id=body.document_id,
        text=body.text,
        config=pipeline_config,
    )
    pipeline = _build_pipeline(pipeline_config)
    try:
        result = await pipeline.run(ctx, body.text)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    html_preview = build_html_report(ctx.text, ctx.artifacts)
    ctx.artifacts["html_preview"] = html_preview
    return {
        "result": result,
        "artifacts": ctx.artifacts,
        "steps_log": ctx.steps_log,
        "html_preview": html_preview,
    }


@app.post("/analyze/docx")
async def analyze_docx(body: AnalyzeDocxRequest):
    return await analyze_source(
        AnalyzeSourceRequest(
            source_type="docx",
            source_path=body.docx_path,
            case_id=body.case_id,
            document_id=body.document_id,
            job_id=body.job_id,
            pipeline_config=body.pipeline_config,
        )
    )


@app.post("/analyze/source")
async def analyze_source(body: AnalyzeSourceRequest):
    path = Path(body.source_path) if body.source_path else None
    if path is not None and body.source_path and not path.is_file():
        raise HTTPException(404, f"File not found: {path}")
    pipeline_config = await resolve_pipeline_config(body.pipeline_config)
    if body.job_id:
        pipeline_config = {**pipeline_config, "job_id": body.job_id}
    pipeline_config = {**pipeline_config, "source_type": body.source_type}
    ctx = PipelineContext(
        case_id=body.case_id,
        document_id=body.document_id,
        text=body.source_text or "",
        config=pipeline_config,
    )
    ctx.artifacts["source_type"] = body.source_type
    if body.source_path:
        ctx.artifacts["source_path"] = body.source_path
        if body.source_type == "docx":
            ctx.artifacts["docx_path"] = body.source_path
    if body.source_url:
        ctx.artifacts["source_url"] = body.source_url
    if body.source_text:
        ctx.artifacts["source_text"] = body.source_text
    ctx.artifacts["include_comments"] = body.include_comments
    pipeline = _build_pipeline(pipeline_config)
    try:
        result = await pipeline.run(ctx, body.source_path or body.source_text or body.source_url)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    html_preview = build_html_report(ctx.text, ctx.artifacts)
    ctx.artifacts["html_preview"] = html_preview
    return {
        "result": result,
        "artifacts": ctx.artifacts,
        "steps_log": ctx.steps_log,
        "html_preview": html_preview,
        "text_length": len(ctx.text),
        "source_type": body.source_type,
    }


@app.post("/pipeline/two-level")
async def two_level(body: AnalyzeTextRequest):
    """Shortcut: extremism + validation only."""
    try:
        from ollama_pipeline_two_level import run_pipeline
    except ImportError:
        raise HTTPException(503, "ollama_pipeline_two_level not available")
    import asyncio
    result = await asyncio.to_thread(
        run_pipeline,
        body.text,
        verbose=False,
    )
    return result
