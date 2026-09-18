# -*- coding: utf-8 -*-
"""Сверка найденных сущностей с реестрами (не всего текста по CSV)."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from platform_core.config import get_settings
from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

# Значимый токен: буквы/цифры, не «чистый» номер документа
_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+", re.UNICODE)
_YEAR_RE = re.compile(r"^(19|20)\d{2}(г\.?|год[ау]?)?$", re.IGNORECASE)
_NUM_ONLY_RE = re.compile(r"^[\d№#.\-–—/\s]+$")
_DATE_LIKE_RE = re.compile(
    r"^(\d{1,2}[./]\d{1,2}[./]\d{2,4}|«?_+\»?\s*[._]*\s*(19|20)\d{2}|г\.\s*[А-Яа-яЁё]+)$",
    re.IGNORECASE,
)

# Стоп-слова / шум для token overlap
_STOP = {
    "и", "в", "во", "на", "по", "с", "со", "к", "ко", "о", "об", "от", "до", "за",
    "из", "у", "для", "при", "над", "под", "про", "без", "или", "а", "но", "же",
    "год", "года", "году", "г", "№", "n", "от", "закон", "законе", "статья",
    "статьи", "п", "пп", "the", "of", "and", "to",
}

KIND_SOURCES = {
    # ФИО: Росфинмониторинг + иноагенты (parser5/6)
    # Для parser5/6 колонки ищутся по заголовку (см. _resolve_named_cols), индексы — fallback.
    "person": [
        ("fio", "parser1_data_физические_лица.csv", 1, None),
        ("fio_foreign_p5", "parser5_data.csv", 1, ("Тип иностранного агента", "Физические лица")),
        ("fio_foreign_p6", "parser6_data.csv", 1, ("Тип иностранного агента", "Физические лица")),
    ],
    "organization": [
        ("organization", "parser1_data_организации.csv", 1, None),
        ("org_foreign_p5", "parser5_data.csv", 1, ("Тип иностранного агента", "!Физические лица")),
        ("org_foreign_p6", "parser6_data.csv", 1, ("Тип иностранного агента", "!Физические лица")),
    ],
    "title": [("title", "parser7_exportfsm.csv", 1, None)],
    "url": [("url", "rknweb_blocked_sites.csv", 2, None)],
}

# Колонка значения (ФИО / наименование) в CSV иноагентов — по подстроке заголовка
_FOREIGN_VALUE_HEADER_HINTS = (
    "полное наименование",
    "фио",
    "псевдоним",
)

# Человекочитаемые названия реестров для UI / HTML
SOURCE_TITLES = {
    "fio": "Каталог террористов и экстремистов Росфинмониторинга (ФЛ)",
    "fio_foreign_p5": "Реестр иноагентов Минюста",
    "fio_foreign_p6": "Реестр иноагентов Минюста",
    "organization": "Каталог Росфинмониторинга (организации)",
    "org_foreign_p5": "Реестр иноагентов Минюста (организации)",
    "org_foreign_p6": "Реестр иноагентов Минюста (организации)",
    "title": "Перечень экстремистских материалов Минюста",
    "url": "Реестр заблокированных сайтов (РКН)",
}

# Суффиксы для stem-сравнения ФИО (если склонение не помогло) — из notebook
_FIO_STEM_SUFFIXES = tuple(
    sorted(
        {
            "ОВШЕ", "ЕВШЕ", "ИВШЕ", "ЫМИ", "ИМИ", "СКОГО", "СКОМУ", "СКИМ", "СКИХ", "СКАМ", "СКАХ",
            "ОГО", "ЕГО", "ОМУ", "ЕМУ", "ОЮ", "ЕЮ", "УЮ", "ОЙ", "ЕЙ", "УЙ", "ЫЙ", "ИЙ",
            "АЯ", "ЯЯ", "ОЕ", "ЕЕ", "ИЕ", "УЕ", "ЫМ", "ИМ", "ОМ", "ЕМ", "АМ", "ЯМ", "АХ", "ЯХ",
            "ОВ", "ЕВ", "ИВ", "ЫВ", "ИН", "ОН", "ЕН", "АН", "ЯН", "УН",
            "А", "У", "Е", "О", "Ы", "И", "Я", "Ю", "Ё",
        },
        key=len,
        reverse=True,
    )
)

LABEL_TO_KIND = {
    "persons": "person",
    "person": "person",
    "fio": "person",
    "organizations": "organization",
    "organization": "organization",
    "titles": "title",
    "title": "title",
    "urls": "url",
    "url": "url",
}


def _significant_tokens(text: str) -> List[str]:
    toks: List[str] = []
    for raw in _TOKEN_RE.findall(text or ""):
        t = raw.lower().strip(".")
        if len(t) < 2:
            continue
        if t in _STOP:
            continue
        if _YEAR_RE.match(t):
            continue
        if t.isdigit() and len(t) <= 4:
            continue
        toks.append(t)
    return toks


def is_noise_query(text: str, *, kind: str = "") -> bool:
    """Отсекает даты, номера, ««О», слишком короткие фрагменты."""
    s = (text or "").strip()
    if not s:
        return True
    if _NUM_ONLY_RE.match(s):
        return True
    if _DATE_LIKE_RE.match(s):
        return True
    # чистый год / «2006 год»
    if _YEAR_RE.match(s.replace(" ", "")):
        return True
    if re.fullmatch(r"(19|20)\d{2}\s*год[ауи]?", s, re.IGNORECASE):
        return True
    # обрывки вроде ««О», «О », «№ 1»
    compact = re.sub(r"[\s«»\"'`]+", "", s)
    if len(compact) <= 2:
        return True
    if re.fullmatch(r"№?\d{1,4}", compact):
        return True

    tokens = _significant_tokens(s)
    if kind == "url":
        return len(s) < 4
    if kind == "person":
        # ФИО: минимум 2 значимых токена (фамилия+имя) или один длинный
        return len(tokens) < 2 and not (len(tokens) == 1 and len(tokens[0]) >= 5)
    # organization / title: ≥ 3 значимых слова
    return len(tokens) < 3


def is_noise_registry_entry(entry: str) -> bool:
    s = (entry or "").strip()
    if not s or len(s) < 5:
        return True
    if _NUM_ONLY_RE.match(s):
        return True
    if re.fullmatch(r"(19|20)\d{2}", s):
        return True
    if len(_significant_tokens(s)) < 2 and len(s) < 20:
        return True
    return False


def _find_header_col(header: List[str], *needles: str) -> Optional[int]:
    """Индекс колонки по подстрокам в заголовке (без учёта регистра)."""
    lowered = [(i, (h or "").lower()) for i, h in enumerate(header)]
    for needle in needles:
        n = needle.lower()
        for i, h in lowered:
            if n in h:
                return i
    return None


def _load_csv_column(
    path: Path,
    col: int,
    min_len: int = 5,
    *,
    type_filter: Optional[Tuple[Any, str]] = None,
) -> List[Tuple[str, int]]:
    """
    Возвращает [(значение, номер_строки_в_файле)], строка 1 = заголовок.

    type_filter:
      (int, "Физические лица") — фильтр по индексу колонки типа;
      ("Тип иностранного агента", "Физические лица") — фильтр по имени заголовка;
      префикс «!» у значения — исключить строки с этим типом.
    Для parser5/6 значение (ФИО) ищется по заголовку, если col не попал в «ФИО/наименование».
    """
    if not path.is_file():
        return []
    out: List[Tuple[str, int]] = []
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            with path.open(encoding=enc, newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None) or []
                # значение: предпочитаем колонку ФИО/наименования для иноагентов
                value_col = col
                if path.name.startswith("parser5") or path.name.startswith("parser6"):
                    named = _find_header_col(header, *_FOREIGN_VALUE_HEADER_HINTS)
                    if named is not None:
                        value_col = named
                type_col: Optional[int] = None
                type_val = ""
                if type_filter is not None:
                    tkey, type_val = type_filter
                    if isinstance(tkey, int):
                        type_col = tkey
                    else:
                        type_col = _find_header_col(header, str(tkey), "тип иностранного")
                        if type_col is None and isinstance(tkey, str) and tkey.isdigit():
                            type_col = int(tkey)
                line_no = 1
                for row in reader:
                    line_no += 1
                    if value_col >= len(row):
                        continue
                    if type_filter is not None and type_col is not None:
                        if type_col >= len(row):
                            continue
                        cell_type = (row[type_col] or "").strip()
                        exclude = type_val.startswith("!")
                        needle = type_val[1:] if exclude else type_val
                        has = needle.lower() in cell_type.lower()
                        if exclude and has:
                            continue
                        if not exclude and not has:
                            continue
                    v = (row[value_col] or "").strip().strip('"')
                    if len(v) >= min_len and not is_noise_registry_entry(v):
                        out.append((v, line_no))
            break
        except UnicodeDecodeError:
            continue
    return out


def _fio_stem_token(tok: str) -> str:
    """Обрезка падежных окончаний: ГАЛКИНА→ГАЛКИН→ГАЛК, МАКСИМА→МАКСИМ."""
    tok = (tok or "").strip().upper().rstrip(".")
    if not tok or len(tok) < 4:
        return tok
    changed = True
    while changed and len(tok) >= 4:
        changed = False
        for suf in _FIO_STEM_SUFFIXES:
            if tok.endswith(suf) and len(tok) - len(suf) >= 3:
                tok = tok[: -len(suf)]
                changed = True
                break
    return tok


def _fio_tokens_stemmed(text: str) -> List[str]:
    return [_fio_stem_token(t) for t in _significant_tokens(text) if _fio_stem_token(t)]


def _fio_stem_compatible(query: str, entry: str) -> bool:
    """
    Совпадение ФИО по основам (если склонение/именительный не помогли).
    «Галкин Максим» ↔ «Галкин Максим Александрович»
    «Максима Галкина» ↔ то же.
    """
    qt = _fio_tokens_stemmed(query)
    et = _fio_tokens_stemmed(entry)
    if not qt or not et:
        return False
    if len(qt) >= 2:
        q2 = qt[:2]
        if all(any(e == q or e.startswith(q) or q.startswith(e) for e in et) for q in q2):
            return True
    if len(qt) == 1 and len(qt[0]) >= 5:
        return any(e == qt[0] or e.startswith(qt[0]) or qt[0].startswith(e) for e in et if len(e) >= 4)
    et_set = set(et)
    if len(qt) >= 2 and all(
        q in et_set or any(e.startswith(q) or q.startswith(e) for e in et) for q in qt
    ):
        return True
    return False


def _token_overlap_ok(query: str, entry: str, min_shared: int = 3) -> bool:
    qt = set(_significant_tokens(query))
    et = set(_significant_tokens(entry))
    if not qt or not et:
        return False
    shared = qt & et
    if len(shared) >= min_shared:
        return True
    # короткие запросы (ФИО из 2 токенов): оба должны входить
    if len(qt) <= 2 and qt.issubset(et):
        return True
    # доля покрытия запроса
    if len(shared) / max(1, len(qt)) >= 0.8 and len(shared) >= 2:
        return True
    return False


def _match_entity_to_entries(
    query: str,
    entries: List[Tuple[str, int]],
    *,
    kind: str,
    fuzzy_threshold: int = 90,
) -> Optional[Tuple[str, int, int]]:
    """Возвращает (запись, score, номер_строки) или None."""
    q = query.strip()
    if is_noise_query(q, kind=kind):
        return None
    ql = q.lower()
    best: Optional[Tuple[str, int, int]] = None

    for entry, row_no in entries:
        el = entry.lower()
        # точное вхождение сущности в строку реестра или наоборот (полное)
        if ql == el or (len(ql) >= 12 and (ql in el or el in ql)):
            if _token_overlap_ok(q, entry, min_shared=2 if kind == "person" else 3) or ql == el:
                score = 100
                if best is None or score > best[1]:
                    best = (entry, score, row_no)
                continue
        # пересечение значимых слов (≥3 для org/title)
        min_shared = 2 if kind in ("person", "url") else 3
        if _token_overlap_ok(q, entry, min_shared=min_shared):
            score = 95
            if best is None or score > best[1]:
                best = (entry, score, row_no)
            continue
        # fuzzy только для достаточно длинных сущностей
        if fuzz and len(q) >= 12 and len(entry) >= 12:
            score = int(fuzz.WRatio(ql, el))
            if score >= fuzzy_threshold and _token_overlap_ok(q, entry, min_shared=2):
                if best is None or score > best[1]:
                    best = (entry, score, row_no)
                continue
        # ФИО: stem (срез окончаний), если токены/склонение не совпали
        if kind == "person" and _fio_stem_compatible(q, entry):
            score = 92
            if best is None or score > best[1]:
                best = (entry, score, row_no)
    return best


def collect_entities(artifacts: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Собирает сущности для поиска в реестре.
    В text кладётся именительный (для CSV); surface — форма из документа.
    """
    from platform_plugins.processors.nominative import pick_search_form

    out: List[Dict[str, str]] = []
    seen: Set[str] = set()

    def _add(surface: str, kind: str, normal: str = "") -> None:
        surf = (surface or "").strip()
        if not surf:
            return
        # Для ФИО normal уже канон «Фамилия Имя Отчество» из fio_slots
        query = pick_search_form(surf, normal or None)
        key = f"{kind}|{query.lower()}"
        if key in seen:
            return
        seen.add(key)
        out.append({
            "text": query,
            "surface": surf,
            "normal": query,
            "kind": kind,
        })

    qwen = artifacts.get("entities") or {}
    if isinstance(qwen, dict):
        for key, kind in (
            ("persons", "person"),
            ("organizations", "organization"),
            ("titles", "title"),
            ("urls", "url"),
        ):
            for item in qwen.get(key) or []:
                if isinstance(item, dict):
                    _add(
                        str(item.get("text") or ""),
                        kind,
                        normal=str(
                            item.get("fio_normalized")
                            or item.get("normal")
                            or ""
                        ),
                    )
                elif isinstance(item, str):
                    _add(item, kind)

    for src_key in ("rubert_entities", "natasha_entities"):
        for item in artifacts.get(src_key) or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "")
            kind = LABEL_TO_KIND.get(label)
            if not kind:
                continue
            _add(
                str(item.get("text") or ""),
                kind,
                normal=str(
                    item.get("fio_normalized")
                    or item.get("normal")
                    or ""
                ),
            )

    return out


def enrich_hits_from_entities(
    entities: List[Dict[str, str]],
    blacklist_dir: str,
    fuzzy_threshold: int = 90,
) -> List[Dict[str, Any]]:
    base = Path(blacklist_dir)
    cache: Dict[str, List[Tuple[str, int]]] = {}
    hits: List[Dict[str, Any]] = []
    hit_keys: Set[str] = set()

    for ent in entities:
        kind = ent.get("kind") or ""
        # поиск по именительному
        query = ent.get("text") or ent.get("normal") or ""
        surface = ent.get("surface") or query
        if is_noise_query(query, kind=kind) and is_noise_query(surface, kind=kind):
            continue
        search_text = query if not is_noise_query(query, kind=kind) else surface
        if is_noise_query(search_text, kind=kind):
            continue
        for source_id, filename, col, type_filter in KIND_SOURCES.get(kind, []):
            cache_key = f"{source_id}:{col}:{type_filter}"
            if cache_key not in cache:
                cache[cache_key] = _load_csv_column(
                    base / filename, col, min_len=5, type_filter=type_filter
                )
            matched = _match_entity_to_entries(
                search_text, cache[cache_key], kind=kind, fuzzy_threshold=fuzzy_threshold
            )
            if not matched:
                continue
            entry, score, row_no = matched
            hk = f"{source_id}|{entry.lower()}|{search_text.lower()}"
            if hk in hit_keys:
                continue
            hit_keys.add(hk)
            title = SOURCE_TITLES.get(source_id) or source_id
            hits.append({
                "source": source_id,
                "source_title": title,
                "file": filename,
                "row": row_no,
                "kind": kind,
                "match": entry,
                "entity": search_text,
                "query": search_text,
                "surface": surface,
                "score": score,
                "label": f"{title}, строка {row_no}",
            })
    return hits


# обратная совместимость: старый API больше не сканирует весь текст по CSV
def enrich_hits(text: str, blacklist_dir: str, threshold: int = 85) -> List[Dict[str, Any]]:
    """Deprecated: без сущностей совпадений нет (защита от ложных дат/номеров)."""
    _ = text, threshold
    return []


@register_plugin_class
class RegistryEnrichPlugin(Plugin):
    meta = PluginMeta(
        id="registry_enrich",
        name="Registry Enrich",
        kind=PluginKind.PROCESSOR,
        description="Сверка сущностей с реестрами (≥3 значимых слова)",
    )

    async def process(self, ctx: PipelineContext, data: Any) -> Any:
        settings = get_settings()
        bl_dir = ctx.config.get("blacklist_dir") or settings.resolved_blacklist_dir()
        entities = collect_entities(ctx.artifacts)
        # Не ищем в реестре то, чего нет в тексте (галлюцинации LLM)
        from platform_plugins.processors.text_grounding import text_contains
        source = ctx.text or ctx.artifacts.get("raw_text") or ""
        if source:
            filtered = []
            for e in entities:
                kind = e.get("kind") or ""
                allow = kind in ("person", "organization")
                # проверяем вхождение формы из документа (surface), не именительного
                surface = e.get("surface") or e.get("text") or ""
                if text_contains(source, surface, allow_inflection=allow):
                    filtered.append(e)
            entities = filtered
        hits = enrich_hits_from_entities(entities, bl_dir)
        if source:
            hits = [
                h for h in hits
                if isinstance(h, dict) and text_contains(
                    source,
                    str(h.get("surface") or h.get("query") or h.get("match") or h.get("text") or ""),
                    allow_inflection=(h.get("kind") in ("person", "organization", "fio")),
                )
            ]
        ctx.artifacts["registry_hits"] = hits
        ctx.artifacts["registry_query_entities"] = [
            {
                "text": e.get("text"),
                "surface": e.get("surface"),
                "kind": e.get("kind"),
            }
            for e in entities
            if not is_noise_query(e.get("text") or "", kind=e.get("kind") or "")
        ]
        return data
