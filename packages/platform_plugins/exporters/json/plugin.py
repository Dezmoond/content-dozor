# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class


@register_plugin_class
class JsonExporterPlugin(Plugin):
    meta = PluginMeta(id="exporter_json", name="JSON Exporter", kind=PluginKind.EXPORTER)

    async def process(self, ctx: PipelineContext, data: Any) -> dict:
        result = {
            "case_id": ctx.case_id,
            "document_id": ctx.document_id,
            "text_length": len(ctx.text),
            "analysis_mode": ctx.artifacts.get("analysis_mode") or ctx.config.get("analysis_mode", "deep"),
            "entities": ctx.artifacts.get("entities"),
            "rubert_entities": ctx.artifacts.get("rubert_entities"),
            "natasha_entities": ctx.artifacts.get("natasha_entities"),
            "natasha_entities_typed": ctx.artifacts.get("natasha_entities_typed"),
            "extremism": ctx.artifacts.get("extremism"),
            "validation": ctx.artifacts.get("validation"),
            "shallow_analysis": ctx.artifacts.get("shallow_analysis"),
            "ошибочное": ctx.artifacts.get("ошибочное", False),
            "registry_hits": ctx.artifacts.get("registry_hits", []),
            "chunks_count": len(ctx.artifacts.get("chunks") or []),
            "steps_log": ctx.steps_log,
        }
        ctx.artifacts["final_report"] = result
        return result
