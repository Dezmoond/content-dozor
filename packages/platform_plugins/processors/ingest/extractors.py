# -*- coding: utf-8 -*-
"""Извлечение плоского текста из выбранного источника."""
from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from platform_core.ingest_sources import USER_AGENT, get_source
from platform_plugins.processors.docx_extract.plugin import read_docx_text

_SCRIPT_TAGS = ("script", "style", "noscript", "svg", "template")
_WS_RE = re.compile(r"[ \t\u00a0]+")
_NL_RE = re.compile(r"\n{3,}")


def read_bytes_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def collapse_text(text: str) -> str:
    lines = [_WS_RE.sub(" ", line).strip() for line in (text or "").splitlines()]
    joined = "\n".join(line for line in lines if line)
    return _NL_RE.sub("\n\n", joined).strip()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(_SCRIPT_TAGS):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "tr"]):
        p.append("\n")
    return collapse_text(unescape(soup.get_text("\n")))


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "html.parser")


def _el_text(el) -> str:
    if el is None:
        return ""
    for br in el.find_all("br"):
        br.replace_with("\n")
    return collapse_text(unescape(el.get_text("\n")))


async def fetch_url(url: str, timeout: float = 25.0) -> Tuple[str, Dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            try:
                body = resp.text
            except Exception:
                body = resp.content.decode(resp.encoding or "utf-8", errors="replace")
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"Страница недоступна (HTTP {exc.response.status_code}): {url}") from exc
    except httpx.RequestError as exc:
        raise ValueError(
            "Не удалось загрузить страницу (нет сети или ресурс недоступен). "
            "Приложите сохранённый HTML-файл."
        ) from exc
    meta = {
        "final_url": str(resp.url),
        "status_code": resp.status_code,
        "content_type": resp.headers.get("content-type", ""),
    }
    return body, meta


def normalize_telegram_preview_url(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower().replace("www.", "")
    if host not in ("t.me", "telegram.me", "telegram.dog"):
        return raw
    path = parsed.path.strip("/")
    if not path:
        return raw
    if path.startswith("s/"):
        return f"https://t.me/{path}"
    first = path.split("/", 1)[0]
    if first in ("c", "joinchat", "addstickers", "share", "proxy") or first.startswith("+"):
        return raw
    return f"https://t.me/s/{path}"


def parse_telegram_html(html: str, *, include_comments: bool = True) -> Tuple[str, Dict[str, Any]]:
    soup = _soup(html)
    posts: List[str] = []
    comments: List[str] = []

    widgets = soup.select(".tgme_widget_message")
    for node in widgets:
        author = _el_text(node.select_one(".tgme_widget_message_author, .tgme_widget_message_owner_name"))
        body = _el_text(node.select_one(".tgme_widget_message_text, .tgme_widget_message_caption"))
        date = ""
        time_el = node.select_one("time")
        if time_el is not None:
            date = time_el.get("datetime") or _el_text(time_el)
        if not body:
            continue
        head = " / ".join(part for part in (author, date) if part)
        posts.append(f"[пост] {head}\n{body}" if head else f"[пост]\n{body}")

    # HTML-экспорт Telegram Desktop
    export_msgs = soup.select("div.message")
    if export_msgs and not widgets:
        for node in export_msgs:
            if "service" in (node.get("class") or []):
                continue
            author = _el_text(node.select_one(".from_name"))
            body = _el_text(node.select_one(".text, .media_wrap + .text"))
            reply = _el_text(node.select_one(".reply_to, .forwarded"))
            if not body:
                continue
            is_reply = bool(node.select_one(".reply_to")) or "reply" in " ".join(node.get("class") or [])
            prefix = "[комментарий]" if is_reply and include_comments else "[пост]"
            bits = [prefix]
            if author:
                bits.append(author)
            block = " ".join(bits) + "\n" + body
            if reply and include_comments:
                block = f"{block}\n(ответ на: {reply})"
            if is_reply and include_comments:
                comments.append(block)
            elif not is_reply:
                posts.append(block)
            elif include_comments:
                comments.append(block)

    if include_comments:
        for node in soup.select(".tgme_widget_message_reply, .discussion, .comment"):
            t = _el_text(node)
            if t:
                comments.append(f"[комментарий]\n{t}")

    parts = list(posts)
    if include_comments:
        parts.extend(comments)
    text = "\n\n".join(parts).strip()
    if not text:
        text = html_to_text(html)
    meta = {
        "posts_count": len(posts),
        "comments_count": len(comments) if include_comments else 0,
        "parser": "telegram_html",
    }
    if widgets or export_msgs:
        meta["format"] = "tgme_preview" if widgets else "telegram_desktop_export"
    return text, meta


def parse_vk_html(html: str, *, include_comments: bool = True) -> Tuple[str, Dict[str, Any]]:
    soup = _soup(html)
    posts: List[str] = []
    comments: List[str] = []

    post_nodes = soup.select(
        ".wall_text, .wall_post_text, .pi_text, .post_content, article, .PostContent"
    )
    seen = set()
    for node in post_nodes:
        body = _el_text(node)
        if not body or body in seen or len(body) < 2:
            continue
        seen.add(body)
        posts.append(f"[пост]\n{body}")

    if include_comments:
        for node in soup.select(
            ".reply_text, .wall_reply_text, .replies_list .pi_text, .comment, .Comment"
        ):
            body = _el_text(node)
            if not body or body in seen:
                continue
            seen.add(body)
            comments.append(f"[комментарий]\n{body}")

    parts = list(posts)
    if include_comments:
        parts.extend(comments)
    text = "\n\n".join(parts).strip()
    warnings: List[str] = []
    page_text = html_to_text(html)
    if not text:
        text = page_text
        if any(x in page_text.lower() for x in ("войдите", "log in", "sign in")):
            warnings.append("Страница VK может требовать авторизацию — сохраните HTML вручную.")
    if "login" in (soup.title.get_text() if soup.title else "").lower():
        warnings.append("Похоже на страницу входа VK.")

    meta = {
        "posts_count": len(posts),
        "comments_count": len(comments) if include_comments else 0,
        "parser": "vk_html",
        "warnings": warnings,
    }
    return text, meta


def extract_pdf(path: str) -> Tuple[str, Dict[str, Any]]:
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages: List[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            chunk = page.extract_text() or ""
        except Exception:
            chunk = ""
        chunk = collapse_text(chunk)
        if chunk:
            pages.append(chunk)
    text = "\n\n".join(pages).strip()
    meta: Dict[str, Any] = {"pages": len(reader.pages), "pages_with_text": len(pages)}
    if not text:
        meta["warnings"] = ["В PDF нет текстового слоя (возможно скан). OCR будет добавлен позже."]
    return text, meta


def load_source_descriptor(path: Path) -> Optional[Dict[str, Any]]:
    if path.suffix.lower() != ".json":
        return None
    try:
        data = json.loads(read_bytes_text(path))
    except Exception:
        return None
    if isinstance(data, dict) and (data.get("url") or data.get("source_type")):
        return data
    return None


async def extract_from_source(
    *,
    source_type: str,
    source_path: Optional[str] = None,
    source_url: Optional[str] = None,
    source_text: Optional[str] = None,
    include_comments: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    spec = get_source(source_type)
    meta: Dict[str, Any] = {
        "source_type": spec["id"],
        "source_label": spec["label"],
        "include_comments": bool(include_comments),
        "internet_used": False,
        "warnings": [],
    }
    path = Path(source_path) if source_path else None
    url = (source_url or "").strip()
    pasted = (source_text or "").strip()

    if path and path.is_file():
        desc = load_source_descriptor(path)
        if desc:
            url = url or str(desc.get("url") or "").strip()
            include_comments = bool(desc.get("include_comments", include_comments))
            meta["include_comments"] = include_comments
            path = None

    if spec["id"] == "paste":
        text = pasted
        if not text and path and path.is_file():
            text = read_bytes_text(path)
        meta["chars"] = len(text or "")
        return (text or "").strip(), meta

    if spec["id"] == "docx":
        if not path or not path.is_file():
            raise FileNotFoundError("DOCX-файл не найден")
        text = read_docx_text(str(path))
        meta["chars"] = len(text)
        return text, meta

    if spec["id"] == "pdf":
        if not path or not path.is_file():
            raise FileNotFoundError("PDF-файл не найден")
        text, extra = extract_pdf(str(path))
        meta.update(extra)
        if extra.get("warnings"):
            meta["warnings"] = list(extra["warnings"])
        meta["chars"] = len(text)
        return text, meta

    html = ""
    if path and path.is_file():
        html = read_bytes_text(path)
        meta["from_file"] = path.name
    elif url:
        fetch_url_value = url
        if spec["id"] == "telegram":
            fetch_url_value = normalize_telegram_preview_url(url)
            if fetch_url_value != url:
                meta["preview_url"] = fetch_url_value
        html, fetch_meta = await fetch_url(fetch_url_value)
        meta["internet_used"] = True
        meta.update(fetch_meta)
        meta["url"] = url
    else:
        raise ValueError(f"Для «{spec['label']}» нужна ссылка или HTML-файл")

    if spec["id"] == "telegram":
        text, extra = parse_telegram_html(html, include_comments=include_comments)
        meta.update({k: v for k, v in extra.items() if k != "warnings"})
        meta["warnings"] = list(meta.get("warnings") or []) + list(extra.get("warnings") or [])
        if extra.get("posts_count", 0) == 0 and extra.get("comments_count", 0) == 0:
            meta["warnings"].append(
                "Не удалось разобрать посты Telegram — взят общий текст страницы. "
                "Для комментариев лучше HTML-экспорт чата."
            )
        meta["chars"] = len(text)
        return text, meta

    if spec["id"] == "vk":
        text, extra = parse_vk_html(html, include_comments=include_comments)
        meta.update({k: v for k, v in extra.items() if k != "warnings"})
        meta["warnings"] = list(meta.get("warnings") or []) + list(extra.get("warnings") or [])
        meta["chars"] = len(text)
        return text, meta

    # url / html
    ctype = str(meta.get("content_type") or "")
    if path and path.suffix.lower() in (".txt", ".md") and not html.strip().startswith("<"):
        text = html
    elif "json" in ctype and html.lstrip().startswith("{"):
        text = html
    else:
        text = html_to_text(html) if "<" in html[:500].lower() else collapse_text(html)
    meta["chars"] = len(text)
    if url:
        meta["url"] = url
    return text, meta
