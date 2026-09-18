# -*- coding: utf-8 -*-
"""RuBERT entity extraction runtime (window classifier)."""
from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_tok = None
_model = None
_id2label: Dict[int, str] = {}
_device = None
_load_error: Optional[str] = None

URL_PATTERN = re.compile(r"https?://[^\s<>\"'\\)]+", re.IGNORECASE)
QUOTE_PAIRS = [("«", "»"), ('"', '"'), ("“", "”")]
ENT_LABELS = ["fio", "organization", "title", "url", "other"]


def _default_model_dir() -> Path:
    env = os.environ.get("RUBERT_MODEL_PATH", "").strip()
    if env:
        return Path(env)
    diplom = Path(os.environ.get("DIPLOM_ROOT", "E:/CURSOR/DIPLOM"))
    for name in (
        "rubert-mini-uncased-15",
        "rubert-mini-uncased",
        "output_tiny2_фио сущности",
    ):
        p = diplom / "RUBERT" / name
        if p.is_dir() and (p / "config.json").is_file():
            return p
    return diplom / "RUBERT" / "rubert-mini-uncased-15"


def ensure_rubert_loaded() -> bool:
    """Lazy-load tokenizer+model. Returns False if unavailable."""
    global _tok, _model, _id2label, _device, _load_error
    if _model is not None:
        return True
    if _load_error is not None:
        return False
    with _lock:
        if _model is not None:
            return True
        if _load_error is not None:
            return False
        model_dir = _default_model_dir()
        if not model_dir.is_dir():
            _load_error = f"RuBERT model dir not found: {model_dir}"
            logger.warning(_load_error)
            return False
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            _tok = AutoTokenizer.from_pretrained(str(model_dir))
            _model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
            _model.to(_device)
            _model.eval()
            raw = getattr(_model.config, "id2label", None) or {}
            _id2label = {int(k): v for k, v in raw.items()}
            if _id2label and str(next(iter(_id2label.values()), "")).startswith("LABEL_"):
                _id2label = {i: ENT_LABELS[i] for i in range(len(ENT_LABELS))}
            logger.info("RuBERT entities loaded from %s on %s", model_dir, _device)
            return True
        except Exception as exc:
            _load_error = str(exc)
            logger.warning("RuBERT load failed: %s", exc)
            _tok = None
            _model = None
            return False


def normalize_for_model(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip().lower()
    text = re.sub(r'[^a-zа-яё0-9\s«»"”“\-–—:;,.()\[\]]', " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_word_spans(text: str) -> List[Tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in re.finditer(r"\S+", text)]


def iter_windows(word_spans, min_w: int = 2, max_w: int = 15):
    n = len(word_spans)
    for length in range(min_w, min(max_w + 1, n + 1)):
        for i in range(n - length + 1):
            start = word_spans[i][0]
            end = word_spans[i + length - 1][1]
            phrase = " ".join(w for _, _, w in word_spans[i : i + length])
            yield start, end, phrase


def extract_quoted_spans(text: str, min_len: int = 2, max_len: int = 120) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(text, str) or not text:
        return out
    for lq, rq in QUOTE_PAIRS:
        start = 0
        while True:
            i = text.find(lq, start)
            if i < 0:
                break
            j = text.find(rq, i + 1)
            if j < 0:
                break
            span = text[i : j + 1]
            inner = text[i + 1 : j].strip()
            if min_len <= len(inner) <= max_len:
                out.append({"start": i, "end": j + 1, "text": span, "inner": inner})
            start = j + 1
    return out


def extract_url_spans(text: str) -> List[Dict[str, Any]]:
    return [
        {"text": m.group(), "label": "url", "start": m.start(), "end": m.end(), "score": 1.0}
        for m in URL_PATTERN.finditer(text or "")
    ]


def _batched_logits(phrases: List[str], max_length: int, batch_size: int):
    import numpy as np
    import torch

    all_logits = []
    for i in range(0, len(phrases), batch_size):
        batch = phrases[i : i + batch_size]
        enc = _tok(
            batch,
            max_length=max_length,
            padding=True,
            truncation=True,
            return_tensors="pt",
        )
        enc = {k: v.to(_device) for k, v in enc.items()}
        with torch.no_grad():
            out = _model(**enc)
        all_logits.append(out.logits.detach().cpu().numpy())
    return np.concatenate(all_logits, axis=0) if all_logits else None


def extract_entities_rubert(
    text: str,
    min_words: int = 1,
    max_words: int = 15,
    batch_size: int = 64,
    confidence_threshold: float = 0.6,
    max_len: int = 128,
) -> List[Dict[str, Any]]:
    if not isinstance(text, str) or not text.strip():
        return []
    if not ensure_rubert_loaded():
        return []

    import torch

    results: List[Dict[str, Any]] = []
    results.extend(extract_url_spans(text))

    word_spans = get_word_spans(text)
    if len(word_spans) < min_words:
        return sorted(results, key=lambda x: x["start"])

    quoted = extract_quoted_spans(text)
    quoted_phrases = [q["text"] for q in quoted]
    quoted_pos = [(q["start"], q["end"]) for q in quoted]

    windows = list(iter_windows(word_spans, min_words, max_words))
    # Cap windows on very long docs to keep latency reasonable
    if len(windows) > 8000:
        step = max(1, len(windows) // 8000)
        windows = windows[::step]

    phrases_orig = [p for _, _, p in windows]
    positions = [(s, e) for s, e, _ in windows]
    phrases_norm = [normalize_for_model(p) for p in phrases_orig]

    logits = _batched_logits(phrases_norm, max_len, batch_size)
    if logits is None:
        return sorted(results, key=lambda x: x["start"])
    probs = torch.softmax(torch.tensor(logits), dim=-1).numpy()
    pred_ids = probs.argmax(axis=-1)
    max_p = probs.max(axis=-1)

    q_preds, q_probs = ([], [])
    if quoted_phrases:
        q_logits = _batched_logits(
            [normalize_for_model(p) for p in quoted_phrases], max_len, batch_size
        )
        if q_logits is not None:
            q_probs_full = torch.softmax(torch.tensor(q_logits), dim=-1).numpy()
            q_preds = q_probs_full.argmax(axis=-1)
            q_probs = q_probs_full.max(axis=-1)

    max_words_per_label = {"fio": 6, "organization": 20, "title": 25}
    thr_by_label = {
        "fio": max(0.70, confidence_threshold),
        "organization": confidence_threshold,
        "title": 0.45,
    }

    for (start, end), phrase, pid, conf in zip(positions, phrases_orig, pred_ids, max_p):
        label = _id2label.get(int(pid), "other")
        if label in ("other", "url"):
            continue
        if float(conf) < thr_by_label.get(label, confidence_threshold):
            continue
        if len(phrase.split()) > max_words_per_label.get(label, 25):
            continue
        results.append({
            "text": phrase,
            "label": label,
            "start": int(start),
            "end": int(end),
            "score": float(conf),
        })

    for (start, end), phrase, pid, conf in zip(quoted_pos, quoted_phrases, q_preds, q_probs):
        label = _id2label.get(int(pid), "other")
        if label not in ("title", "organization"):
            continue
        if float(conf) < thr_by_label.get(label, confidence_threshold):
            continue
        results.append({
            "text": phrase,
            "label": label,
            "start": int(start),
            "end": int(end),
            "score": float(conf),
        })

    def _sort_key(item: Dict[str, Any]):
        length = item["end"] - item["start"]
        conf = -item.get("score", 0.0)
        if item.get("label") in ("title", "organization"):
            return (-length, conf, item["start"])
        return (length, conf, item["start"])

    results = sorted(results, key=_sort_key)
    merged: List[Dict[str, Any]] = []
    for item in results:
        if any(
            prev["label"] == item["label"]
            and not (item["end"] <= prev["start"] or item["start"] >= prev["end"])
            for prev in merged
        ):
            continue
        merged.append(item)
    return sorted(merged, key=lambda x: x["start"])


def rubert_to_typed_dict(entities: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
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
        "title": "titles",
        "url": "urls",
    }
    for e in entities:
        key = key_map.get(str(e.get("label") or ""))
        if not key:
            continue
        out[key].append({
            "text": e.get("text"),
            "start_char": e.get("start"),
            "end_char": e.get("end"),
            "score": e.get("score"),
            "label": e.get("label"),
        })
    return out
