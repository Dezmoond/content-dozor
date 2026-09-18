# -*- coding: utf-8 -*-
"""Stub plugins for future formats."""
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class
from platform_core.context import PipelineContext
from typing import Any


@register_plugin_class
class PdfParserStub(Plugin):
    meta = PluginMeta(id="parser_pdf", name="PDF (stub)", kind=PluginKind.PARSER, enabled=False)

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        return {"status": "not_implemented"}


@register_plugin_class
class HtmlParserStub(Plugin):
    meta = PluginMeta(id="parser_html", name="HTML (stub)", kind=PluginKind.PARSER, enabled=False)

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        return {"status": "not_implemented"}
