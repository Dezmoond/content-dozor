# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from docx import Document as DocxDocument

from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class


@register_plugin_class
class DocxExtractPlugin(Plugin):
    meta = PluginMeta(
        id="docx_extract",
        name="DOCX Extract",
        kind=PluginKind.PROCESSOR,
        description="Извлечение текста из DOCX",
    )

    async def process(self, ctx: PipelineContext, data: Any) -> str:
        if isinstance(data, str) and data.strip() and not ctx.artifacts.get("docx_path"):
            ctx.text = data
            return data
        path = ctx.artifacts.get("docx_path") or data
        if not path:
            return ctx.text
        text = read_docx_text(str(path))
        ctx.text = text
        ctx.artifacts["raw_text"] = text
        return text


def read_docx_text(path: str, join_with: str = "\n") -> str:
    doc = DocxDocument(path)
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return join_with.join(parts)
