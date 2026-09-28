"""A small, forgiving DOM built on the standard library's ``html.parser``.

``html.parser`` is a tokenizer, not a tree builder: it reports start and end tags
and leaves nesting to the caller. Real pages close ``<p>`` and ``<li>`` implicitly,
leave ``<td>`` open, and emit stray end tags, so the builder below applies the
handful of HTML5 implied-end rules that matter for content and ignores end tags
that match nothing open.
"""

from __future__ import annotations

from collections.abc import Iterator
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

# Elements allowed in <head>; any other start tag there implies </head>.
_HEAD_TAGS = frozenset(
    {
        "html",
        "head",
        "body",
        "title",
        "meta",
        "link",
        "style",
        "script",
        "noscript",
        "base",
        "template",
    }
)

# Raw-text elements whose contents html.parser already treats as CDATA.
RAW_TEXT_TAGS = frozenset({"script", "style"})


class Element:
    """An element node. Text children are plain ``str``.

    Removal is lazy: :meth:`remove` only detaches the node (``parent = None``) and
    marks the parent dirty; the parent's child list is compacted once, the next
    time it is read. Removing k of n siblings therefore costs O(n), not O(k*n),
    which matters on pages with tens of thousands of sibling elements.
    """

    __slots__ = ("tag", "attrs", "_children", "parent", "_dirty")

    def __init__(
        self,
        tag: str,
        attrs: dict[str, str] | None = None,
        children: list[Element | str] | None = None,
        parent: Element | None = None,
    ) -> None:
        self.tag = tag
        self.attrs = attrs if attrs is not None else {}
        self._children: list[Element | str] = children if children is not None else []
        self.parent = parent
        self._dirty = False

    def __repr__(self) -> str:
        return f"Element({self.tag!r}, {self.attrs!r})"

    @property
    def children(self) -> list[Element | str]:
        if self._dirty:
            # Keep text, and elements that still name this node as their parent
            # (removed or re-parented elements do not).
            self._children = [c for c in self._children if isinstance(c, str) or c.parent is self]
            self._dirty = False
        return self._children

    @children.setter
    def children(self, value: list[Element | str]) -> None:
        self._children = value
        self._dirty = False

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
            self.parent._dirty = True
            self.parent = None

    def adopt(self, child: Element) -> None:
        """Move ``child`` (and its subtree) to the end of this element's children."""
        if child.parent is not None:
            child.parent._dirty = True
        child.parent = self
        self.children.append(child)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document")
        self.stack: list[Element] = [self.root]
        # How many elements of each tag are open, so the common "is a <p> open?"
        # question does not scan a stack that can be MAX_DEPTH deep.
        self.open_count: dict[str, int] = {}
        self.seen_document_tags: dict[str, bool] = {}

    # -- helpers -----------------------------------------------------------
    def _close_through(self, index: int) -> None:
        for el in self.stack[index:]:
            self.open_count[el.tag] -= 1
        del self.stack[index:]

    def _find_open(self, tags: frozenset[str], boundary: frozenset[str]) -> int | None:
        if not any(self.open_count.get(t) for t in tags):
            return None
        for i in range(len(self.stack) - 1, 0, -1):
            tag = self.stack[i].tag
            if tag in tags:
                return i
            if tag in boundary:
                return None
        return None

    def _leave_head(self) -> None:
        """Close an open <head> when body content arrives, as browsers do.

        A broken attribute quote in a <meta> tag can swallow ``</head><body>``;
        without this rule the whole page would then be parsed as head content.
        """
        if self.stack[-1].tag == "head":
            self._close_through(len(self.stack) - 1)

    def _document_tag(self, tag: str) -> bool:
        """Whether an <html>/<head>/<body> start tag should create an element.

        Only the first of each does, and only at document level. Pages write
        ``<body>`` inside ``<noscript>`` or ``document.write`` fallbacks; taken
        literally, that tiny element becomes "the body" and the real page, which
        sits outside it, is lost.
        """
        if self.seen_document_tags.get(tag):
            return False
        open_tags = {el.tag for el in self.stack[1:]}
        allowed = {"html": set(), "head": {"html"}, "body": {"html", "head"}}[tag]
        if not open_tags <= allowed:
            return False
        if tag == "body" and "head" in open_tags:
            self._close_through(next(i for i, el in enumerate(self.stack) if el.tag == "head"))
        self.seen_document_tags[tag] = True
        return True

    # -- HTMLParser callbacks ------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("html", "head", "body") and not self._document_tag(tag):
            return
        if tag not in _HEAD_TAGS:
            self._leave_head()
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
            self.open_count[tag] = self.open_count.get(tag, 0) + 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        before = self.stack[-1]
        self.handle_starttag(tag, attrs)
        top = self.stack[-1]
        if top is not before and top.tag == tag and not top.children:
            self._close_through(len(self.stack) - 1)  # "<div/>": the XHTML form, closed

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._find_open(frozenset({"p"}), frozenset()) is None:
            # A stray </p> creates an empty paragraph in browsers; it has no text.
            return
        if not self.open_count.get(tag):
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                self._close_through(i)
                return

    def handle_data(self, data: str) -> None:
        if data.strip() and self.stack[-1].tag == "head":
            self._leave_head()  # visible text cannot live in <head>
        if data:
            self.stack[-1].children.append(data)


def parse(html: str) -> Element:
    """Parse ``html`` into an :class:`Element` tree rooted at ``#document``."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root
