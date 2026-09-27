"""Page metadata: title, author, date, canonical URL, and a few extras.

Sources are tried from most to least explicit: OpenGraph/article meta tags,
JSON-LD, ``itemprop`` microdata, then visible markup (``<title>``, ``<time>``,
``rel=author``). The first non-empty value wins.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin

from web2md.dom import Element

_TITLE_SEPARATORS = re.compile(r"\s+[|–—:\-·•]\s+")
_DATE_META = (
    "article:published_time",
    "og:published_time",
    "datepublished",
    "date",
    "pubdate",
    "publishdate",
    "publish-date",
    "dc.date",
    "dc.date.issued",
    "dcterms.date",
    "dcterms.created",
    "sailthru.date",
    "parsely-pub-date",
    "citation_publication_date",
)
_AUTHOR_META = (
    "author",
    "article:author",
    "og:article:author",
    "dc.creator",
    "sailthru.author",
    "parsely-author",
    "citation_author",
    "byl",
)
_BYLINE_CLASS = re.compile(r"\bbyline\b|\bauthor(?:-name)?\b", re.I)


@dataclass
class Metadata:
    title: str = ""
    author: str = ""
    date: str = ""
    canonical_url: str = ""
    description: str = ""
    site_name: str = ""
    language: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _meta_map(root: Element) -> dict[str, str]:
    found: dict[str, str] = {}
    for meta in root.iter("meta"):
        key = (meta.get("property") or meta.get("name") or meta.get("itemprop")).strip().lower()
        value = _clean(meta.get("content"))
        if key and value and key not in found:
            found[key] = value
    return found


def _json_ld(root: Element) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for script in root.iter("script"):
        if "ld+json" not in script.get("type").lower():
            continue
        raw = "".join(c for c in script.children if isinstance(c, str)).strip()
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        stack: list[Any] = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                objects.append(item)
                if "@graph" in item:
                    stack.append(item["@graph"])
    return objects


def _ld_author(value: Any) -> str:
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, dict):
        return _ld_author(value.get("name", ""))
    if isinstance(value, list):
        names = [_ld_author(v) for v in value]
        return ", ".join(n for n in names if n)
    return ""


def _ld_value(objects: list[dict[str, Any]], key: str) -> Any:
    articles = [
        o
        for o in objects
        if "Article" in str(o.get("@type", "")) or "Posting" in str(o.get("@type", ""))
    ]
    for obj in articles + objects:
        if obj.get(key):
            return obj[key]
    return ""


def _strip_site_suffix(title: str, site_name: str, heading: str = "") -> str:
    parts = _TITLE_SEPARATORS.split(title)
    if len(parts) < 2:
        return title
    if heading:
        for part in parts:
            if part.strip().lower() == heading.lower():
                return part.strip()
    if site_name:
        kept = [p for p in parts if p.strip().lower() != site_name.lower()]
        if kept and len(kept) < len(parts):
            return " - ".join(kept)
    longest = max(parts, key=len)
    # Only drop segments when one part clearly carries the headline.
    return longest if len(longest.split()) >= 4 else title


def extract_metadata(root: Element, base_url: str | None = None) -> Metadata:
    meta = _meta_map(root)
    ld = _json_ld(root)
    md = Metadata()
    md.site_name = meta.get("og:site_name", "")

    title_tag = root.find("title")
    title_text = _clean(title_tag.text()) if title_tag is not None else ""
    ld_headline = _ld_value(ld, "headline")
    h1 = root.find("h1")
    h1_text = _clean(h1.text()) if h1 is not None else ""
    md.title = (
        meta.get("og:title")
        or meta.get("twitter:title")
        or (_clean(ld_headline) if isinstance(ld_headline, str) else "")
        or _strip_site_suffix(title_text, md.site_name, h1_text)
        or h1_text
    )

    md.author = next((meta[k] for k in _AUTHOR_META if meta.get(k) and "://" not in meta[k]), "")
    if not md.author:
        md.author = _ld_author(_ld_value(ld, "author"))
    if not md.author:
        for el in root.iter():
            if el.get("rel") == "author" or el.get("itemprop") == "author":
                md.author = _clean(el.get("content") or el.text())
            elif el.tag in ("span", "div", "p", "a") and _BYLINE_CLASS.search(el.get("class")):
                text = _clean(el.text())
                md.author = re.sub(r"^(?:by|von|par|por)\s+", "", text, flags=re.I)
            if md.author:
                md.author = md.author[:120]
                break

    md.date = next((meta[k] for k in _DATE_META if meta.get(k)), "")
    if not md.date:
        ld_date = _ld_value(ld, "datePublished")
        md.date = _clean(ld_date) if isinstance(ld_date, str) else ""
    if not md.date:
        for el in root.iter():
            if el.get("itemprop") == "datePublished":
                md.date = el.get("content") or el.get("datetime") or _clean(el.text())
            elif el.tag == "time" and el.get("datetime"):
                md.date = el.get("datetime")
            if md.date:
                break

    canonical = ""
    for link in root.iter("link"):
        if "canonical" in link.get("rel").lower().split() and link.get("href").strip():
            canonical = link.get("href").strip()
            break
    canonical = canonical or meta.get("og:url", "")
    md.canonical_url = urljoin(base_url, canonical) if base_url and canonical else canonical

    md.description = meta.get("og:description") or meta.get("description", "")
    html = root.find("html")
    md.language = (html.get("lang") if html is not None else "") or meta.get("og:locale", "")
    return md
