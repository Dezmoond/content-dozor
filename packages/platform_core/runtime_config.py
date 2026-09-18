# -*- coding: utf-8 -*-
"""Сборка конфигурации пайплайна из глобальных настроек платформы."""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from platform_core.analysis_modes import apply_analysis_mode
from platform_core.config import get_settings

# Ключи со страницы «Модели», пробрасываются в ctx.config плагинов
_MODEL_SETTING_KEYS = (
    "extremism_model",
    "entities_model",
    "validation_model",
    "temperature",
    "max_tokens",
    "num_ctx",
    "chunk_size",
    "chunk_overlap",
    "min_danger_confidence",
)


async def fetch_platform_settings() -> Dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.cases_service_url, timeout=15.0) as client:
        resp = await client.get("/settings")
        resp.raise_for_status()
        return resp.json()


def merge_pipeline_config(
    pipeline_config: Optional[dict],
    platform_settings: Optional[dict] = None,
    *,
    refresh_steps: bool = False,
) -> dict:
    """
    Собрать runtime-конфиг из настроек платформы.

    refresh_steps=True — взять актуальные Methods (enabled_steps) из БД,
    игнорируя снимок в pipeline_config (нужно перед apply_analysis_mode).
    """
    cfg = dict(pipeline_config or {})
    platform = platform_settings or {}
    pipeline = platform.get("pipeline") or {}

    if refresh_steps:
        cfg.pop("enabled_steps", None)

    if pipeline.get("enabled_steps") and "enabled_steps" not in cfg:
        cfg["enabled_steps"] = dict(pipeline["enabled_steps"])

    if platform.get("forbidden_lexicon") and "forbidden_lexicon" not in cfg:
        cfg["forbidden_lexicon"] = platform["forbidden_lexicon"]

    models = platform.get("models") or {}
    if isinstance(models, dict):
        for key in _MODEL_SETTING_KEYS:
            if key in models and key not in cfg and models[key] is not None:
                cfg[key] = models[key]
        # Прочие кастомные ключи из models тоже пробрасываем
        for key, val in models.items():
            if key not in cfg and val is not None:
                cfg[key] = val

    return cfg


def finalize_pipeline_config(
    pipeline_config: Optional[dict],
    platform_settings: Optional[dict] = None,
) -> dict:
    """
    Полная сборка: актуальные Methods + Модели + лексикон,
    затем режим deep/shallow (deep уважает Methods, shallow — фиксированный).
    """
    cfg = dict(pipeline_config or {})
    mode = cfg.get("analysis_mode")
    cfg = merge_pipeline_config(cfg, platform_settings, refresh_steps=True)
    cfg = apply_analysis_mode(cfg, mode)
    return cfg


async def resolve_pipeline_config(pipeline_config: Optional[dict] = None) -> dict:
    try:
        platform = await fetch_platform_settings()
    except Exception:
        platform = {}
    return finalize_pipeline_config(pipeline_config, platform)
