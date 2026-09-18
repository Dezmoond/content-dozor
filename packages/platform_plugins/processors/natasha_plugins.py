# -*- coding: utf-8 -*-
"""Natasha NER — ФИО, организации, URL (без titles)."""
from __future__ import annotations

import time
from typing import Any

from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class


@register_plugin_class
class NatashaEntitiesPlugin(Plugin):
    meta = PluginMeta(
        id="natasha_entities",
        name="Natasha Entities",
        kind=PluginKind.PROCESSOR,
        description="ФИО/организации (именительный падеж) + URL; titles не ищет",
    )

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        t0 = time.perf_counter()
        text = ctx.text or ""
        entities: list = []
        error = None
        try:
            from platform_plugins.processors.natasha_runtime import (
                ensure_natasha_loaded,
                extract_entities_natasha,
                load_error,
                natasha_to_typed_dict,
            )

            if ensure_natasha_loaded():
                entities = extract_entities_natasha(text)
                ctx.artifacts["natasha_entities_typed"] = natasha_to_typed_dict(entities)
            else:
                error = load_error() or "Natasha not installed (pip install natasha)"
                ctx.artifacts["natasha_entities_typed"] = {
                    "persons": [], "organizations": [], "titles": [], "urls": [],
                }
        except Exception as exc:
            error = str(exc)[:300]
            ctx.artifacts["natasha_entities_typed"] = {
                "persons": [], "organizations": [], "titles": [], "urls": [],
            }

        ctx.artifacts["natasha_entities"] = entities
        ms = (time.perf_counter() - t0) * 1000
        ctx.artifacts.setdefault("natasha_stats", {})["entities"] = {
            "count": len(entities),
            "persons": sum(1 for e in entities if e.get("label") in ("fio", "person")),
            "organizations": sum(1 for e in entities if e.get("label") == "organization"),
            "urls": sum(1 for e in entities if e.get("label") == "url"),
            "duration_ms": round(ms, 1),
            "error": error,
        }
        return data
