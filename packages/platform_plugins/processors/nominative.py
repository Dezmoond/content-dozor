# -*- coding: utf-8 -*-
"""Приведение русских фраз к именительному падежу (для поиска по реестрам)."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import List, Optional

_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё\-]+|[^\s]", re.UNICODE)
_CYR_RE = re.compile(r"[А-Яа-яЁё]")
_PUNCT_ATTACH = set(".,;:!?»)»\"'")


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


def _restore_case(original: str, normalized: str) -> str:
    if not original or not normalized:
        return normalized
    if original.isupper():
        return normalized.upper()
    if original[:1].isupper():
        return normalized[:1].upper() + normalized[1:]
    return normalized


def _word_to_nominative(word: str) -> str:
    if not word or not _CYR_RE.search(word):
        return word
    if "-" in word and not word.startswith("-") and not word.endswith("-"):
        return "-".join(_word_to_nominative(p) if p else p for p in word.split("-"))

    morph = _morph()
    if morph is None:
        return word
    try:
        parsed = morph.parse(word)
        if not parsed:
            return word
        p0 = parsed[0]
        for gram in ({"nomn"}, {"nomn", "sing"}, {"nomn", "plur"}):
            inf = p0.inflect(gram)
            if inf is not None:
                return _restore_case(word, inf.word)
        return _restore_case(word, p0.normal_form)
    except Exception:
        return word


def to_nominative(phrase: str) -> str:
    """
    «Максима Галкина» → «Максим Галкин»
    «Читинского лесхозов» → ближайший именительный по словам
    """
    s = (phrase or "").strip()
    if not s:
        return s
    if re.search(r"(https?://|www\.|\.[a-z]{2,6}\b)", s, re.I):
        return s

    tokens = _TOKEN_RE.findall(s)
    out: List[str] = []
    for tok in tokens:
        if _CYR_RE.search(tok) and len(tok) > 1:
            word = _word_to_nominative(tok)
        else:
            word = tok
        if not out:
            out.append(word)
            continue
        if word in _PUNCT_ATTACH:
            out[-1] = out[-1] + word
        elif out[-1] in "(«\"'":
            out[-1] = out[-1] + word
        elif word in "(«\"'":
            out.append(" " + word)
        else:
            out.append(" " + word)
    return "".join(out).strip()


def pick_search_form(surface: str, normal: Optional[str] = None) -> str:
    """Именительный для CSV: Natasha normal или морфология от surface."""
    surf = (surface or "").strip()
    nom = (normal or "").strip()
    if nom and nom.lower() != surf.lower():
        # Natasha уже нормализовала — дополнительно прогоняем слова (на случай смеси)
        converted = to_nominative(nom)
        return converted or nom
    converted = to_nominative(surf)
    return converted or nom or surf
