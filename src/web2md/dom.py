"""A small, forgiving DOM built on the standard library's ``html.parser``.

``html.parser`` is a tokenizer, not a tree builder: it reports start and end tags
and leaves nesting to the caller. Real pages close ``<p>`` and ``<li>`` implicitly,
leave ``<td>`` open, and emit stray end tags, so the builder below applies the
handful of HTML5 implied-end rules that matter for content and ignores end tags
that match nothing open.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID_TAGS = frozenset(
    [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "keygen",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
)

# A start tag from this set closes an open <p> (HTML5 "close a p element").
_CLOSES_P = frozenset(
    [
        "address",
        "article",
        "aside",
        "blockquote",
        "details",
        "dialog",
        "div",
        "dl",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "main",
        "menu",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    ]
)

# tag -> (open tag it implicitly closes, with everything inside it; tags that stop
# the search). Closing through the match also closes any cell or item inside it.
_IMPLIED_END: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "li": (frozenset({"li"}), frozenset({"ul", "ol", "menu"})),
    "dt": (frozenset({"dt", "dd"}), frozenset({"dl"})),
    "dd": (frozenset({"dt", "dd"}), frozenset({"dl"})),
    "tr": (frozenset({"tr"}), frozenset({"table", "thead", "tbody", "tfoot"})),
    "td": (frozenset({"td", "th"}), frozenset({"tr", "table"})),
    "th": (frozenset({"td", "th"}), frozenset({"tr", "table"})),
    "thead": (frozenset({"thead", "tbody", "tfoot"}), frozenset({"table"})),
    "tbody": (frozenset({"thead", "tbody", "tfoot"}), frozenset({"table"})),
    "tfoot": (frozenset({"thead", "tbody", "tfoot"}), frozenset({"table"})),
    "option": (frozenset({"option"}), frozenset({"select", "datalist", "optgroup"})),
}

MAX_DEPTH = 200

# Raw-text elements whose contents html.parser already treats as CDATA.
RAW_TEXT_TAGS = frozenset({"script", "style"})


@dataclass(eq=False)
class Element:
    """An element node. Text children are plain ``str``."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Element | str] = field(default_factory=list)
    parent: Element | None = field(default=None, repr=False)

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def elements(self) -> list[Element]:
        return [c for c in self.children if isinstance(c, Element)]

    def iter(self, *tags: str) -> Iterator[Element]:
        """Depth-first, document-order walk over descendant elements (self included)."""
        stack: list[Element] = [self]
        while stack:
            node = stack.pop()
            if not tags or node.tag in tags:
                yield node
            stack.extend(reversed(node.elements))

    def find(self, *tags: str) -> Element | None:
        return next(self.iter(*tags), None)

    def ancestors(self) -> Iterator[Element]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def text(self) -> str:
        """All descendant text, script and style excluded, whitespace untouched."""
        parts: list[str] = []
        stack: list[Element | str] = [self]
        while stack:
            node = stack.pop()
            if isinstance(node, str):
                parts.append(node)
            elif node.tag not in RAW_TEXT_TAGS:
                stack.extend(reversed(node.children))
        return "".join(parts)

    def remove(self) -> None:
        if self.parent is not None:
            self.parent.children = [c for c in self.parent.children if c is not self]
            self.parent = None


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document")
        self.stack: list[Element] = [self.root]

    # -- helpers -----------------------------------------------------------
    def _close_through(self, index: int) -> None:
        del self.stack[index:]

    def _find_open(self, tags: frozenset[str], boundary: frozenset[str]) -> int | None:
        for i in range(len(self.stack) - 1, 0, -1):
            tag = self.stack[i].tag
            if tag in tags:
                return i
            if tag in boundary:
                return None
        return None

    # -- HTMLParser callbacks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _CLOSES_P:
            idx = self._find_open(frozenset({"p"}), frozenset({"button", "table", "td", "th"}))
            if idx is not None:
                self._close_through(idx)
        implied = _IMPLIED_END.get(tag)
        if implied is not None:
            idx = self._find_open(*implied)
            if idx is not None:
                self._close_through(idx)
        parent = self.stack[-1]
        node = Element(tag, {k: (v or "") for k, v in attrs}, [], parent)
        parent.children.append(node)
        if tag not in VOID_TAGS and len(self.stack) < MAX_DEPTH:
            # Past MAX_DEPTH (runs of never-closed <font>/<b> tags) the element is
            # kept but its content stays with the parent, bounding tree depth.
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._find_open(frozenset({"p"}), frozenset()) is None:
            # A stray </p> creates an empty paragraph in browsers; it has no text.
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self._close_through(i)
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def parse(html: str) -> Element:
    """Parse ``html`` into an :class:`Element` tree rooted at ``#document``."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root
