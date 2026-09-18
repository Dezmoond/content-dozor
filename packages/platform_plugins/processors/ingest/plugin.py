# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class
from platform_plugins.processors.ingest.extractors import extract_from_source, load_source_descriptor


@register_plugin_class
class IngestSourcePlugin(Plugin):
    meta = PluginMeta(
        id="ingest_source",
        name="Ingest Source",
        kind=PluginKind.PROCESSOR,
        description="Извлечение текста из выбранного источника (docx, pdf, текст, URL, Telegram, VK)",
    )

    async def process(self, ctx: PipelineContext, data: Any) -> str:
        artifacts = ctx.artifacts
        if artifacts.get("docx_path") and not artifacts.get("source_path"):
            artifacts["source_path"] = artifacts["docx_path"]
            artifacts.setdefault("source_type", "docx")

        source_type = (
            artifacts.get("source_type")
            or ctx.config.get("source_type")
            or _guess_source_type(artifacts, data)
        )

        path = artifacts.get("source_path") or artifacts.get("docx_path")
        if not path and isinstance(data, str) and data.strip() and Path(str(data)).exists():
            path = data

        url = artifacts.get("source_url") or ""
        include_comments = bool(artifacts.get("include_comments", True))
        pasted = artifacts.get("source_text") or ""

        if path:
            desc = load_source_descriptor(Path(str(path)))
            if desc:
                url = url or str(desc.get("url") or "")
                source_type = source_type or desc.get("source_type")
                include_comments = bool(desc.get("include_comments", include_comments))

        ready_text = isinstance(data, str) and data.strip() and not Path(str(data)).exists()
        if ready_text and not path and not url and not pasted:
            ctx.text = data
            artifacts["raw_text"] = data
            artifacts["source_type"] = source_type or "paste"
            artifacts["ingest_meta"] = {
                "source_type": artifacts["source_type"],
                "chars": len(data),
                "internet_used": False,
            }
            return data

        source_type = source_type or "docx"
        text, meta = await extract_from_source(
            source_type=source_type,
            source_path=str(path) if path else None,
            source_url=url or None,
            source_text=pasted or None,
            include_comments=include_comments,
        )
        if not (text or "").strip():
            raise ValueError("Не удалось извлечь текст из источника")
        ctx.text = text
        artifacts["raw_text"] = text
        artifacts["source_type"] = source_type
        artifacts["ingest_meta"] = meta
        return text


def _guess_source_type(artifacts: dict, data: Any) -> str:
    path = str(artifacts.get("source_path") or artifacts.get("docx_path") or data or "")
    suffix = Path(path).suffix.lower()
    mapping = {
        ".docx": "docx",
        ".pdf": "pdf",
        ".txt": "paste",
        ".html": "url",
        ".htm": "url",
        ".json": "url",
    }
    return mapping.get(suffix, "docx")
