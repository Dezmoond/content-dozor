# -*- coding: utf-8 -*-
"""Размеченный HTML-отчёт с якорями на найденные материалы."""
from __future__ import annotations

import html
from typing import Any, Dict, List, Tuple

from platform_core.context import PipelineContext
from platform_core.plugin import Plugin, PluginKind, PluginMeta, register_plugin_class


def _collect_marks(artifacts: Dict[str, Any]) -> List[Dict[str, Any]]:
    from platform_plugins.processors.text_grounding import find_in_text, phrase_of

    source = artifacts.get("raw_text") or ""
    marks: List[Dict[str, Any]] = []

    def _add_mark(m: Dict[str, Any]) -> None:
        """Добавить mark только если фрагмент есть в тексте (или offsets валидны)."""
        t = phrase_of(m)
        if not t:
            return
        kind = str(m.get("kind") or "")
        label = str(m.get("label") or "")
        allow_infl = (
            kind in ("entity", "registry")
            or "fio" in label
            or "person" in label
            or "org" in label
        )
        start, end = m.get("start"), m.get("end")
        if isinstance(start, int) and isinstance(end, int) and source and 0 <= start < end <= len(source):
            # сверить, что срез похож на сущность (не чужой span)
            slice_ = source[start:end]
            if (
                slice_ == t
                or slice_.lower() == t.lower()
                or (allow_infl and find_in_text(slice_, t, allow_inflection=True))
            ):
                m = {**m, "text": slice_}
                marks.append(m)
                return
        if source:
            found = find_in_text(source, t, allow_inflection=allow_infl)
            if not found:
                return
            m = {**m, "start": found[0], "end": found[1], "text": source[found[0]:found[1]]}
        marks.append(m)

    shallow = artifacts.get("shallow_analysis") or {}
    for i, ph in enumerate(shallow.get("phrases") or []):
        if not isinstance(ph, dict) or not ph.get("text"):
            continue
        label = ph.get("class_label") or ph.get("class") or "фраза"
        _add_mark({
            "text": ph["text"],
            "kind": "shallow",
            "id": f"shallow-{i}",
            "label": str(label),
            "start": ph.get("start_char", ph.get("start")),
            "end": ph.get("end_char", ph.get("end")),
        })
    extremism = artifacts.get("extremism") or {}
    for i, ph in enumerate(extremism.get("dangerous_phrases") or []):
        if isinstance(ph, str) and ph.strip():
            _add_mark({"text": ph, "kind": "danger", "id": f"danger-{i}", "label": "опасная фраза"})
        elif isinstance(ph, dict) and ph.get("text"):
            _add_mark({
                "text": ph["text"],
                "kind": "danger",
                "id": f"danger-{i}",
                "label": "опасная фраза",
                "start": ph.get("start_char", ph.get("start")),
                "end": ph.get("end_char", ph.get("end")),
            })
    for i, bl in enumerate(artifacts.get("blocklist_phrases") or []):
        if isinstance(bl, dict) and bl.get("text"):
            _add_mark({
                "text": bl["text"],
                "kind": "blocklist",
                "id": f"blocklist-{i}",
                "label": "запретный лексикон",
                "start": bl.get("start"),
                "end": bl.get("end"),
                "href": bl.get("url") or bl.get("source"),
            })
        elif isinstance(bl, str) and bl.strip():
            _add_mark({"text": bl, "kind": "blocklist", "id": f"blocklist-{i}", "label": "запретный лексикон"})
    for i, hit in enumerate(artifacts.get("registry_hits") or []):
        if not isinstance(hit, dict):
            continue
        # В тексте ищем форму из документа (surface), не канон из CSV
        surface = hit.get("surface") or hit.get("query") or hit.get("match") or hit.get("text") or ""
        if not surface:
            continue
        title = hit.get("source_title") or hit.get("source") or "реестр"
        row = hit.get("row")
        match = hit.get("match") or ""
        label_parts = [str(title)]
        if row is not None:
            label_parts.append(f"строка {row}")
        if match:
            label_parts.append(f"запись: {match}")
        label = ", ".join(label_parts)
        _add_mark({
            "text": str(surface),
            "kind": "registry",
            "id": f"registry-{i}",
            "label": label,
            "href": hit.get("url") or hit.get("link"),
            "start": hit.get("start"),
            "end": hit.get("end"),
            "source_title": title,
            "row": row,
            "match": match,
            "file": hit.get("file"),
        })
    entities = artifacts.get("entities") or {}
    for key in ("persons", "organizations", "titles", "urls"):
        for i, ent in enumerate(entities.get(key) or []):
            if isinstance(ent, str) and ent.strip():
                _add_mark({"text": ent, "kind": "entity", "id": f"ent-{key}-{i}", "label": key})
            elif isinstance(ent, dict) and ent.get("text"):
                _add_mark({
                    "text": ent["text"],
                    "kind": "entity",
                    "id": f"ent-{key}-{i}",
                    "label": key,
                    "start": ent.get("start_char", ent.get("start")),
                    "end": ent.get("end_char", ent.get("end")),
                })

    for src, prefix in (
        ("rubert_entities", "rubert"),
        ("natasha_entities", "natasha"),
    ):
        for i, ent in enumerate(artifacts.get(src) or []):
            if not isinstance(ent, dict) or not ent.get("text"):
                continue
            label = str(ent.get("label") or "entity")
            _add_mark({
                "text": ent["text"],
                "kind": "entity",
                "id": f"{prefix}-{i}",
                "label": f"{prefix}:{label}",
                "start": ent.get("start"),
                "end": ent.get("end"),
            })
    return marks


def _apply_marks(text: str, marks: List[Dict[str, Any]]) -> str:
    """Вставить <mark> по offset или по первому вхождению текста."""
    ranges: List[Tuple[int, int, Dict[str, Any]]] = []
    used: set[Tuple[int, int]] = set()
    for m in marks:
        start, end = m.get("start"), m.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text):
            key = (start, end)
            if key not in used:
                used.add(key)
                ranges.append((start, end, m))
            continue
        needle = m.get("text") or ""
        if not needle:
            continue
        pos = text.find(needle)
        if pos < 0:
            continue
        key = (pos, pos + len(needle))
        if key in used:
            continue
        used.add(key)
        ranges.append((pos, pos + len(needle), m))

    ranges.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    merged: List[Tuple[int, int, Dict[str, Any]]] = []
    last_end = -1
    for s, e, m in ranges:
        if s < last_end:
            continue
        merged.append((s, e, m))
        last_end = e

    parts: List[str] = []
    cursor = 0
    for s, e, m in merged:
        parts.append(html.escape(text[cursor:s]))
        cls = m.get("kind", "danger")
        mid = m.get("id", "")
        label = html.escape(str(m.get("label") or cls))
        inner = html.escape(text[s:e])
        href = m.get("href")
        if href:
            link = html.escape(str(href))
            if cls == "registry" and label:
                parts.append(
                    f'<mark id="{mid}" class="{cls}" title="{label}">'
                    f'<a href="{link}" target="_blank" rel="noopener">{inner}</a>'
                    f'<sup class="reg-meta"> [{label}]</sup></mark>'
                )
            else:
                parts.append(
                    f'<mark id="{mid}" class="{cls}" title="{label}">'
                    f'<a href="{link}" target="_blank" rel="noopener">{inner}</a></mark>'
                )
        else:
            # для реестра — видимая подпись с названием и строкой
            if cls == "registry" and label:
                parts.append(
                    f'<mark id="{mid}" class="{cls}" title="{label}">{inner}'
                    f'<sup class="reg-meta"> [{label}]</sup></mark>'
                )
            else:
                parts.append(f'<mark id="{mid}" class="{cls}" title="{label}">{inner}</mark>')
        cursor = e
    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def build_html_report(text: str, artifacts: Dict[str, Any]) -> str:
    arts = dict(artifacts or {})
    if text and not arts.get("raw_text"):
        arts["raw_text"] = text
    # Финальный анти-галлюцинационный срез опасных фраз в сайдбаре
    from platform_plugins.processors.text_grounding import ground_phrase_list, text_contains
    source = arts.get("raw_text") or text or ""
    ext = dict(arts.get("extremism") or {})
    if source and isinstance(ext.get("dangerous_phrases"), list):
        kept, _ = ground_phrase_list(ext["dangerous_phrases"], source, min_len=3)
        ext["dangerous_phrases"] = kept
        ext["found_dangerous"] = bool(kept)
        arts["extremism"] = ext
    if source and isinstance(arts.get("registry_hits"), list):
        arts["registry_hits"] = [
            h for h in arts["registry_hits"]
            if isinstance(h, dict) and text_contains(
                source,
                str(h.get("surface") or h.get("query") or h.get("match") or h.get("text") or ""),
                allow_inflection=(h.get("kind") in ("person", "organization", "fio")),
            )
        ]
    shallow = dict(arts.get("shallow_analysis") or {})
    if source and isinstance(shallow.get("phrases"), list):
        kept, _ = ground_phrase_list(shallow["phrases"], source, min_len=3)
        shallow["phrases"] = kept
        arts["shallow_analysis"] = shallow

    from platform_plugins.processors.text_grounding import ground_entities_typed
    if source and isinstance(arts.get("entities"), dict):
        grounded_ent, _ = ground_entities_typed(arts["entities"], source)
        arts["entities"] = grounded_ent

    marks = _collect_marks(arts)
    highlighted = _apply_marks(text or source or "", marks)
    erroneous = arts.get("ошибочное", False)
    badge = (
        '<span class="badge err">ошибочное</span>'
        if erroneous
        else '<span class="badge ok">проверено</span>'
    )

    def _list_items(items: List[Dict[str, Any]], kind: str) -> str:
        rows = [m for m in marks if m.get("kind") == kind]
        if not rows:
            return "<li>нет</li>"
        out = []
        for m in rows[:80]:
            t = html.escape(str(m.get("text") or ""))
            mid = m.get("id") or ""
            href = m.get("href")
            extra = f' · <a href="{html.escape(str(href))}" target="_blank" rel="noopener">источник</a>' if href else ""
            meta = ""
            if kind == "registry":
                st = html.escape(str(m.get("source_title") or ""))
                row = m.get("row")
                match = html.escape(str(m.get("match") or ""))
                bits = []
                if st:
                    bits.append(st)
                if row is not None:
                    bits.append(f"строка {html.escape(str(row))}")
                if match:
                    bits.append(match)
                if bits:
                    meta = f' <span class="reg-meta">({", ".join(bits)})</span>'
            out.append(f'<li><a href="#{mid}">{t}</a>{meta}{extra}</li>')
        return "".join(out)

    entities = arts.get("entities") or {}
    ent_html = ""
    for key, label in (("persons", "Персоны"), ("organizations", "Организации"), ("titles", "Названия"), ("urls", "URL")):
        items = entities.get(key) or []
        if not items:
            continue
        lis = []
        for i, ent in enumerate(items[:40]):
            t = ent.get("text") if isinstance(ent, dict) else str(ent)
            mid = f"ent-{key}-{i}"
            lis.append(f'<li><a href="#{mid}">{html.escape(str(t or ""))}</a></li>')
        ent_html += f"<h3>{label}</h3><ul>{''.join(lis) or '<li>нет</li>'}</ul>"

    natasha = arts.get("natasha_entities_typed") or {}
    if isinstance(natasha, dict):
        for key, label in (("persons", "Natasha — ФИО"), ("organizations", "Natasha — организации"), ("urls", "Natasha — URL")):
            items = natasha.get(key) or []
            if not items:
                continue
            lis = []
            for i, ent in enumerate(items[:40]):
                if not isinstance(ent, dict):
                    continue
                surface = html.escape(str(ent.get("text") or ""))
                normal = str(ent.get("normal") or "")
                extra = f" → <em>{html.escape(normal)}</em>" if normal and normal != ent.get("text") else ""
                mid = f"natasha-{key}-{i}"
                lis.append(f'<li id="{mid}">{surface}{extra}</li>')
            ent_html += f"<h3>{label}</h3><ul>{''.join(lis)}</ul>"

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/>
<title>Контент Дозор — отчёт</title>
<style>
body{{font-family:Georgia,'Times New Roman',serif;background:#0f1419;color:#e6edf3;padding:24px;line-height:1.6}}
h1,h2,h3{{font-family:system-ui,sans-serif}}
mark.danger{{background:#5c1a1a;color:#ffb4b4;padding:0 2px;border-radius:3px}}
mark.shallow{{background:#3d2a55;color:#e0c4ff;padding:0 2px;border-radius:3px}}
mark.blocklist{{background:#4a2c0a;color:#ffd08a;padding:0 2px;border-radius:3px}}
mark.registry{{background:#7a1010;color:#ffe0e0;padding:0 3px;border-radius:3px;border-bottom:2px solid #ff4d4d;font-weight:600}}
mark.entity{{background:#1f3d2a;color:#8affb4;padding:0 2px;border-radius:3px}}
mark a{{color:inherit;text-decoration:underline}}
.reg-meta{{color:#ff8a8a;font-size:0.92em}}
.badge{{padding:4px 10px;border-radius:6px;font-size:12px;font-family:system-ui,sans-serif}}
.badge.err{{background:#3d1f1f;color:#ff8a8a}}
.badge.ok{{background:#1f3d2a;color:#8affb4}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin:12px 0}}
.legend span{{display:inline-block;margin-right:12px;font-size:13px;font-family:system-ui,sans-serif}}
pre.text{{white-space:pre-wrap;font-family:Georgia,serif;font-size:15px;line-height:1.7}}
a{{color:#79c0ff}}
ul{{padding-left:1.2em}}
</style></head><body>
<h1>Контент Дозор — отчёт</h1>{badge}
<div class="legend card">
  <span><mark class="danger">опасное</mark></span>
  <span><mark class="shallow">поверхностный</mark></span>
  <span><mark class="blocklist">лексикон</mark></span>
  <span><mark class="registry">реестр (красный)</mark></span>
  <span><mark class="entity">сущность</mark></span>
</div>
<div class="card"><h2>Текст с разметкой</h2><pre class="text">{highlighted}</pre></div>
<div class="card"><h2>Поверхностный анализ (4 класса)</h2><ul>{_list_items(marks, "shallow")}</ul></div>
<div class="card"><h2>Опасные фразы</h2><ul>{_list_items(marks, "danger")}</ul></div>
<div class="card"><h2>Запретный лексикон</h2><ul>{_list_items(marks, "blocklist")}</ul></div>
<div class="card"><h2>Совпадения реестра</h2><ul>{_list_items(marks, "registry")}</ul></div>
<div class="card"><h2>Сущности</h2>{ent_html or "<p>нет</p>"}</div>
</body></html>"""


@register_plugin_class
class HtmlExporterPlugin(Plugin):
    meta = PluginMeta(id="exporter_html", name="HTML Exporter", kind=PluginKind.EXPORTER)

    async def process(self, ctx: PipelineContext, data: Any) -> str:
        html_out = build_html_report(ctx.text, ctx.artifacts)
        ctx.artifacts["html_preview"] = html_out
        return html_out
