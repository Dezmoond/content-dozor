# -*- coding: utf-8 -*-
"""Привязка LLM-находок к исходному тексту (анти-галлюцинации).

Фраза/сущность принимается только если она встречается в документе
(или в склоняемой форме для ФИО/организаций).
Иначе отбрасывается и не попадает в отчёт / разметку / findings.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

_DASH_CLASS = r"[\s\u2010-\u2015\-−]+"
_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+", re.UNICODE)

# Типичные окончания рус. падежей (эвристика, если нет pymorphy)
_RU_SUFFIXES = (
    "ого", "ему", "ому", "ыми", "ами", "ями", "ией", "ой", "ей", "ий", "ый",
    "ая", "яя", "ое", "ее", "ые", "ие", "ов", "ев", "ёв", "ин", "ын",
    "ом", "ем", "ём", "ам", "ям", "ах", "ях", "ую", "юю",
    "а", "я", "у", "ю", "ы", "и", "е", "о",
)


@lru_cache(maxsize=1)
def _morph():
    try:
        from pymorphy2 import MorphAnalyzer
        return MorphAnalyzer()
    except Exception:
        try:
            from pymorphy3 import MorphAnalyzer
            return MorphAnalyzer()
        except Exception:
            return None


def phrase_of(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("text", "match", "phrase", "entity"):
            v = item.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def _span_of(item: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    start = item.get("start_char")
    end = item.get("end_char")
    if start is None:
        start = item.get("start")
    if end is None:
        end = item.get("end")
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end:
        return start, end
    return None


def _ru_stem(word: str) -> str:
    """Основа слова для поиска склонений: Максим←Максима, Галкин←Галкина."""
    w = (word or "").lower().replace("ё", "е").strip()
    if len(w) < 3:
        return w
    morph = _morph()
    if morph is not None:
        try:
            p = morph.parse(w)[0]
            nf = (p.normal_form or w).lower().replace("ё", "е")
            # общий префикс нормальной формы и словоформы
            n = 0
            for a, b in zip(nf, w):
                if a != b:
                    break
                n += 1
            if n >= 3:
                return nf[:n] if n >= 4 else nf
            return nf if len(nf) >= 3 else w
        except Exception:
            pass
    for suf in _RU_SUFFIXES:
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w if len(w) <= 4 else w[:-2]


def find_in_text(
    haystack: str,
    needle: str,
    *,
    allow_inflection: bool = False,
) -> Optional[Tuple[int, int]]:
    """Найти needle в haystack. allow_inflection — для ФИО/орг. со склонениями."""
    if not haystack or not needle:
        return None
    n = needle.strip()
    if len(n) < 2:
        return None

    pos = haystack.find(n)
    if pos >= 0:
        return pos, pos + len(n)

    low_h = haystack.lower()
    low_n = n.lower()
    pos = low_h.find(low_n)
    if pos >= 0:
        return pos, pos + len(n)

    parts = re.split(_DASH_CLASS, n)
    parts = [p for p in parts if p]
    if not parts:
        return None
    pattern = _DASH_CLASS.join(re.escape(p) for p in parts)
    m = re.search(pattern, haystack, flags=re.IGNORECASE | re.UNICODE)
    if m:
        return m.start(), m.end()

    if not allow_inflection:
        return None

    # Склонения: «Максим Галкин» ↔ «Максима Галкина»
    words = _WORD_RE.findall(n)
    if len(words) < 1:
        return None
    stems = [_ru_stem(w) for w in words]
    if any(len(s) < 3 for s in stems):
        # слишком коротко — опасно для ложных срабатываний
        if len(words) == 1 and len(stems[0]) < 4:
            return None
    flex = []
    for stem in stems:
        if len(stem) < 3:
            flex.append(re.escape(stem))
        else:
            flex.append(re.escape(stem) + r"\w{0,8}")
    flex_pat = _DASH_CLASS.join(flex)
    m = re.search(flex_pat, haystack, flags=re.IGNORECASE | re.UNICODE)
    if m:
        return m.start(), m.end()
    return None


def ground_item_to_text(
    item: Any,
    text: str,
    *,
    min_len: int = 2,
    allow_inflection: bool = False,
) -> Optional[Dict[str, Any]]:
    """Dict с text (=форма из документа) + offsets; normal сохраняем отдельно."""
    candidates: List[str] = []
    raw = phrase_of(item)
    if raw:
        candidates.append(raw)
    if isinstance(item, dict):
        # сначала surface (text), потом именительный (normal)
        for key in ("text", "normal"):
            v = str(item.get(key) or "").strip()
            if v and v not in candidates:
                candidates.append(v)

    base: Dict[str, Any] = dict(item) if isinstance(item, dict) else {"text": raw}
    original_normal = None
    if isinstance(item, dict) and item.get("normal"):
        original_normal = str(item.get("normal") or "").strip()
    elif raw:
        # если пришёл только именительный от LLM — сохраним как normal
        original_normal = raw

    span = _span_of(base) if isinstance(item, dict) else None

    if span and span[1] <= len(text):
        slice_ = text[span[0]:span[1]]
        ok = False
        for cand in candidates:
            if not cand or len(cand) < min_len:
                continue
            if slice_ == cand or slice_.lower() == cand.lower():
                ok = True
                break
        if not ok and allow_inflection and len(slice_) >= min_len:
            # offsets указывают на кусок текста — сверим по основам
            if find_in_text(slice_, raw or slice_, allow_inflection=True) or (
                original_normal and find_in_text(slice_, original_normal, allow_inflection=True)
            ):
                ok = True
        if ok:
            base["text"] = slice_
            if original_normal and original_normal.lower() != slice_.lower():
                base["normal"] = original_normal
            base["start_char"] = span[0]
            base["end_char"] = span[1]
            base["start"] = span[0]
            base["end"] = span[1]
            base["grounded"] = True
            return base

    for cand in candidates:
        if len(cand) < min_len:
            continue
        found = find_in_text(text, cand, allow_inflection=allow_inflection)
        if not found:
            continue
        start, end = found
        surface = text[start:end]
        base["text"] = surface
        if original_normal and original_normal.lower() != surface.lower():
            base["normal"] = original_normal
        elif cand.lower() != surface.lower():
            # cand был именительный, в тексте — косвенный
            base["normal"] = cand
        base["start_char"] = start
        base["end_char"] = end
        base["start"] = start
        base["end"] = end
        base["grounded"] = True
        if allow_inflection and cand.lower() != surface.lower():
            base["grounded_via"] = "inflection"
        return base
    return None


def ground_phrase_list(
    phrases: List[Any],
    text: str,
    *,
    min_len: int = 3,
    allow_inflection: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    seen: set = set()
    for ph in phrases or []:
        grounded = ground_item_to_text(
            ph, text, min_len=min_len, allow_inflection=allow_inflection,
        )
        if not grounded:
            rej = dict(ph) if isinstance(ph, dict) else {"text": phrase_of(ph)}
            rej["reason"] = "not_in_source_text"
            rejected.append(rej)
            continue
        key = (grounded["start_char"], grounded["end_char"], grounded["text"].lower())
        if key in seen:
            continue
        seen.add(key)
        kept.append(grounded)
    return kept, rejected


def ground_entities_typed(
    entities: Dict[str, Any],
    text: str,
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {
        "persons": [],
        "organizations": [],
        "titles": [],
        "urls": [],
    }
    rejected: List[Dict[str, Any]] = []
    if not isinstance(entities, dict):
        return out, rejected
    for key in out:
        items = entities.get(key) or []
        if not isinstance(items, list):
            continue
        min_len = 4 if key == "urls" else 2
        # ФИО и организации часто в косвенных падежах; titles/urls — точное вхождение
        allow_infl = key in ("persons", "organizations")
        kept, rej = ground_phrase_list(
            items, text, min_len=min_len, allow_inflection=allow_infl,
        )
        out[key] = kept
        for r in rej:
            r["entity_kind"] = key
            rejected.append(r)
    return out, rejected


def text_contains(haystack: str, needle: str, *, allow_inflection: bool = False) -> bool:
    return find_in_text(haystack, needle, allow_inflection=allow_inflection) is not None
