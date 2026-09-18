# -*- coding: utf-8 -*-
"""Фильтрация ложноположительных dangerous_phrases и оценка уверенности."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+", re.UNICODE)
_YEAR_RE = re.compile(r"(19|20)\d{2}")
_LGBT_META = ("лгбт", "гей", "лесби", "прайд", "meta", "instagram", "facebook")

_NOISE_PHRASE = re.compile(
    r"^("
    r"г\.\s*\w+"
    r"|«?_+\»?"
    r"|№\s*\d+"
    r"|(19|20)\d{2}(\s*год[ауи]?)?"
    r"|«о"
    r"|о\s+внесении"
    r")$",
    re.IGNORECASE,
)

DEFAULT_MIN_CONFIDENCE = 50

PHRASE_SCORE_SYSTEM = (
    "Ты проверяешь фразы, которые другая модель пометила как опасные. "
    "Опасно: агрессия, оскорбления, ненависть, дискриминация, экстремизм, "
    "явные упоминания ЛГБТ, продукты Meta (Facebook/Instagram/WhatsApp). "
    "НЕ опасно: канцелярит, названия ПО, топонимы, даты, номера документов, "
    "нейтральные названия организаций, одобрение власти/Путина. "
    "Для каждой фразы верни: text, is_dangerous (bool), "
    "confidence (целое 0–100 — насколько фраза ОПАСНА: 0=точно безопасно, 100=точно опасно), "
    "reason (кратко). "
    "Ответ только JSON: {\"phrases\": [...]}."
)


def phrase_text(ph: Any) -> str:
    if isinstance(ph, str):
        return ph.strip()
    if isinstance(ph, dict):
        return str(ph.get("text") or "").strip()
    return ""


def _norm_phrase_key(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip(".,!?…;:—-–«»\"'“”")


def _phrase_span(item: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    start = item.get("start_char")
    end = item.get("end_char")
    if start is None:
        start = item.get("start")
    if end is None:
        end = item.get("end")
    if isinstance(start, int) and isinstance(end, int) and end > start:
        return start, end
    return None


def _phrase_nested_in(longer: Dict[str, Any], shorter: Dict[str, Any]) -> bool:
    """Короткая фраза — часть длинной (по тексту или по span в документе)."""
    long_t = phrase_text(longer)
    short_t = phrase_text(shorter)
    if not long_t or not short_t:
        return False
    if long_t == short_t:
        return True
    long_norm = _norm_phrase_key(long_t)
    short_norm = _norm_phrase_key(short_t)
    if short_norm and long_norm and short_norm in long_norm and len(short_norm) < len(long_norm):
        return True
    span_long = _phrase_span(longer)
    span_short = _phrase_span(shorter)
    if span_long and span_short:
        ls, le = span_long
        ss, se = span_short
        if ss >= ls and se <= le and (ss, se) != (ls, le):
            return True
    return False


def dedupe_nested_dangerous_phrases(phrases: List[Any]) -> Tuple[List[Any], List[Any]]:
    """Убрать вложенные/дублирующие фразы — оставить более длинные."""
    items = [normalize_phrase_confidence(p) for p in phrases or [] if phrase_text(p)]
    if len(items) <= 1:
        return items, []

    items.sort(
        key=lambda it: (
            -len(phrase_text(it)),
            -(_phrase_span(it)[1] - _phrase_span(it)[0]) if _phrase_span(it) else 0,
            _phrase_span(it)[0] if _phrase_span(it) else 0,
        )
    )
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for item in items:
        if any(_phrase_nested_in(k, item) for k in kept):
            rejected.append({**item, "reason": item.get("reason") or "nested_in_longer"})
            continue
        kept.append(item)
    return kept, rejected


def _clamp_confidence(v: Any) -> Optional[int]:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


def normalize_phrase_confidence(ph: Any) -> Dict[str, Any]:
    if isinstance(ph, str):
        return {"text": ph.strip()}
    if isinstance(ph, dict):
        out = dict(ph)
        conf = _clamp_confidence(out.get("confidence", out.get("score")))
        if conf is not None:
            out["confidence"] = conf
        return out
    return {"text": str(ph)}


def is_noise_dangerous_phrase(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    if len(s) < 4:
        return True
    if _NOISE_PHRASE.match(s):
        return True
    if re.fullmatch(r"[\d\s«»\"'_.\-–—№/гГод]+", s):
        return True
    tokens = [t for t in _TOKEN_RE.findall(s) if len(t) >= 2]
    if len(tokens) <= 1 and len(s) < 20:
        return True
    if len(tokens) == 1 and _YEAR_RE.fullmatch(tokens[0]):
        return True
    return False


def filter_dangerous_phrases(phrases: List[Any]) -> Tuple[List[Any], List[Any]]:
    kept: List[Any] = []
    rejected: List[Any] = []
    for ph in phrases or []:
        item = normalize_phrase_confidence(ph)
        t = phrase_text(item)
        if is_noise_dangerous_phrase(t):
            item["reason"] = "noise"
            rejected.append(item)
        else:
            kept.append(item)
    return kept, rejected


def text_has_lgbt_meta(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in _LGBT_META)


def phrase_score_user_prompt(full_text: str, phrases: List[Any]) -> str:
    lines = []
    for i, ph in enumerate(phrases, 1):
        item = normalize_phrase_confidence(ph)
        lines.append(f"{i}. {phrase_text(item)}")
    sample = (full_text or "")[:2500]
    return (
        f"Исходный текст (фрагмент):\n{sample}\n\n"
        f"Фразы для проверки:\n" + "\n".join(lines) + "\n\n"
        "Ответ (только JSON):"
    )


def apply_validation_scores(
    phrases: List[Any],
    scored: List[Dict[str, Any]],
    *,
    min_confidence: int = DEFAULT_MIN_CONFIDENCE,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    by_text: Dict[str, Dict[str, Any]] = {}
    for s in scored or []:
        if not isinstance(s, dict):
            continue
        t = phrase_text(s).lower()
        if t:
            by_text[t] = s

    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for ph in phrases or []:
        item = normalize_phrase_confidence(ph)
        key = phrase_text(item).lower()
        score_row = by_text.get(key)
        if score_row:
            conf = _clamp_confidence(score_row.get("confidence"))
            is_dang = score_row.get("is_dangerous")
            det = _clamp_confidence(item.get("confidence"))
            if det is not None:
                item["detector_confidence"] = det
            if is_dang is False or is_dang == "false" or is_dang == 0:
                item["confidence"] = conf if conf is not None else 0
                item["validation_confidence"] = item["confidence"]
                item["reason"] = score_row.get("reason") or "validation_not_dangerous"
                item["scored_by"] = "qwen_validation"
                rejected.append(item)
                continue
            if conf is not None:
                item["confidence"] = conf
                item["validation_confidence"] = conf
                item["scored_by"] = "qwen_validation"
                if score_row.get("reason"):
                    item["reason"] = score_row["reason"]
                if conf < min_confidence:
                    item["reason"] = item.get("reason") or f"confidence<{min_confidence}"
                    rejected.append(item)
                    continue
        kept.append(item)
    return kept, rejected


def apply_validation_to_extremism(
    extremism: Dict[str, Any],
    validation: Dict[str, Any],
    full_text: str,
    *,
    min_confidence: int = DEFAULT_MIN_CONFIDENCE,
) -> Dict[str, Any]:
    out = dict(extremism)
    phrases = [normalize_phrase_confidence(p) for p in (out.get("dangerous_phrases") or [])]
    kept, noise = filter_dangerous_phrases(phrases)
    if noise:
        out.setdefault("rejected_dangerous_phrases", []).extend(
            [{**p, "reason": p.get("reason") or "noise_heuristic"} for p in noise]
        )

    scored = validation.get("phrase_scores") or []
    if scored and kept:
        kept, low = apply_validation_scores(kept, scored, min_confidence=min_confidence)
        if low:
            out.setdefault("rejected_dangerous_phrases", []).extend(low)

    has_offense = bool(validation.get("has_offense"))
    lgbt = text_has_lgbt_meta(full_text)

    if kept and not has_offense and not lgbt and not scored:
        out.setdefault("rejected_dangerous_phrases", []).extend(
            [{**p, "reason": "validation_no_offense"} for p in kept]
        )
        out["dangerous_phrases"] = []
        out["found_dangerous"] = False
        out["ошибочное"] = True
        return out

    kept, nested = dedupe_nested_dangerous_phrases(kept)
    if nested:
        out.setdefault("rejected_dangerous_phrases", []).extend(nested)

    from platform_plugins.processors.text_grounding import ground_phrase_list
    kept, not_in_text = ground_phrase_list(kept, full_text or "", min_len=3)
    if not_in_text:
        out.setdefault("rejected_dangerous_phrases", []).extend(not_in_text)

    out["dangerous_phrases"] = kept
    out["found_dangerous"] = bool(kept)
    if not kept and (noise or scored or not_in_text):
        out["ошибочное"] = True
    return out
