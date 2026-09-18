# -*- coding: utf-8 -*-
"""
Реестр источников анализа.

Чтобы добавить новый тип:
1. Добавить запись в SOURCE_TYPES.
2. Реализовать extractor в platform_plugins/processors/ingest/extractors.py
   и прописать его в DISPATCH.
3. UI подхватит тип через GET /api/v1/ingest/sources.

Пайплайн после ingest всегда работает с плоским текстом — тип источника
на последующие шаги не влияет.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

# file | text | url | url_or_file
# never | optional | required
# ready | expanding

SOURCE_TYPES: List[Dict[str, Any]] = [
    {
        "id": "docx",
        "label": "Документ DOCX",
        "description": "Текстовый документ Microsoft Word (.docx).",
        "input_kind": "file",
        "accept": [".docx"],
        "needs_internet": "never",
        "include_comments": False,
        "status": "ready",
        "placeholder": "",
        "hint": "Один файл .docx на кейс.",
    },
    {
        "id": "pdf",
        "label": "Документ PDF",
        "description": "Текстовый слой PDF. Сканы без OCR пока не разбираются.",
        "input_kind": "file",
        "accept": [".pdf"],
        "needs_internet": "never",
        "include_comments": False,
        "status": "ready",
        "placeholder": "",
        "hint": "Если PDF — скан, текста может не быть. OCR добавим отдельно.",
    },
    {
        "id": "paste",
        "label": "Вставленный текст",
        "description": "Произвольный текст, вставленный в форму.",
        "input_kind": "text",
        "accept": [],
        "needs_internet": "never",
        "include_comments": False,
        "status": "ready",
        "placeholder": "Вставьте текст для анализа…",
        "hint": "Подходит для фрагментов переписок, постов, цитат.",
    },
    {
        "id": "url",
        "label": "Ссылка или HTML",
        "description": "Страница по URL при доступе в интернет, иначе сохранённый HTML.",
        "input_kind": "url_or_file",
        "accept": [".html", ".htm", ".xhtml"],
        "needs_internet": "optional",
        "include_comments": False,
        "status": "ready",
        "placeholder": "https://example.com/article",
        "hint": "Нет сети — приложите сохранённую HTML-страницу.",
    },
    {
        "id": "telegram",
        "label": "Группа / канал Telegram",
        "description": "Публичные посты и комментарии (если есть в превью или HTML-экспорте).",
        "input_kind": "url_or_file",
        "accept": [".html", ".htm"],
        "needs_internet": "optional",
        "include_comments": True,
        "status": "expanding",
        "placeholder": "https://t.me/username или https://t.me/s/username",
        "hint": (
            "С интернетом: публичное превью t.me/s/…. "
            "Без сети: HTML-экспорт чата из Telegram Desktop. "
            "Полный обход комментариев через API — следующий этап."
        ),
    },
    {
        "id": "vk",
        "label": "Паблик ВКонтакте",
        "description": "Посты стены и комментарии из HTML публичной страницы или сохранённого файла.",
        "input_kind": "url_or_file",
        "accept": [".html", ".htm"],
        "needs_internet": "optional",
        "include_comments": True,
        "status": "expanding",
        "placeholder": "https://vk.com/public… или https://vk.com/club…",
        "hint": (
            "С интернетом: открытая страница паблика. "
            "Без сети: сохраните страницу как HTML. "
            "Полный сбор комментариев через VK API — следующий этап."
        ),
    },
]

SOURCE_BY_ID: Dict[str, Dict[str, Any]] = {item["id"]: item for item in SOURCE_TYPES}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

CONNECTIVITY_URLS = (
    "https://ya.ru",
    "https://example.com",
)


def list_source_types() -> List[Dict[str, Any]]:
    return [dict(item) for item in SOURCE_TYPES]


def get_source(source_id: str) -> Dict[str, Any]:
    item = SOURCE_BY_ID.get((source_id or "").strip().lower())
    if not item:
        known = ", ".join(SOURCE_BY_ID)
        raise ValueError(f"Неизвестный источник «{source_id}». Доступны: {known}")
    return dict(item)


def source_label(source_id: Optional[str]) -> str:
    item = SOURCE_BY_ID.get((source_id or "").strip().lower())
    return item["label"] if item else (source_id or "источник")


def probe_internet(timeout: float = 3.0) -> bool:
    headers = {"User-Agent": USER_AGENT}
    for url in CONNECTIVITY_URLS:
        try:
            httpx.head(url, timeout=timeout, follow_redirects=True, headers=headers)
            return True
        except Exception:
            try:
                httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
                return True
            except Exception:
                continue
    return False


def validate_ingest(
    source_type: str,
    *,
    has_file: bool,
    filename: Optional[str],
    text: Optional[str],
    url: Optional[str],
    online: Optional[bool] = None,
) -> Dict[str, Any]:
    """Проверить вход. Возвращает карточку источника или бросает ValueError."""
    spec = get_source(source_type)
    kind = spec["input_kind"]
    url_s = (url or "").strip()
    text_s = (text or "").strip()
    name = (filename or "").strip().lower()
    accept = [a.lower() for a in spec.get("accept") or []]

    if kind == "file":
        if not has_file:
            raise ValueError(f"Для «{spec['label']}» нужен файл")
        if accept and name and not any(name.endswith(a) for a in accept):
            raise ValueError(f"Ожидается файл: {', '.join(accept)}")
        return spec

    if kind == "text":
        if not text_s:
            raise ValueError("Вставьте текст для анализа")
        return spec

    # url | url_or_file
    if url_s:
        return spec

    if has_file:
        if accept and name and not any(name.endswith(a) for a in accept):
            raise ValueError(f"Ожидается HTML-файл: {', '.join(accept)}")
        return spec

    if kind == "url_or_file":
        raise ValueError(
            f"Для «{spec['label']}» укажите ссылку или приложите HTML-файл"
        )
    raise ValueError(f"Для «{spec['label']}» укажите ссылку")
