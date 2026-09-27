"""Does the markdown keep the article's structure? A dimension shingle F1 ignores.

Ground truth in both benchmarks is plain text, so structure labels are derived:
a list, table, code block or heading in the *source HTML* counts as a gold
structure of the article when its text is present in the ground-truth article
(each list item / table cell / heading found as a contiguous token run, a code
block's 4-shingles at least 80% covered). A structure *survives* in an
extractor's output when the same text appears inside the matching markdown
construct: list-item lines, table rows, fenced or indented code, heading lines.

Scoring is per structure, not per page, so a page with ten tables weighs ten
times one with a single table. Counts are small; the report prints n.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bench.metrics import shingles, tokenize
from web2md.dom import Element, parse
from web2md.markdown import _raw_text

KINDS = ("list", "table", "code", "heading")
MATCH = 0.8


@dataclass
class Gold:
    kind: str
    units: list[list[str]]  # token runs that must survive (items, cells, heading)
    code_text: str = ""
    code_lines: int = 0


@dataclass
class Regions:
    list_lines: list[list[str]] = field(default_factory=list)
    table_lines: list[list[str]] = field(default_factory=list)
    code_blocks: list[str] = field(default_factory=list)
    heading_lines: list[list[str]] = field(default_factory=list)


def _contains(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    if n == 0:
        return False
    first = needle[0]
    return any(
        haystack[i] == first and haystack[i : i + n] == needle for i in range(len(haystack) - n + 1)
    )


def _in_truth(needle: list[str], truth_tokens: list[str], truth_text: str) -> bool:
    return _contains(truth_tokens, needle) if len(needle) < 12 else (" ".join(needle) in truth_text)


def _coverage(needle_text: str, hay_text: str) -> float:
    need = shingles(needle_text)
    if not need:
        return 0.0
    have = shingles(hay_text)
    hit = sum(min(c, have.get(k, 0)) for k, c in need.items())
    return hit / sum(need.values())


def gold_structures(html: str, truth: str) -> list[Gold]:
    root = parse(html)
    for el in list(root.iter("script", "style", "noscript", "template")):
        el.remove()
    truth_tokens = tokenize(truth)
    truth_joined = " ".join(truth_tokens)
    found: list[Gold] = []

    def in_truth(tokens: list[str]) -> bool:
        return _in_truth(tokens, truth_tokens, truth_joined)

    for el in root.iter("ul", "ol", "table", "pre", "h2", "h3", "h4", "h5", "h6"):
        if any(a.tag in ("pre", "table") for a in el.ancestors()) and el.tag != "table":
            continue
        if el.tag in ("ul", "ol"):
            items = [tokenize(_own_item_text(li)) for li in el.elements if li.tag == "li"]
            items = [t for t in items if len(t) >= 2]
            if len(items) >= 2 and sum(in_truth(t) for t in items) >= MATCH * len(items):
                found.append(Gold("list", items))
        elif el.tag == "table":
            if any(t is not el for t in el.iter("table")):
                continue  # layout table wrapping other tables
            rows = [tr for tr in el.iter("tr")]
            cells = [
                tokenize(c.text()) for tr in rows for c in tr.elements if c.tag in ("td", "th")
            ]
            widths = [len([c for c in tr.elements if c.tag in ("td", "th")]) for tr in rows]
            cells = [c for c in cells if c]
            if (
                len(rows) >= 2
                and max(widths, default=0) >= 2
                and len(cells) >= 4
                and sum(in_truth(c) for c in cells) >= MATCH * len(cells)
            ):
                found.append(Gold("table", cells))
        elif el.tag == "pre":
            code = _raw_text(el).strip("\n")
            if len(tokenize(code)) >= 4 and _coverage(code, truth) >= MATCH:
                lines = [ln for ln in code.split("\n") if ln.strip()]
                found.append(Gold("code", [], code, len(lines)))
        else:
            tokens = tokenize(el.text())
            if len(tokens) >= 2 and in_truth(tokens):
                found.append(Gold("heading", [tokens]))
    return found


def _own_item_text(li: Element) -> str:
    """An item's text without its nested lists (those are scored as lists themselves)."""
    parts: list[str] = []
    for child in li.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in ("ul", "ol"):
            parts.append(child.text())
    return " ".join(parts)


_LIST_LINE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.*)$")
_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_TABLE_RULE = re.compile(r"[|:\-\s]+")
_SETEXT = re.compile(r"=+|-+")


def regions(markdown: str) -> Regions:
    """Split markdown into the text found inside each kind of construct.

    Recognises fenced code and indented code (html2text's style), bullet and
    numbered list lines, ATX and setext headings, and pipe-table rows with or
    without the outer pipes (html2text omits them).
    """
    out = Regions()
    lines = markdown.split("\n")
    fence: str | None = None
    block: list[str] | None = None  # the code block being collected
    in_list = False
    prev_blank = True
    for i, line in enumerate(lines):
        m = _FENCE.match(line)
        if fence is not None and block is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                out.code_blocks.append("\n".join(block))
                fence, block = None, None
            else:
                block.append(line)
            continue
        if m:
            fence, block = m.group(1), []
            continue
        indented = line.startswith(("    ", "\t"))
        if block is not None:  # inside an indented code block
            if indented or not line.strip():
                block.append(line)
                continue
            out.code_blocks.append("\n".join(block).strip("\n"))
            block = None
        stripped = line.strip()
        if indented and stripped and prev_blank and not in_list:
            block = [line]
            prev_blank = False
            continue
        prev_blank = not stripped
        if not stripped:
            continue
        if (lm := _LIST_LINE.match(line)) is not None:
            in_list = True
            out.list_lines.append(tokenize(lm.group(1)))
            continue
        if not indented:
            in_list = False
        if (hm := _HEADING_LINE.match(line)) is not None:
            out.heading_lines.append(tokenize(hm.group(1)))
        elif "|" in stripped and not _TABLE_RULE.fullmatch(stripped):
            out.table_lines.append(tokenize(stripped))
        elif _SETEXT.fullmatch(stripped) and i > 0 and lines[i - 1].strip():
            out.heading_lines.append(tokenize(lines[i - 1]))
    if block is not None:
        out.code_blocks.append("\n".join(block).strip("\n"))
    return out


def survives(gold: Gold, reg: Regions) -> bool:
    if gold.kind == "code":
        # Every token present is not enough: a code block collapsed onto one line,
        # or spread over paragraphs, is broken. Its lines must survive in one block.
        return any(
            _coverage(gold.code_text, block) >= MATCH
            and len([ln for ln in block.split("\n") if ln.strip()]) >= MATCH * gold.code_lines
            for block in reg.code_blocks
        )
    pools = {"list": reg.list_lines, "table": reg.table_lines, "heading": reg.heading_lines}
    pool = pools[gold.kind]
    hits = sum(any(_contains(line, unit) for line in pool) for unit in gold.units)
    return hits >= MATCH * len(gold.units)


def text_present(gold: Gold, output_tokens: list[str], output_text: str) -> bool:
    """Whether the structure's *words* reached the output, marked up or not."""
    if gold.kind == "code":
        return _coverage(gold.code_text, output_text) >= MATCH
    hits = sum(_contains(output_tokens, unit) for unit in gold.units)
    return hits >= MATCH * len(gold.units)
