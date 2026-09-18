# -*- coding: utf-8 -*-
"""Режимы анализа кейса: deep (полный) vs shallow (4 класса на validation-Qwen)."""
from __future__ import annotations

from typing import Any, Dict, Optional

ANALYSIS_MODE_DEEP = "deep"
ANALYSIS_MODE_SHALLOW = "shallow"

DEEP_STEPS = {
    "ingest_docx": True,
    "chunk_text": True,
    "qwen_entities": True,
    "qwen_extremism": True,
    "qwen_validation": True,
    "qwen_shallow": False,
    "rubert_entities": True,
    "rubert_danger": False,
    "rubert_fio": True,
    "natasha_entities": True,
    "registry_enrich": True,
    "blocklist_lexicon": True,
    "report_json": True,
}

SHALLOW_STEPS = {
    "ingest_docx": True,
    "chunk_text": True,
    "qwen_entities": False,
    "qwen_extremism": False,
    "qwen_validation": False,
    "qwen_shallow": True,
    "rubert_entities": False,
    "rubert_danger": False,
    "rubert_fio": False,
    "natasha_entities": False,
    "registry_enrich": False,
    "blocklist_lexicon": False,
    "report_json": True,
}


def normalize_analysis_mode(mode: Optional[str]) -> str:
    m = (mode or ANALYSIS_MODE_DEEP).strip().lower()
    if m in ("shallow", "surface", "поверхностный", "быстрый"):
        return ANALYSIS_MODE_SHALLOW
    return ANALYSIS_MODE_DEEP


def enabled_steps_for_mode(
    mode: Optional[str],
    base_steps: Optional[Dict[str, bool]] = None,
) -> Dict[str, bool]:
    """
    shallow — фиксированный короткий пайплайн.
    deep — берём шаги из «Методы» (base_steps), поверх дефолтов deep;
           принудительно выключаем qwen_shallow.
    """
    if normalize_analysis_mode(mode) == ANALYSIS_MODE_SHALLOW:
        return dict(SHALLOW_STEPS)

    steps = dict(DEEP_STEPS)
    if base_steps:
        steps.update({k: bool(v) for k, v in base_steps.items()})
    steps["qwen_shallow"] = False
    steps["ingest_docx"] = True
    steps["chunk_text"] = True
    steps["report_json"] = True
    return steps


def apply_analysis_mode(
    pipeline_config: Optional[dict],
    mode: Optional[str],
) -> Dict[str, Any]:
    """Вернуть pipeline_config с enabled_steps под выбранный режим."""
    cfg = dict(pipeline_config or {})
    mode_n = normalize_analysis_mode(mode)
    cfg["analysis_mode"] = mode_n
    base = cfg.get("enabled_steps") if isinstance(cfg.get("enabled_steps"), dict) else None
    cfg["enabled_steps"] = enabled_steps_for_mode(mode_n, base)
    return cfg
