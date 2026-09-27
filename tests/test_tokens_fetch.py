import codecs
import io
import urllib.error

import pytest

from web2md import fetch as fetch_mod
from web2md.fetch import FetchError, decode_html, fetch
from web2md.tokens import estimate_tokens


def test_estimate_tokens_basics():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") == 2
    assert estimate_tokens("hello world, again") == 4
    # A long rare word costs more than one token; CJK is roughly one per character.
    assert estimate_tokens("internationalisation") == 2
    assert estimate_tokens("你好世界") == 4


def test_estimate_tokens_grows_with_text():
    text = "The quick brown fox jumps over the lazy dog. "
    assert estimate_tokens(text * 10) == pytest.approx(10 * estimate_tokens(text), rel=0.05)


def test_decode_respects_bom_and_meta_charset():
    assert decode_html(codecs.BOM_UTF8 + "café".encode()) == "café"
    sjis = '<meta charset="shift_jis"><p>日本</p>'.encode("shift_jis")
    assert "日本" in decode_html(sjis)
    latin = '<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">\x93q\x94'
    assert decode_html(latin.encode("latin-1")).endswith("“q”")  # cp1252 quotes


def test_decode_falls_back_when_utf8_is_invalid():
    assert decode_html(b"caf\xe9") == "café"
    assert decode_html(b"ok", declared="no-such-charset") == "ok"


def test_fetch_rejects_non_http():
    with pytest.raises(FetchError, match="not an http"):
        fetch("file:///etc/passwd")


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, ctype: str, url: str) -> None:
        super().__init__(body)
        self.headers = _Headers(ctype)
        self._url = url

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Headers:
    def __init__(self, ctype: str) -> None:
        self.ctype = ctype

    def get(self, name: str, default: str = "") -> str:
        return self.ctype if name == "Content-Type" else default

    def get_content_charset(self) -> str | None:
        return self.ctype.split("charset=")[1] if "charset=" in self.ctype else None


def test_fetch_decodes_with_the_header_charset(monkeypatch):
    body = "<p>été</p>".encode("latin-1")
    monkeypatch.setattr(
        fetch_mod.urllib.request,
        "urlopen",
        lambda req, timeout: _FakeResponse(body, "text/html; charset=latin-1", "https://e.org/f"),
    )
    html, final = fetch("https://e.org/")
    assert html == "<p>été</p>" and final == "https://e.org/f"


def test_fetch_refuses_non_html(monkeypatch):
    monkeypatch.setattr(
        fetch_mod.urllib.request,
        "urlopen",
        lambda req, timeout: _FakeResponse(b"%PDF", "application/pdf", "https://e.org/x.pdf"),
    )
    with pytest.raises(FetchError, match="not HTML"):
        fetch("https://e.org/x.pdf")


def test_fetch_wraps_http_errors(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(fetch_mod.urllib.request, "urlopen", boom)
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch("https://e.org/missing")


def test_fetch_wraps_connection_errors(monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("name resolution failed")

    monkeypatch.setattr(fetch_mod.urllib.request, "urlopen", boom)
    with pytest.raises(FetchError, match="name resolution failed"):
        fetch("https://nowhere.invalid/")
