"""Byte decoding and optional URL fetching (``urllib``, no third-party client)."""

from __future__ import annotations

import codecs
import re
import urllib.error
import urllib.request

USER_AGENT = "web2md/0.1 (+https://github.com/hammasbuilds/web-to-markdown)"
MAX_BYTES = 20 * 1024 * 1024

_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w.:-]+)""", re.I)


class FetchError(RuntimeError):
    """Raised when a URL cannot be fetched or is not HTML."""


def _known(encoding: str | None) -> str | None:
    if not encoding:
        return None
    try:
        return codecs.lookup(encoding.strip().strip("\"'")).name
    except LookupError:
        return None


def decode_html(data: bytes, declared: str | None = None) -> str:
    """Decode HTML bytes: BOM, then the declared charset, then ``<meta charset>``,
    then strict UTF-8, then Windows-1252 (which accepts any byte sequence)."""
    for bom, enc in (
        (codecs.BOM_UTF8, "utf-8"),
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
    ):
        if data.startswith(bom):
            return data[len(bom) :].decode(enc, errors="replace")
    candidates = [_known(declared)]
    match = _META_CHARSET.search(data[:8192])
    if match:
        candidates.append(_known(match.group(1).decode("ascii", "ignore")))
    candidates.append("utf-8")
    for enc in candidates:
        if enc is None:
            continue
        if enc in ("latin-1", "iso8859-1", "ascii"):
            enc = "cp1252"  # what browsers actually do with these labels
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("cp1252", errors="replace")


def fetch(url: str, timeout: float = 20.0) -> tuple[str, str]:
    """Fetch ``url`` and return ``(html, final_url)``."""
    if not re.match(r"^https?://", url, re.I):
        raise FetchError(f"not an http(s) URL: {url!r}")
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            ctype = response.headers.get("Content-Type", "")
            if ctype and "html" not in ctype.lower() and "xml" not in ctype.lower():
                raise FetchError(f"{url} returned {ctype!r}, not HTML")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise FetchError(f"{url} is larger than {MAX_BYTES // (1024 * 1024)} MB")
            charset = response.headers.get_content_charset()
            return decode_html(data, charset), response.geturl()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"{url} returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"could not fetch {url}: {reason}") from exc
