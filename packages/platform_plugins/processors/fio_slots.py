# -*- coding: utf-8 -*-
"""Разбор и канонизация ФИО: фамилия имя отчество | фамилия инициалы.

1) Natasha NamesExtractor (fact.as_dict: first/last/middle) — если доступен.
2) Эвристика слотов (отчества на -вич/-вна, инициалы) — как в RuBERT FIO slots fallback.
3) Опционально: RuBERT FIO-slots модель (FIO_SLOTS_MODEL_PATH), если установлена.
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from platform_plugins.processors.nominative import to_nominative

logger = logging.getLogger(__name__)

_INITIAL_RE = re.compile(
    r"^\s*([А-ЯЁа-яёA-Za-z])\.\s*$|^\s*([А-ЯЁа-яёA-Za-z])\s*$"
)
_PATRONYMIC_SUF = (
    "вич", "вна", "ична", "оглы", "кызы",
    "вича", "вичу", "вичем", "виче", "вной", "вне", "вну", "вною",
    "ича", "ичу", "ичем",
)


def is_initial_token(tok: str) -> bool:
    raw = (tok or "").strip()
    if not raw:
        return False
    if _INITIAL_RE.match(raw):
        return True
    letters = re.sub(r"[^А-ЯЁа-яёA-Za-z]", "", raw)
    return len(letters) == 1


def is_patronymic_token(tok: str) -> bool:
    t = (tok or "").strip().lower().rstrip(".")
    if not t or is_initial_token(tok):
        return False
    return any(t.endswith(s) for s in _PATRONYMIC_SUF)


def format_initial(tok: str) -> str:
    m = _INITIAL_RE.match((tok or "").strip())
    if m:
        ch = (m.group(1) or m.group(2) or "").upper()
        return f"{ch}."
    letters = re.sub(r"[^А-ЯЁа-яёA-Za-z]", "", tok or "")
    if len(letters) == 1:
        return f"{letters.upper()}."
    return (tok or "").strip()


def title_word(tok: str) -> str:
    t = (tok or "").strip()
    if not t:
        return t
    if is_initial_token(t):
        return format_initial(t)
    if "-" in t:
        return "-".join(title_word(p) if p else p for p in t.split("-"))
    return t[:1].upper() + t[1:].lower() if t[0].isalpha() else t


def format_canonical_fio(
    surname: str = "",
    name: str = "",
    patronymic: str = "",
    *,
    to_nom: bool = True,
) -> str:
    """Канон: «Фамилия Имя Отчество» или «Фамилия И.О.»."""
    sur = (surname or "").strip()
    nam = (name or "").strip()
    pat = (patronymic or "").strip()
    if to_nom:
        if sur and not is_initial_token(sur):
            sur = to_nominative(sur) or sur
        if nam and not is_initial_token(nam):
            nam = to_nominative(nam) or nam
        if pat and not is_initial_token(pat):
            pat = to_nominative(pat) or pat

    sur = title_word(sur) if sur else ""
    if not sur and not nam and not pat:
        return ""

    name_init = bool(nam) and is_initial_token(nam)
    pat_init = bool(pat) and is_initial_token(pat)

    if nam and (name_init or pat_init):
        # Фамилия + инициалы
        parts_i = []
        if nam:
            parts_i.append(format_initial(nam))
        if pat:
            parts_i.append(format_initial(pat))
        init = "".join(parts_i) if all(is_initial_token(x) for x in (nam, pat) if x) else " ".join(parts_i)
        # «И.О.» слитно, если оба инициала
        if nam and pat and is_initial_token(nam) and is_initial_token(pat):
            init = f"{format_initial(nam)}{format_initial(pat)}"
        return f"{sur} {init}".strip() if sur else init

    chunks = [c for c in (sur, title_word(nam) if nam else "", title_word(pat) if pat else "") if c]
    return " ".join(chunks)


def _fact_as_dict(fact: Any) -> Dict[str, str]:
    if fact is None:
        return {}
    if hasattr(fact, "as_dict"):
        try:
            d = fact.as_dict
            if callable(d):
                d = d()
            if isinstance(d, dict):
                return {str(k): str(v) for k, v in d.items() if v}
        except Exception:
            pass
    out: Dict[str, str] = {}
    for key in ("first", "last", "middle"):
        v = getattr(fact, key, None)
        if v:
            out[key] = str(v)
    # slots list
    slots = getattr(fact, "slots", None)
    if slots and not out:
        for s in slots:
            k = getattr(s, "key", None) or (s[0] if isinstance(s, (list, tuple)) else None)
            v = getattr(s, "value", None) or (s[1] if isinstance(s, (list, tuple)) and len(s) > 1 else None)
            if k and v:
                out[str(k)] = str(v)
    return out


def parts_from_natasha_fact(fact: Any) -> Dict[str, str]:
    """Natasha: last→фамилия, first→имя, middle→отчество."""
    d = _fact_as_dict(fact)
    return {
        "surname": (d.get("last") or "").strip(),
        "name": (d.get("first") or "").strip(),
        "patronymic": (d.get("middle") or "").strip(),
        "source": "natasha_names",
    }


def parts_from_heuristic(phrase: str) -> Dict[str, str]:
    """Эвристика слотов без модели (аналог RuBERT FIO slots fallback)."""
    raw = (phrase or "").strip()
    raw = re.sub(r"\s+", " ", raw)
    # «И.И.Иванов» / «И. И. Иванов»
    raw = re.sub(r"([А-ЯЁа-яёA-Za-z])\.(?=[А-ЯЁа-яёA-Za-z])", r"\1. ", raw)
    toks = [t for t in raw.replace(",", " ").split() if t.strip()]
    if not toks:
        return {"surname": "", "name": "", "patronymic": "", "source": "heuristic"}

    # Слить «И.» «И.» в отдельные токены уже ок
    surname = name = patronymic = ""

    if len(toks) == 1:
        surname = toks[0]
    elif len(toks) == 2:
        a, b = toks
        if is_initial_token(a) and not is_initial_token(b):
            # И. Иванов
            name, surname = a, b
        elif is_initial_token(b) and not is_initial_token(a):
            surname, name = a, b
        elif is_patronymic_token(b) and not is_patronymic_token(a):
            # Иван Иванович (без фамилии) или Фамилия Отчество — редко
            name, patronymic = a, b
        else:
            # Фамилия Имя (или Имя Фамилия: эвристика — длиннее/первая заглавная как фамилия)
            surname, name = a, b
    else:
        # 3+ токенов
        # И. О. Фамилия / И.О. Фамилия
        if is_initial_token(toks[0]) and is_initial_token(toks[1]):
            name, patronymic, surname = toks[0], toks[1], toks[-1]
        elif is_patronymic_token(toks[1]) and len(toks) == 3:
            # Имя Отчество Фамилия
            name, patronymic, surname = toks[0], toks[1], toks[2]
        elif is_patronymic_token(toks[2]) or (len(toks) >= 3 and is_patronymic_token(toks[-1])):
            # Фамилия Имя Отчество
            surname, name, patronymic = toks[0], toks[1], toks[2] if len(toks) == 3 else toks[-1]
            if len(toks) > 3 and is_patronymic_token(toks[-1]):
                surname, name, patronymic = toks[0], " ".join(toks[1:-1]), toks[-1]
        else:
            surname, name, patronymic = toks[0], toks[1], toks[2] if len(toks) > 2 else ""

    return {
        "surname": surname,
        "name": name,
        "patronymic": patronymic,
        "source": "heuristic",
    }


@lru_cache(maxsize=1)
def _try_load_rubert_fio_slots():
    """Опциональная модель FIO slots (если есть путь и torch)."""
    path = os.environ.get("FIO_SLOTS_MODEL_PATH", "").strip()
    if not path or not os.path.isdir(path):
        return None
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(path)
        model = AutoModelForSequenceClassification.from_pretrained(path)
        model.eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model.to(device)
        labels = ["surname", "name", "patronymic", "other"]
        id2label = getattr(model.config, "id2label", None) or {i: l for i, l in enumerate(labels)}
        return {"tok": tok, "model": model, "device": device, "id2label": id2label, "torch": torch}
    except Exception as exc:
        logger.warning("FIO slots model not loaded: %s", exc)
        return None


def parts_from_rubert_slots(phrase: str) -> Optional[Dict[str, str]]:
    pack = _try_load_rubert_fio_slots()
    if not pack or not phrase:
        return None
    toks = phrase.split()
    if not toks:
        return None
    torch = pack["torch"]
    surname = name = patronymic = ""
    token_labels = []
    seq_ctx = phrase.lower().strip()
    for w in toks:
        w0 = w.replace(".", "")
        enc_s = f"tok={w0} ; seq={seq_ctx}"[:400]
        enc = pack["tok"](enc_s, return_tensors="pt", truncation=True, max_length=64)
        enc = {k: v.to(pack["device"]) for k, v in enc.items()}
        with torch.no_grad():
            logits = pack["model"](**enc).logits
        pid = int(logits.argmax(-1).item())
        lab = str(pack["id2label"].get(pid) or pack["id2label"].get(str(pid)) or "other").lower()
        token_labels.append({"token": w, "label": lab})
        if ("sur" in lab or "фам" in lab or lab == "last") and not surname:
            surname = w
        elif ("patr" in lab or "отч" in lab or "middle" in lab) and not patronymic:
            patronymic = w
        elif ("name" in lab or "first" in lab or "имя" in lab) and not name:
            name = w
    if not surname and toks:
        surname = toks[0]
    return {
        "surname": surname,
        "name": name,
        "patronymic": patronymic,
        "token_labels": token_labels,
        "source": "rubert_fio_slots",
    }


def normalize_fio_phrase(
    phrase: str,
    *,
    natasha_fact: Any = None,
) -> Dict[str, Any]:
    """
    Вернуть fio_parts + fio_normalized (канон для реестра).
    Приоритет: Natasha fact → RuBERT slots (если модель) → эвристика.
    """
    parts: Dict[str, str] = {}
    if natasha_fact is not None:
        parts = parts_from_natasha_fact(natasha_fact)
        if not (parts.get("surname") or parts.get("name")):
            parts = {}
    if not parts:
        rubert = parts_from_rubert_slots(phrase)
        if rubert and (rubert.get("surname") or rubert.get("name")):
            parts = rubert
    if not parts:
        parts = parts_from_heuristic(phrase)

    fio_norm = format_canonical_fio(
        parts.get("surname", ""),
        parts.get("name", ""),
        parts.get("patronymic", ""),
        to_nom=True,
    )
    if not fio_norm:
        fio_norm = to_nominative(phrase) or phrase

    return {
        "fio_parts": {
            "surname": parts.get("surname", ""),
            "name": parts.get("name", ""),
            "patronymic": parts.get("patronymic", ""),
        },
        "fio_normalized": fio_norm,
        "fio_source": parts.get("source", "unknown"),
        "token_labels": parts.get("token_labels"),
    }


def enrich_person_entity(ent: Dict[str, Any], *, natasha_fact: Any = None) -> Dict[str, Any]:
    """Дописать normal / fio_* для person/fio сущности."""
    out = dict(ent)
    surface = str(out.get("text") or "").strip()
    if not surface:
        return out
    fact = natasha_fact
    if fact is None and out.get("natasha_fact"):
        fact = out.get("natasha_fact")
    info = normalize_fio_phrase(surface, natasha_fact=fact)
    out["fio_parts"] = info["fio_parts"]
    out["fio_normalized"] = info["fio_normalized"]
    out["fio_source"] = info["fio_source"]
    # для реестра — канонический именительный порядок
    out["normal"] = info["fio_normalized"]
    if info.get("token_labels"):
        out["fio_token_labels"] = info["token_labels"]
    return out
