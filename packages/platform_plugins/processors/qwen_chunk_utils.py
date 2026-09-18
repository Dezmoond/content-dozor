# -*- coding: utf-8 -*-
"""Слияние результатов Qwen по чанкам документа."""
from __future__ import annotations

from typing import Any, Dict, List


def _shift_entity(item: Dict[str, Any], offset: int) -> Dict[str, Any]:
    out = dict(item)
    if isinstance(out.get("start_char"), int):
        out["start_char"] = out["start_char"] + offset
    if isinstance(out.get("end_char"), int):
        out["end_char"] = out["end_char"] + offset
    if isinstance(out.get("start"), int):
        out["start"] = out["start"] + offset
    if isinstance(out.get("end"), int):
        out["end"] = out["end"] + offset
    return out


def _dedupe_entities(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[tuple] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        text = str(item.get("text", "")).strip().lower()
        start = item.get("start_char", item.get("start"))
        key = (text, start)
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def merge_entities_chunk_results(chunk_results: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    merged: Dict[str, List[Dict[str, Any]]] = {
        "persons": [],
        "organizations": [],
        "titles": [],
        "urls": [],
    }
    # синонимы ключей от разных промптов / моделей
    aliases = {
        "persons": ("persons", "person", "fio", "people", "персоны", "лица"),
        "organizations": ("organizations", "organization", "orgs", "организации"),
        "titles": ("titles", "title", "названия"),
        "urls": ("urls", "url", "links"),
    }
    for block in chunk_results:
        offset = int(block.get("chunk_start", 0))
        parsed = block.get("result") or {}
        if not isinstance(parsed, dict):
            continue
        if parsed.get("_parse_error"):
            continue
        # ответ от неправильной (extremism) модели — без полей сущностей
        if "found_dangerous" in parsed and not any(
            k in parsed for group in aliases.values() for k in group
        ):
            continue
        for key, names in aliases.items():
            items = []
            for name in names:
                if name in parsed and parsed[name] is not None:
                    items = parsed[name]
                    break
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    merged[key].append(_shift_entity(item, offset))
                elif isinstance(item, str) and item.strip():
                    merged[key].append({"text": item.strip()})
    for key in merged:
        merged[key] = _dedupe_entities(merged[key])
    return merged


def merge_extremism_chunk_results(chunk_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    phrases: List[Dict[str, Any]] = []
    found = False
    for block in chunk_results:
        offset = int(block.get("chunk_start", 0))
        parsed = block.get("result") or {}
        if not isinstance(parsed, dict):
            continue
        if parsed.get("found_dangerous"):
            found = True
        for ph in parsed.get("dangerous_phrases") or []:
            if isinstance(ph, dict):
                item = dict(ph)
                if isinstance(item.get("start_char"), int):
                    item["start_char"] = item["start_char"] + offset
                if isinstance(item.get("end_char"), int):
                    item["end_char"] = item["end_char"] + offset
                if isinstance(item.get("start"), int):
                    item["start"] = item["start"] + offset
                if isinstance(item.get("end"), int):
                    item["end"] = item["end"] + offset
                phrases.append(item)
            elif isinstance(ph, str) and ph.strip():
                phrases.append({"text": ph.strip(), "chunk_index": block.get("chunk_index")})
    return {"found_dangerous": found, "dangerous_phrases": phrases}
