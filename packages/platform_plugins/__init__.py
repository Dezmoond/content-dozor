# -*- coding: utf-8 -*-
"""Register all built-in plugins."""
from platform_plugins.processors.chunker import plugin as _chunker  # noqa: F401
from platform_plugins.processors.docx_extract import plugin as _docx  # noqa: F401
from platform_plugins.processors.ingest import plugin as _ingest  # noqa: F401
from platform_plugins.processors.qwen_plugins import (  # noqa: F401
    QwenEntitiesPlugin,
    QwenExtremismPlugin,
    QwenValidationPlugin,
)
from platform_plugins.processors.qwen_shallow_plugin import QwenShallowAnalysisPlugin  # noqa: F401
from platform_plugins.processors.registry_enrich import plugin as _registry  # noqa: F401
from platform_plugins.processors.blocklist_lexicon import plugin as _blocklist  # noqa: F401
from platform_plugins.processors.rubert_plugins import (  # noqa: F401
    RuBertDangerPlugin,
    RuBertEntitiesPlugin,
    RuBertFioPlugin,
)
from platform_plugins.processors.natasha_plugins import NatashaEntitiesPlugin  # noqa: F401
from platform_plugins.exporters.json import plugin as _json_exp  # noqa: F401
from platform_plugins.exporters.html import plugin as _html_exp  # noqa: F401
from platform_plugins.parsers.parser_zapret import plugin as _parser_zapret  # noqa: F401
from platform_plugins.parsers import stubs as _stubs  # noqa: F401
