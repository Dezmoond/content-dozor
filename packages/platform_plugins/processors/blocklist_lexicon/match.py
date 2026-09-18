# -*- coding: utf-8 -*-
"""Поиск запрещённых фраз в тексте по word error rate (jiwer/rapidfuzz)."""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Sequence, Tuple

FORBIDDEN_LEXICON_DEFAULT = "facebook, meta, 1488"
BLOCKLIST_MAX_WER_DEFAULT = 0.25

try:
    from jiwer import wer as _jiwer_wer  # type: ignore
except Exception:  # noqa: BLE001
    _jiwer_wer = None

try:
    from rapidfuzz import fuzz as _rf_fuzz  # type: ignore
except Exception:  # noqa: BLE001
    _rf_fuzz = None

_WORD_TOKEN_RE = re.compile(
    r"[\w\u0400-\u04FF]+(?:['\u2019-][\w\u0400-\u04FF]+)*",
    re.UNICODE,
)


def phrases_to_csv(phrases: Sequence[str]) -> str:
    parts = [p.strip() for p in phrases if p and str(p).strip()]
    return ", ".join(parts)


def parse_forbidden_lexicon(s: str) -> List[List[str]]:
    """Фразы через запятую; внутри фразы слова разделяются пробелами."""
    out: List[List[str]] = []
    if not s or not str(s).strip():
        return out
    for part in str(s).split(","):
        p = part.strip()
        if not p:
            continue
        toks = [t for t in re.split(r"\s+", p) if t]
        if toks:
            out.append(toks)
    return out


def parse_phrases_lines(text: str) -> List[str]:
    """Одна фраза на строку (пустые строки и # комментарии пропускаются)."""
    out: List[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def tokenize_text_word_spans(text: str) -> List[Dict[str, Any]]:
    res: List[Dict[str, Any]] = []
    for m in _WORD_TOKEN_RE.finditer(text or ""):
        raw = m.group(0)
        res.append({"start": m.start(), "end": m.end(), "raw": raw, "lw": raw.casefold()})
    return res


def _phrase_wer_accept(ref_words_lc: List[str], hyp_words_lc: List[str], max_wer: float) -> Tuple[bool, float]:
    if not ref_words_lc or len(ref_words_lc) != len(hyp_words_lc):
        return False, 1.0
    ref_s = " ".join(ref_words_lc)
    hyp_s = " ".join(hyp_words_lc)
    if ref_s == hyp_s:
        return True, 0.0
    if _jiwer_wer is not None:
        try:
            err = float(_jiwer_wer(ref_s.split(), hyp_s.split()))
        except Exception:  # noqa: BLE001
            err = 1.0
        if err <= max_wer:
            return True, err
    if len(ref_words_lc) == 1:
        if _rf_fuzz is not None:
            ratio = float(_rf_fuzz.ratio(ref_s, hyp_s)) / 100.0
        else:
            ratio = float(difflib.SequenceMatcher(None, ref_s, hyp_s).ratio())
        if ratio >= (1.0 - max_wer):
            return True, 1.0 - ratio
    return False, 1.0


def find_forbidden_lexicon_spans(
    text: str,
    lexicon_csv: str,
    max_wer: float = BLOCKLIST_MAX_WER_DEFAULT,
) -> List[Dict[str, Any]]:
    phrases = parse_forbidden_lexicon(lexicon_csv)
    if not phrases:
        return []
    toks = tokenize_text_word_spans(text)
    if not toks:
        return []
    spans: List[Dict[str, Any]] = []
    n_doc = len(toks)
    for phrase in phrases:
        ref_lc = [w.casefold() for w in phrase]
        length = len(ref_lc)
        if length < 1 or length > n_doc:
            continue
        for i in range(0, n_doc - length + 1):
            window = toks[i : i + length]
            hyp_lc = [t["lw"] for t in window]
            ok, err = _phrase_wer_accept(ref_lc, hyp_lc, max_wer)
            if not ok:
                continue
            start = window[0]["start"]
            end = window[-1]["end"]
            chunk = text[start:end]
            spans.append({
                "start": start,
                "end": end,
                "text": chunk,
                "label": "blocked_lexicon",
                "method": "blocklist_wer",
                "score": max(0.0, min(1.0, 1.0 - err)),
                "reference": " ".join(phrase),
            })
    spans.sort(key=lambda s: (s["start"], -s["end"]))
    dedup: List[Dict[str, Any]] = []
    for s in spans:
        if dedup and s["start"] == dedup[-1]["start"] and s["end"] == dedup[-1]["end"]:
            continue
        dedup.append(s)
    return dedup


def find_forbidden_from_phrases(
    text: str,
    phrases: Sequence[str],
    max_wer: float = BLOCKLIST_MAX_WER_DEFAULT,
) -> List[Dict[str, Any]]:
    return find_forbidden_lexicon_spans(text, phrases_to_csv(phrases), max_wer)
