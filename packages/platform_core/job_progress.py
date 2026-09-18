# -*- coding: utf-8 -*-
"""Обновление прогресса задачи в cases service."""
from __future__ import annotations

from typing import Optional

import httpx

from platform_core.config import get_settings

STEP_LABELS_RU = {
    "ingest_docx": "Извлечение текста",
    "chunk_text": "Чанкинг текста",
    "qwen_entities": "Qwen — сущности",
    "qwen_extremism": "Qwen — опасные фразы",
    "qwen_validation": "Qwen — проверка ложных срабатываний",
    "qwen_shallow": "Qwen — поверхностный анализ (4 класса)",
    "rubert_entities": "RuBERT — сущности",
    "rubert_danger": "RuBERT — опасность",
    "rubert_fio": "RuBERT — ФИО",
    "natasha_entities": "Natasha — ФИО / организации / URL",
    "registry_enrich": "Сверка с реестрами",
    "blocklist_lexicon": "Запретный лексикон",
    "report_json": "Формирование отчёта",
    "queue": "Постановка в очередь",
    "finalize": "Сохранение результатов",
}


def step_label(step_id: str) -> str:
    return STEP_LABELS_RU.get(step_id, step_id)


def report_job_progress(
    job_id: str,
    progress: int,
    step_id: str,
    *,
    status: str = "running",
    cases_url: Optional[str] = None,
) -> None:
    if not job_id:
        return
    settings = get_settings()
    base = cases_url or settings.cases_service_url
    progress = max(0, min(100, int(progress)))
    try:
        with httpx.Client(base_url=base, timeout=10.0) as client:
            client.patch(
                f"/jobs/{job_id}",
                json={
                    "status": status,
                    "progress": progress,
                    "detail": step_label(step_id),
                },
            )
    except Exception:
        pass
