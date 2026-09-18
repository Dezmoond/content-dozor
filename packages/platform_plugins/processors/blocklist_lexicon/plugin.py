# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, List

from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class

from platform_plugins.processors.blocklist_lexicon.match import (
    BLOCKLIST_MAX_WER_DEFAULT,
    FORBIDDEN_LEXICON_DEFAULT,
    find_forbidden_from_phrases,
    phrases_to_csv,
)


def _resolve_lexicon_config(ctx: PipelineContext) -> tuple[List[str], float]:
    cfg = ctx.config.get("forbidden_lexicon") or {}
    phrases = cfg.get("phrases")
    max_wer = float(cfg.get("max_wer", BLOCKLIST_MAX_WER_DEFAULT))
    if isinstance(phrases, list) and phrases:
        return [str(p).strip() for p in phrases if str(p).strip()], max_wer
    csv = (cfg.get("phrases_csv") or "").strip()
    if not csv:
        csv = FORBIDDEN_LEXICON_DEFAULT
    return [p.strip() for p in csv.split(",") if p.strip()], max_wer


@register_plugin_class
class BlocklistLexiconPlugin(Plugin):
    meta = PluginMeta(id="blocklist_lexicon", name="Blocklist Lexicon", kind=PluginKind.PROCESSOR)

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        phrases, max_wer = _resolve_lexicon_config(ctx)
        if not phrases:
            ctx.artifacts["blocklist_phrases"] = []
            return data
        hits = find_forbidden_from_phrases(ctx.text, phrases, max_wer)
        ctx.artifacts["blocklist_phrases"] = hits
        ctx.artifacts["forbidden_lexicon_effective"] = {
            "phrases": phrases,
            "phrases_csv": phrases_to_csv(phrases),
            "max_wer": max_wer,
            "count": len(hits),
        }
        return data
