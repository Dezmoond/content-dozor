# -*- coding: utf-8 -*-
"""Сводка времени обработки пайплайна."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

STEP_LABELS_RU = {
    "ingest_docx": "Извлечение текста",
    "chunk_text": "Разбиение на чанки",
    "qwen_entities": "Qwen: сущности",
    "qwen_extremism": "Qwen: экстремизм",
    "qwen_validation": "Qwen: валидация",
    "qwen_shallow": "Qwen: поверхностный анализ",
    "rubert_entities": "RuBERT: сущности",
    "rubert_danger": "RuBERT: опасность",
    "rubert_fio": "RuBERT: ФИО",
    "natasha_entities": "Natasha: сущности",
    "registry_enrich": "Реестры",
    "blocklist_lexicon": "Запретный лексикон",
    "report_json": "Отчёт JSON",
    "finalize": "Финализация",
}


def format_duration_ms(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f} мс"
    sec = ms / 1000.0
    if sec < 60:
        return f"{sec:.1f} с"
    minutes = int(sec // 60)
    rest = sec % 60
    return f"{minutes} мин {rest:.0f} с"


def build_timing_summary(
    steps_log: List[Dict[str, Any]],
    *,
    total_ms: Optional[float] = None,
    model_loads: Optional[List[Dict[str, Any]]] = None,
    chunk_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    steps_total_ms = 0.0
    for entry in steps_log:
        if entry.get("status") not in ("ok", "error"):
            continue
        ms = float(entry.get("duration_ms") or 0)
        steps_total_ms += ms
        step_id = str(entry.get("step_id", ""))
        steps.append({
            "step_id": step_id,
            "label": STEP_LABELS_RU.get(step_id, step_id),
            "status": entry.get("status"),
            "duration_ms": round(ms, 1),
            "duration_human": format_duration_ms(ms),
            "detail": entry.get("detail"),
        })

    model_load_total = 0.0
    loads_out: List[Dict[str, Any]] = []
    for load in model_loads or []:
        ms = float(load.get("duration_ms") or 0)
        model_load_total += ms
        loads_out.append({
            "role": load.get("role"),
            "gguf": load.get("gguf"),
            "duration_ms": round(ms, 1),
            "duration_human": format_duration_ms(ms),
            "reused": bool(load.get("reused")),
        })

    wall_ms = total_ms if total_ms is not None else steps_total_ms
    return {
        "total_ms": round(wall_ms, 1),
        "total_human": format_duration_ms(wall_ms),
        "steps_total_ms": round(steps_total_ms, 1),
        "steps_total_human": format_duration_ms(steps_total_ms),
        "model_load_total_ms": round(model_load_total, 1),
        "model_load_total_human": format_duration_ms(model_load_total),
        "steps": steps,
        "model_loads": loads_out,
        "chunk_stats": chunk_stats or {},
    }
