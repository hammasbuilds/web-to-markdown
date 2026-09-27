"""Benchmark loaders. Data lives under ``data/`` (git-ignored); ``bench/fetch_data.sh``
downloads it.

* ``aeb`` - scrapinghub/article-extraction-benchmark: 181 news/blog pages with
  hand-checked article text.
* ``wceb/<name>`` - the eight datasets that Bevendorff et al. (2023) combined
  into one format for "An Empirical Comparison of Web Content Extraction
  Algorithms" (CETD, CleanEval, CleanPortalEval, Dragnet, Google-Trends-2017,
  L3S-GN1, Readability, Scrapinghub). Their Scrapinghub copy is the same 181
  pages as ``aeb`` and is skipped; pages with an empty ground truth are skipped.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from web2md.fetch import decode_html

DATA = Path(os.environ.get("WEB2MD_DATA", Path(__file__).resolve().parent.parent / "data"))

# Second-level labels under which the registrable domain has three parts.
_SLD = {"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or"}


@dataclass(frozen=True)
class Page:
    dataset: str
    page_id: str
    url: str
    html: str
    truth: str

    @property
    def site(self) -> str:
        return site_of(self.url) or f"{self.dataset}:{self.page_id}"

    @property
    def split(self) -> str:
        return split_of(self.site)


def site_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 3 and parts[-2] in _SLD and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def split_of(site: str) -> str:
    """Deterministic dev/held-out assignment by site, so no site is in both."""
    digest = hashlib.sha1(site.encode("utf-8")).digest()
    return "dev" if digest[0] % 2 == 0 else "heldout"


def load_aeb(root: Path | None = None) -> list[Page]:
    base = (root or DATA) / "aeb"
    truth_path = base / "ground-truth.json"
    if not truth_path.exists():
        raise FileNotFoundError(f"{truth_path} missing; run bench/fetch_data.sh")
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    pages = []
    for page_id, item in truth.items():
        raw = gzip.decompress((base / "html" / f"{page_id}.html.gz").read_bytes())
        pages.append(
            Page("aeb", page_id, item.get("url", ""), decode_html(raw), item["articleBody"])
        )
    return pages


WCEB_SKIP = {"scrapinghub"}  # same pages as aeb


def _wceb_url(html: str) -> str:
    for pattern in (
        r"<link[^>]+rel=[\"']?canonical[\"']?[^>]+href=[\"']([^\"']+)",
        r"<meta[^>]+property=[\"']og:url[\"'][^>]+content=[\"']([^\"']+)",
    ):
        match = re.search(pattern, html[:50000], re.I)
        if match and match.group(1).startswith("http"):
            return match.group(1)
    return ""


PACKED = "pages.jsonl.gz"


def pack_wceb(root: Path | None = None) -> Path:
    """Write every usable WCEB page into one gzip file.

    Reading 3,800 loose HTML files is slow on a busy disk (and every one is an
    antivirus scan on Windows); one sequential 60 MB read is not.
    """
    target = (root or DATA) / "wceb" / PACKED
    tmp = target.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        for page in _iter_wceb_files(root):
            fh.write(json.dumps(page.__dict__, ensure_ascii=False))
            fh.write("\n")
    tmp.replace(target)
    return target


def iter_wceb(root: Path | None = None) -> Iterator[Page]:
    packed = (root or DATA) / "wceb" / PACKED
    if packed.exists():
        with gzip.open(packed, "rt", encoding="utf-8") as fh:
            for line in fh:
                yield Page(**json.loads(line))
        return
    yield from _iter_wceb_files(root)


def _iter_wceb_files(root: Path | None = None) -> Iterator[Page]:
    base = (root or DATA) / "wceb" / "combined"
    if not (base / "ground-truth").exists():
        raise FileNotFoundError(f"{base} missing; run bench/fetch_data.sh")
    for truth_file in sorted((base / "ground-truth").glob("*.jsonl")):
        name = truth_file.stem
        if name in WCEB_SKIP:
            continue
        with truth_file.open(encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        for row in rows:
            truth = row.get("plaintext", "")
            if not truth.strip():
                continue  # a page whose article is empty cannot be scored
            html = decode_html((base / "html" / name / f"{row['page_id']}.html").read_bytes())
            url = row.get("url") or _wceb_url(html)
            yield Page(f"wceb/{name}", row["page_id"], url, html, truth)


def load_wceb(root: Path | None = None) -> list[Page]:
    return list(iter_wceb(root))


if __name__ == "__main__":
    print(pack_wceb())
