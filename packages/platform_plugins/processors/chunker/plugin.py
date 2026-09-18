# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List

from platform_core.config import get_settings
from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class

CHUNK_SIZE = 300
CHUNK_OVERLAP = 25


def split_text_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[Dict[str, Any]]:
    if not text:
        return []
    chunks: List[Dict[str, Any]] = []
    start = 0
    n = len(text)
    idx = 0
    while start < n:
        end = min(start + chunk_size, n)
        chunk_text = text[start:end]
        chunks.append({"index": idx, "start": start, "end": end, "text": chunk_text})
        if end >= n:
            break
        start = max(0, end - overlap)
        idx += 1
    return chunks


@register_plugin_class
class ChunkerPlugin(Plugin):
    meta = PluginMeta(
        id="chunker",
        name="Text Chunker",
        kind=PluginKind.PROCESSOR,
        description="Разбиение текста на чанки",
    )

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        text = data if isinstance(data, str) else ctx.text
        settings = get_settings()
        size = int(ctx.config.get("chunk_size", settings.chunk_size))
        overlap = int(ctx.config.get("chunk_overlap", settings.chunk_overlap))
        chunks = split_text_chunks(text, size, overlap)
        ctx.artifacts["chunks"] = chunks
        return text
