# -*- coding: utf-8 -*-
"""Извлечение сущностей через Natasha: ФИО (PER), организации (ORG), URL.

Titles не извлекаем — Natasha их не умеет.
Нормализация в именительный — span.normalize(MorphVocab) / extract_fact(NamesExtractor).
URL — regex (в NER Natasha нет типа URL).
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_ready = False
_segmenter = None
_morph_vocab = None
_ner_tagger = None
_names_extractor = None
_load_error: Optional[str] = None

_URL_RE = re.compile(
    r"(?i)\b("
    r"(?:https?://|ftp://|www\.)[^\s<>\"']+"
    r"|"
    r"(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+"
    r"(?:ru|рф|com|org|net|info|biz|su|io|me|tv|online|site|xyz|club)"
    r"(?:/[^\s<>\"']*)?"
    r")\b"
)
_TRAIL_PUNCT = ".,;:!?)]}\"»'"


def ensure_natasha_loaded() -> bool:
    global _ready, _segmenter, _morph_vocab, _ner_tagger, _names_extractor, _load_error
    if _ready:
        return True
    with _lock:
        if _ready:
            return True
        try:
            from natasha import (
                Segmenter,
                MorphVocab,
                NewsEmbedding,
                NewsNERTagger,
                NamesExtractor,
            )

            _segmenter = Segmenter()
            _morph_vocab = MorphVocab()
            emb = NewsEmbedding()
            _ner_tagger = NewsNERTagger(emb)
            _names_extractor = NamesExtractor(_morph_vocab)
            _ready = True
            _load_error = None
            logger.info("Natasha NER loaded")
            return True
        except Exception as exc:
            _load_error = str(exc)[:400]
            logger.warning("Natasha load failed: %s", _load_error)
            return False


def load_error() -> Optional[str]:
    return _load_error


def _trim_url(raw: str) -> str:
    t = (raw or "").strip()
    while t and t[-1] in _TRAIL_PUNCT:
        t = t[:-1]
    return t


def extract_urls(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for m in _URL_RE.finditer(text or ""):
        raw = _trim_url(m.group(0))
        if len(raw) < 4:
            continue
        start = m.start()
        end = start + len(raw)
        key = (start, end, raw.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "text": raw,
            "normal": raw,
            "label": "url",
            "start": start,
            "end": end,
            "score": 1.0,
            "method": "natasha_url",
        })
    return out


def _normal_from_span(span, surface: str) -> Tuple[str, Any]:
    """Вернуть (канонический normal / fio, fact или None)."""
    fact = None
    try:
        if _names_extractor is not None and (span.type or "").upper() == "PER":
            span.extract_fact(_names_extractor)
            fact = getattr(span, "fact", None)
    except Exception:
        fact = None

    if (span.type or "").upper() == "PER":
        try:
            from platform_plugins.processors.fio_slots import normalize_fio_phrase
            info = normalize_fio_phrase(surface, natasha_fact=fact)
            return info["fio_normalized"], fact
        except Exception:
            pass

    normal = getattr(span, "normal", None)
    if normal:
        return str(normal), fact
    return surface, fact


def extract_entities_natasha(text: str) -> List[Dict[str, Any]]:
    """PER → fio, ORG → organization, URL → url. Titles не извлекаются."""
    if not text or not text.strip():
        return []
    if not ensure_natasha_loaded():
        return []

    from natasha import Doc

    doc = Doc(text)
    doc.segment(_segmenter)
    doc.tag_ner(_ner_tagger)

    entities: List[Dict[str, Any]] = []
    for span in doc.spans or []:
        typ = (span.type or "").upper()
        if typ not in ("PER", "ORG"):
            continue
        try:
            span.normalize(_morph_vocab)
        except Exception:
            pass
        surface = text[span.start:span.stop]
        if typ == "PER":
            normal, fact = _normal_from_span(span, surface)
            label = "fio"
            item = {
                "text": surface,
                "normal": normal,
                "label": label,
                "start": int(span.start),
                "end": int(span.stop),
                "score": 1.0,
                "method": "natasha",
                "natasha_type": typ,
            }
            try:
                from platform_plugins.processors.fio_slots import enrich_person_entity
                item = enrich_person_entity(item, natasha_fact=fact)
            except Exception:
                pass
            entities.append(item)
        else:
            normal = getattr(span, "normal", None) or surface
            entities.append({
                "text": surface,
                "normal": str(normal),
                "label": "organization",
                "start": int(span.start),
                "end": int(span.stop),
                "score": 1.0,
                "method": "natasha",
                "natasha_type": typ,
            })

    entities.extend(extract_urls(text))
    entities.sort(key=lambda e: (e["start"], -(e["end"] - e["start"])))
    return entities


def natasha_to_typed_dict(entities: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {
        "persons": [],
        "organizations": [],
        "titles": [],
        "urls": [],
    }
    key_map = {
        "fio": "persons",
        "person": "persons",
        "organization": "organizations",
        "url": "urls",
    }
    for e in entities:
        key = key_map.get(str(e.get("label") or ""))
        if not key:
            continue
        out[key].append({
            "text": e.get("text"),
            "normal": e.get("normal") or e.get("text"),
            "fio_normalized": e.get("fio_normalized") or e.get("normal"),
            "fio_parts": e.get("fio_parts"),
            "fio_source": e.get("fio_source"),
            "start_char": e.get("start"),
            "end_char": e.get("end"),
            "score": e.get("score"),
            "label": e.get("label"),
            "method": e.get("method"),
        })
    return out
