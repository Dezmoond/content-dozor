# -*- coding: utf-8 -*-
"""RuBERT processors — entities + канонизация ФИО (слоты)."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class


@register_plugin_class
class RuBertEntitiesPlugin(Plugin):
    meta = PluginMeta(id="rubert_entities", name="RuBERT Entities", kind=PluginKind.PROCESSOR)

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        t0 = time.perf_counter()
        text = ctx.text or ""
        entities: list = []
        error = None
        try:
            from platform_plugins.processors.rubert_runtime import (
                extract_entities_rubert,
                rubert_to_typed_dict,
                ensure_rubert_loaded,
            )
            if ensure_rubert_loaded():
                entities = extract_entities_rubert(
                    text,
                    min_words=1,
                    max_words=15,
                    confidence_threshold=0.6,
                )
                ctx.artifacts["rubert_entities_typed"] = rubert_to_typed_dict(entities)
            else:
                error = "RuBERT model not loaded (check RUBERT_MODEL_PATH / torch)"
                ctx.artifacts["rubert_entities_typed"] = {
                    "persons": [], "organizations": [], "titles": [], "urls": [],
                }
        except Exception as exc:
            error = str(exc)[:300]
            ctx.artifacts["rubert_entities_typed"] = {
                "persons": [], "organizations": [], "titles": [], "urls": [],
            }

        ctx.artifacts["rubert_entities"] = entities
        ms = (time.perf_counter() - t0) * 1000
        ctx.artifacts.setdefault("rubert_stats", {})["entities"] = {
            "count": len(entities),
            "duration_ms": round(ms, 1),
            "error": error,
        }
        return data


@register_plugin_class
class RuBertDangerPlugin(Plugin):
    meta = PluginMeta(id="rubert_danger", name="RuBERT Danger", kind=PluginKind.PROCESSOR, enabled=False)

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        ctx.artifacts.setdefault("rubert_danger", {"dangerous": False, "phrases": []})
        return data


@register_plugin_class
class RuBertFioPlugin(Plugin):
    """
    Канонизация ФИО для поиска по реестрам:
    фамилия имя отчество | фамилия инициалы.
    Берёт persons из Qwen / RuBERT / Natasha; Natasha fact → RuBERT slots (если модель) → эвристика.
    """

    meta = PluginMeta(
        id="rubert_fio",
        name="RuBERT FIO slots",
        kind=PluginKind.PROCESSOR,
        description="Порядок ФИО: фамилия имя отчество / фамилия инициалы",
    )

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        from platform_plugins.processors.fio_slots import enrich_person_entity

        t0 = time.perf_counter()
        normalized: List[Dict[str, Any]] = []
        seen: set = set()

        def _consume(items: list, default_label: str = "fio") -> None:
            for it in items or []:
                if isinstance(it, str):
                    ent = {"text": it, "label": default_label}
                elif isinstance(it, dict):
                    ent = dict(it)
                    if not ent.get("label"):
                        ent["label"] = default_label
                else:
                    continue
                lab = str(ent.get("label") or "")
                if lab not in ("fio", "person", "persons", ""):
                    # только люди
                    if default_label != "fio":
                        continue
                enriched = enrich_person_entity(ent)
                key = (enriched.get("fio_normalized") or enriched.get("text") or "").lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                normalized.append(enriched)

        # Natasha (уже может иметь fio_*)
        _consume(ctx.artifacts.get("natasha_entities") or [])
        # typed
        for typed_key in ("natasha_entities_typed", "rubert_entities_typed", "entities"):
            typed = ctx.artifacts.get(typed_key) or {}
            if isinstance(typed, dict):
                _consume(typed.get("persons") or [], "fio")
        _consume(ctx.artifacts.get("rubert_entities") or [])

        # обновить normal у исходных списков для registry
        def _patch_list(lst: list) -> list:
            out = []
            for it in lst or []:
                if isinstance(it, dict) and str(it.get("label") or "") in ("fio", "person", ""):
                    out.append(enrich_person_entity(it))
                else:
                    out.append(it)
            return out

        if ctx.artifacts.get("natasha_entities"):
            ctx.artifacts["natasha_entities"] = _patch_list(ctx.artifacts["natasha_entities"])
            from platform_plugins.processors.natasha_runtime import natasha_to_typed_dict
            ctx.artifacts["natasha_entities_typed"] = natasha_to_typed_dict(
                ctx.artifacts["natasha_entities"]
            )

        # Qwen entities persons
        ents = ctx.artifacts.get("entities")
        if isinstance(ents, dict) and ents.get("persons"):
            patched = []
            for p in ents["persons"]:
                if isinstance(p, dict):
                    patched.append(enrich_person_entity({**p, "label": "fio"}))
                elif isinstance(p, str):
                    patched.append(enrich_person_entity({"text": p, "label": "fio"}))
                else:
                    patched.append(p)
            ents = {**ents, "persons": patched}
            ctx.artifacts["entities"] = ents

        ctx.artifacts["fio_normalized"] = normalized
        ms = (time.perf_counter() - t0) * 1000
        ctx.artifacts.setdefault("rubert_stats", {})["fio"] = {
            "count": len(normalized),
            "duration_ms": round(ms, 1),
            "sources": sorted({n.get("fio_source") for n in normalized if n.get("fio_source")}),
        }
        return data
