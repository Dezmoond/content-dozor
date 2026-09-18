# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from platform_core.context import PipelineContext


class PluginKind(str, Enum):
    PARSER = "parser"
    PROCESSOR = "processor"
    EXPORTER = "exporter"


class PluginMeta(BaseModel):
    id: str
    name: str
    version: str = "1.0.0"
    kind: PluginKind
    enabled: bool = True
    description: str = ""


class Plugin(ABC):
    meta: PluginMeta

    @abstractmethod
    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        ...

    async def health(self) -> dict:
        return {"status": "ok", "plugin": self.meta.id}


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: Dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        self._plugins[plugin.meta.id] = plugin

    def get(self, plugin_id: str) -> Optional[Plugin]:
        return self._plugins.get(plugin_id)

    def list_plugins(self, kind: Optional[PluginKind] = None) -> List[PluginMeta]:
        items = [p.meta for p in self._plugins.values()]
        if kind:
            items = [m for m in items if m.kind == kind]
        return items

    def enabled_ids(self) -> List[str]:
        return [p.meta.id for p in self._plugins.values() if p.meta.enabled]


_global_registry = PluginRegistry()


def get_registry() -> PluginRegistry:
    return _global_registry


def register_plugin_class(cls: Type[Plugin]) -> Type[Plugin]:
    instance = cls()
    _global_registry.register(instance)
    return cls
