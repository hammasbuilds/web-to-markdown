"""Render an :class:`~web2md.dom.Element` subtree as GitHub-flavoured markdown.

The renderer works in two modes. *Block* rendering returns a list of finished
markdown blocks (paragraphs, headings, lists, tables, fences); *inline*
rendering returns one whitespace-collapsed string. A container that mixes the
two buffers inline runs into a paragraph until it meets a block child, which is
how a ``<div>`` holding bare text and a ``<ul>`` comes out as a paragraph
followed by a list rather than one run-on line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from web2md.dom import Element

HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

BLOCK_TAGS = frozenset(
    [
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "center",
        "dd",
        "details",
        "dialog",
        "dir",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "frameset",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "html",
        "li",
        "main",
        "menu",
        "nav",
        "noframes",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
        "#document",
    ]
)

# Never rendered: invisible, interactive, or embedded content.
SKIP_TAGS = frozenset(
    [
        "script",
        "style",
        "noscript",
        "template",
        "head",
        "title",
        "meta",
        "link",
        "svg",
        "math",
        "button",
        "input",
        "select",
        "option",
        "textarea",
        "iframe",
        "object",
        "embed",
        "canvas",
        "audio",
        "video",
        "source",
        "track",
        "map",
        "area",
        "dialog",
    ]
)

_WS = re.compile(r"\s+")
_LINE_START_ESCAPE = re.compile(r"^(#{1,6}\s|>|[-+*]\s|\d+[.)]\s|=+\s*$|-{3,}\s*$|```|~~~)")
_LANG_PATTERNS = (
    re.compile(r"(?:^|\s)(?:language|lang)-([\w+#.-]+)"),
    re.compile(r"(?:^|\s)highlight-(?:source-)?([\w+#.-]+)"),
    re.compile(r"(?:^|\s)brush:\s*([\w+#.-]+)"),
    re.compile(r"(?:^|\s)sourceCode\s+([\w+#.-]+)"),
)
_NOT_LANGUAGES = frozenset({"default", "none", "plaintext", "text", "notranslate", "nohighlight"})


@dataclass(frozen=True)
class RenderOptions:
    base_url: str | None = None
    links: bool = True
    images: bool = True


def code_language(el: Element) -> str:
    """Best-effort language tag from the class names on a code block and its wrappers."""
    candidates = [el, *el.elements[:1], *list(el.ancestors())[:2]]
    for node in candidates:
        classes = node.get("class")
        lang_attr = node.get("data-lang") or node.get("data-language")
        if lang_attr and lang_attr.lower() not in _NOT_LANGUAGES:
            return lang_attr.strip().lower()
        for pattern in _LANG_PATTERNS:
            match = pattern.search(classes)
            if match and match.group(1).lower() not in _NOT_LANGUAGES:
                return match.group(1).lower()
    return ""


def _fence_for(code: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", code)), default=0)
    return "`" * max(3, longest + 1)


def _escape_line_start(line: str) -> str:
    return "\\" + line if _LINE_START_ESCAPE.match(line) else line


class Renderer:
    def __init__(self, options: RenderOptions | None = None) -> None:
        self.opts = options or RenderOptions()
        self._has_block: dict[int, bool] = {}
        self._cell_blocks: dict[int, list[str]] = {}

    # -- public --------------------------------------------------------------
    def render(self, root: Element) -> str:
        self._index_blocks(root)
        return "\n\n".join(self.blocks(root)).strip() + "\n"

    # -- structure -------------------------------------------------------------
    def _index_blocks(self, root: Element) -> None:
        """Record, for every element, whether it contains a block-level descendant."""
        order = list(root.iter())
        for el in reversed(order):  # children before parents
            self._has_block[id(el)] = any(
                c.tag in BLOCK_TAGS or self._has_block.get(id(c), False)
                for c in el.elements
                if c.tag not in SKIP_TAGS
            )

    def _is_block(self, el: Element) -> bool:
        return el.tag in BLOCK_TAGS or self._has_block.get(id(el), False)

    # -- block mode ------------------------------------------------------------
    def blocks(self, el: Element) -> list[str]:
        if el.tag in ("td", "th"):
            cached = self._cell_blocks.get(id(el))
            if cached is None:
                cached = self._cell_blocks[id(el)] = self._blocks(el)
            return cached
        return self._blocks(el)

    def _blocks(self, el: Element) -> list[str]:
        return self._render_nodes(el.children)

    def _render_nodes(self, nodes: list[Element | str]) -> list[str]:
        """Block-render a run of sibling nodes, buffering inline ones into paragraphs."""
        out: list[str] = []
        buf: list[str] = []

        def flush() -> None:
            para = self._finish_paragraph("".join(buf))
            buf.clear()
            if para:
                out.append(para)

        for child in nodes:
            if isinstance(child, str):
                buf.append(_WS.sub(" ", child))
            elif child.tag in SKIP_TAGS:
                continue
            elif self._is_block(child):
                flush()
                out.extend(self.block(child))
            else:
                buf.append(self.inline(child))
        flush()
        return out

    def block(self, el: Element) -> list[str]:
        tag = el.tag
        if tag in HEADINGS:
            text = self._one_line(self.inline_children(el))
            return [f"{'#' * HEADINGS[tag]} {text}"] if text else []
        if tag == "pre":
            return self._code_block(el)
        if tag in ("ul", "ol", "menu", "dir"):
            return self._list(el)
        if tag == "table":
            return self._table(el)
        if tag == "blockquote":
            inner = "\n\n".join(self.blocks(el))
            if not inner:
                return []
            return ["\n".join(f"> {ln}" if ln else ">" for ln in inner.split("\n"))]
        if tag == "hr":
            return ["---"]
        if tag == "dt":
            text = self._one_line(self.inline_children(el))
            return [f"**{text}**"] if text else []
        return self.blocks(el)

    def _finish_paragraph(self, text: str) -> str:
        """Collapse whitespace. One <br> is a line break; <br><br> starts a paragraph."""
        paragraphs: list[list[str]] = [[]]
        for raw in text.split("\n"):
            line = _WS.sub(" ", raw).strip()
            if line:
                paragraphs[-1].append(_escape_line_start(line))
            elif paragraphs[-1]:
                paragraphs.append([])
        return "\n\n".join("\n".join(p) for p in paragraphs if p)

    @staticmethod
    def _one_line(text: str) -> str:
        return _WS.sub(" ", text).strip()

    # -- code ------------------------------------------------------------------
    def _code_block(self, el: Element) -> list[str]:
        code = _raw_text(el)
        if code.startswith("\n"):
            code = code[1:]
        code = code.rstrip()
        if not code.strip():
            return []
        fence = _fence_for(code)
        return [f"{fence}{code_language(el)}\n{code}\n{fence}"]

    # -- lists -----------------------------------------------------------------
    def _list(self, el: Element) -> list[str]:
        ordered = el.tag == "ol"
        try:
            number = int(el.get("start") or 1)
        except ValueError:
            number = 1
        items: list[list[str]] = []
        for child in el.children:
            if isinstance(child, str):
                if child.strip():
                    items.append([self._finish_paragraph(_WS.sub(" ", child))])
                continue
            if child.tag in SKIP_TAGS:
                continue
            if child.tag == "li":
                items.append(self.blocks(child))
            elif child.tag in ("ul", "ol") and items:
                # A list nested directly in a list belongs to the previous item.
                items[-1].extend(self._list(child))
            else:
                rendered = self.block(child) if self._is_block(child) else [self.inline(child)]
                rendered = [self._finish_paragraph(b) for b in rendered]
                if any(rendered):
                    items.append([b for b in rendered if b])
        rendered_items: list[str] = []
        loose = False
        for blocks in items:
            blocks = [b for b in blocks if b.strip()]
            if not blocks:
                continue
            marker = f"{number}." if ordered else "-"
            number += 1
            prose = [b for b in blocks if not _is_list_block(b)]
            joiner = "\n\n" if len(prose) > 1 else "\n"
            loose = loose or joiner == "\n\n"
            body = joiner.join(blocks)
            pad = " " * (len(marker) + 1)
            lines = body.split("\n")
            text = f"{marker} {lines[0]}" + "".join(
                f"\n{pad}{ln}" if ln else "\n" for ln in lines[1:]
            )
            rendered_items.append(text)
        if not rendered_items:
            return []
        return [("\n\n" if loose else "\n").join(rendered_items)]

    # -- tables ----------------------------------------------------------------
    def _table(self, el: Element) -> list[str]:
        rows, stray = _table_parts(el)
        grid: list[list[str]] = []
        header_row = False
        layout = el.get("role") == "presentation" or any(t is not el for t in el.iter("table"))
        for r, tr in enumerate(rows):
            cells: list[str] = []
            tr_cells = [c for c in tr.elements if c.tag in ("td", "th")]
            for cell in tr_cells:
                cell_blocks = self.blocks(cell)
                if len(cell_blocks) > 3:
                    layout = True
                text = " ".join(self._one_line(b) for b in cell_blocks)
                cells.append(text.replace("|", "\\|"))
                try:
                    span = int(cell.get("colspan") or 1)
                except ValueError:
                    span = 1
                cells.extend([""] * (min(span, 50) - 1))
            if r == 0 and tr_cells and all(c.tag == "th" for c in tr_cells):
                header_row = True
            if any(c.strip() for c in cells):
                grid.append(cells)
        width = max((len(row) for row in grid), default=0)
        if layout or width < 2 or not grid:
            # Tables used for page layout: keep the content, drop the grid. Cells
            # come from the cache, so nested layout tables are rendered once each,
            # not once per enclosing level (which was exponential in depth).
            return self.blocks(el)
        # Content that is not in a cell (a <p> directly in <table>, a <div> in a
        # <tr>) is moved in front of the table by browsers ("foster parenting");
        # render it there rather than drop it.
        out = self._render_nodes(stray)
        caption = el.find("caption")
        if caption is not None:
            cap = self._one_line(self.inline_children(caption))
            if cap:
                out.append(cap)
        grid = [row + [""] * (width - len(row)) for row in grid]
        if not header_row:
            # GFM requires a header row; an empty one keeps data rows as data.
            grid.insert(0, [""] * width)
        lines = ["| " + " | ".join(grid[0]) + " |", "|" + "---|" * width]
        lines += ["| " + " | ".join(row) + " |" for row in grid[1:]]
        out.append("\n".join(lines))
        return out

    # -- inline mode -----------------------------------------------------------
    def inline_children(self, el: Element) -> str:
        parts: list[str] = []
        for child in el.children:
            if isinstance(child, str):
                parts.append(_WS.sub(" ", child))
            elif child.tag not in SKIP_TAGS:
                parts.append(self.inline(child))
        return "".join(parts)

    def inline(self, el: Element) -> str:
        tag = el.tag
        if tag in SKIP_TAGS:
            return ""
        if tag == "br":
            return "\n"
        if tag == "img":
            return self._image(el)
        if tag in ("code", "kbd", "samp", "tt"):
            return _inline_code(_WS.sub(" ", _raw_text(el)))
        inner = self.inline_children(el)
        if tag == "a":
            return self._link(el, inner)
        if tag in ("strong", "b"):
            return _wrap(inner, "**")
        if tag in ("em", "i", "cite", "dfn"):
            return _wrap(inner, "*")
        if tag in ("del", "s", "strike"):
            return _wrap(inner, "~~")
        if self._is_block(el):
            return " ".join(self.blocks(el))
        return inner

    def _link(self, el: Element, inner: str) -> str:
        href = el.get("href").strip()
        text = inner.strip()
        if not text:
            return inner
        if (
            not self.opts.links
            or not href
            or href.startswith("#")
            or href.lower().startswith(("javascript:", "data:"))
        ):
            return inner
        if self.opts.base_url:
            href = urljoin(self.opts.base_url, href)
        href = href.replace(" ", "%20").replace(")", "%29")
        lead = inner[: len(inner) - len(inner.lstrip())]
        trail = inner[len(inner.rstrip()) :]
        return f"{lead}[{text.replace(chr(10), ' ')}]({href}){trail}"

    def _image(self, el: Element) -> str:
        alt = _WS.sub(" ", el.get("alt")).strip().replace("[", "(").replace("]", ")")
        src = (el.get("src") or el.get("data-src")).strip()
        if not self.opts.images:
            return alt
        if not src or src.lower().startswith("data:"):
            return alt
        if self.opts.base_url:
            src = urljoin(self.opts.base_url, src)
        return f"![{alt}]({src.replace(' ', '%20').replace(')', '%29')})"


def _is_list_block(block: str) -> bool:
    return bool(re.match(r"^(?:[-+*]|\d+[.)]) ", block))


def _wrap(inner: str, mark: str) -> str:
    core = inner.strip()
    if not core:
        return inner
    if core.startswith(mark) and core.endswith(mark):
        return inner  # already emphasised by a nested tag
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{mark}{core}{mark}{trail}"


def _inline_code(text: str) -> str:
    core = text.strip()
    if not core:
        return text
    longest = max((len(m) for m in re.findall(r"`+", core)), default=0)
    ticks = "`" * (longest + 1)
    pad = " " if core.startswith("`") or core.endswith("`") else ""
    lead = " " if text[:1].isspace() else ""
    trail = " " if text[-1:].isspace() else ""
    return f"{lead}{ticks}{pad}{core}{pad}{ticks}{trail}"


def _raw_text(el: Element) -> str:
    """Text with whitespace preserved and ``<br>`` as a newline, for code."""
    parts: list[str] = []
    stack: list[Element | str] = [el]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            parts.append(node)
        elif node.tag == "br":
            parts.append("\n")
        elif node.tag not in SKIP_TAGS:
            stack.extend(reversed(node.children))
    return "".join(parts)


_ROW_GROUPS = frozenset({"thead", "tbody", "tfoot", "form"})
_TABLE_ONLY = frozenset({"caption", "colgroup", "col"})


def _table_parts(table: Element) -> tuple[list[Element], list[Element | str]]:
    """A table's rows, and the content browsers would move out in front of it.

    Rows count inside ``thead``/``tbody``/``tfoot`` and inside a ``<form>``
    wrapped around them (browsers keep the form empty and the rows in the
    table). Any other element or text outside a cell is *stray*: in document
    order, it is what the HTML parsing algorithm foster-parents before the table.
    """
    rows: list[Element] = []
    stray: list[Element | str] = []

    def walk(node: Element) -> None:
        for child in node.children:
            if isinstance(child, str):
                if child.strip():
                    stray.append(child)
            elif child.tag == "tr":
                rows.append(child)
                stray.extend(
                    c
                    for c in child.children
                    if (c.strip() if isinstance(c, str) else c.tag not in ("td", "th"))
                )
            elif child.tag in _ROW_GROUPS:
                walk(child)
            elif child.tag not in _TABLE_ONLY:
                stray.append(child)

    walk(table)
    return rows, stray


def to_markdown(root: Element, options: RenderOptions | None = None) -> str:
    return Renderer(options).render(root)
