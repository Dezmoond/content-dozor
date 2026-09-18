# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "packages"))

import platform_plugins  # noqa: F401
from platform_core.config import get_settings
from platform_core.context import PipelineContext
from platform_core.plugin import get_registry
from platform_plugins.parsers.parser_zapret.plugin import list_parsers, list_parsers_detailed

app = FastAPI(title="Parsers Service", version="0.1.0")


class RunParserRequest(BaseModel):
    parser_id: str = "minjust_extremist_materials"
    output_dir: str = ""
    timeout: int = 3600


@app.get("/health")
async def health():
    return {"status": "ok", "service": "parsers"}


@app.get("/parsers")
async def parsers_list():
    return {
        "parsers": list_parsers(),
        "items": list_parsers_detailed(),
    }

@app.post("/parsers/run")
async def run_parser(body: RunParserRequest):
    reg = get_registry()
    plugin = reg.get("parser_zapret")
    if not plugin:
        return {"status": "error", "message": "parser_zapret plugin not loaded"}
    settings = get_settings()
    output_dir = body.output_dir or settings.resolved_parser_runs_dir()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.resolved_blacklist_dir()).mkdir(parents=True, exist_ok=True)
    ctx = PipelineContext(config={
        "parser_id": body.parser_id,
        "output_dir": output_dir,
        "timeout": body.timeout,
        "apply_to_app": True,
    })
    result = await plugin.process(ctx, None)
    return result
