"""Main-content extraction by DOM scoring.

The pipeline, each stage switchable for ablation:

1. **prune** - drop invisible and interactive elements, and (``hints``) elements
   whose tag or class/id marks them as navigation, comments, ads or chrome.
2. **score** - every paragraph-like block of at least 25 characters awards
   points (1 + commas + length/100, capped) to its parent and, decaying, to
   three more ancestors. Container tags and (``hints``) class/id words shift an
   ancestor's starting score. With ``link_density`` a candidate's score is
   multiplied by the share of its text that is *not* link text.
3. **siblings** - the best candidate's siblings join it when they score close
   to it or read as prose (long, few links).
4. **clean** - inside the result, remove blocks that look like boilerplate:
   link-heavy lists, image galleries, form widgets, a repeated title.

If the result is under ``MIN_CHARS`` characters on a page with at least twice
that much text, extraction reruns with ``hints`` off: class-name rules are the stage most
likely to remove the whole article on an unusual site.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from web2md.dom import Element

MIN_CHARS = 250

_ALWAYS_DROP = frozenset(
    [
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "math",
        "iframe",
        "object",
        "embed",
        "canvas",
        "button",
        "input",
        "select",
        "textarea",
        "dialog",
        "link",
        "meta",
        "head",
        "title",
    ]
)
_BOILERPLATE_TAGS = frozenset({"nav", "aside", "footer"})

_UNLIKELY = re.compile(
    r"-ad-|\bads?\b|ad-?(?:slot|unit|container|wrapper)|advert|agegate|banner|breadcrumb|"
    r"combx|comment|community|cookie|consent|cover-wrap|disqus|extra|footer|gdpr|"
    r"header|legends|menu|modal|newsletter|nav\b|navbar|outbrain|pager|pagination|"
    r"popup|promo|related|remark|replies|rss|share|sharing|shoutbox|sidebar|"
    r"skyscraper|social|sponsor|subscribe|supplemental|taboola|toolbar|trending|"
    r"widget|yom-remote",
    re.I,
)
_MAYBE = re.compile(r"and|article|body|column|content|main|shadow|story|post|entry", re.I)
_POSITIVE = re.compile(
    r"article|body|content|entry|hentry|h-entry|main|page|post|text|blog|story|prose", re.I
)
_NEGATIVE = re.compile(
    r"-ad-|hidden|\bhid\b|banner|combx|comment|com-|contact|footer|gdpr|masthead|media|"
    r"meta|outbrain|promo|related|scroll|share|shoutbox|sidebar|skyscraper|sponsor|"
    r"shopping|tags|widget|byline|caption|credit",
    re.I,
)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_PARAGRAPH_TAGS = frozenset({"p", "pre", "td", "blockquote"})
_BLOCK_CHILDREN = frozenset(
    [
        "address",
        "article",
        "aside",
        "blockquote",
        "dl",
        "div",
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
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "ul",
    ]
)
_TAG_BONUS = {
    "article": 10,
    "main": 5,
    "div": 5,
    "section": 3,
    "pre": 3,
    "td": 3,
    "blockquote": 3,
    "address": -3,
    "ol": -3,
    "ul": -3,
    "dl": -3,
    "dd": -3,
    "dt": -3,
    "li": -3,
    "form": -3,
    "h1": -5,
    "h2": -5,
    "h3": -5,
    "h4": -5,
    "h5": -5,
    "h6": -5,
    "th": -5,
}
_CLEANABLE = ("form", "fieldset", "table", "ul", "ol", "dl", "div", "section", "figure")


@dataclass(frozen=True)
class ExtractOptions:
    hints: bool = True  # tag and class/id name hints (nav/aside/footer, "sidebar", ...)
    link_density: bool = True  # penalise and clean link-heavy blocks
    siblings: bool = True  # merge qualifying siblings of the best candidate
    clean: bool = True  # conditional removal of boilerplate inside the result
    fallback: bool = True  # rerun without hints when the result is implausibly short


@dataclass
class Extraction:
    root: Element
    fallback_used: bool = False
    candidate_tag: str = ""


def _class_id(el: Element) -> str:
    return f"{el.get('class')} {el.get('id')}".strip()


def class_weight(el: Element) -> int:
    name = _class_id(el)
    if not name:
        return 0
    weight = 0
    if _NEGATIVE.search(name):
        weight -= 25
    if _POSITIVE.search(name):
        weight += 25
    if el.get("itemprop") == "articleBody":
        weight += 25
    return weight


def _is_hidden(el: Element) -> bool:
    return (
        "hidden" in el.attrs
        or el.get("aria-hidden").lower() == "true"
        or bool(_HIDDEN_STYLE.search(el.get("style")))
    )


def _collapse(text: str) -> str:
    return " ".join(text.split())


class _Measure:
    """Cached text length, link-text length and comma count per element."""

    def __init__(self) -> None:
        self._cache: dict[int, tuple[int, int, int]] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    def of(self, el: Element) -> tuple[int, int, int]:
        cached = self._cache.get(id(el))
        if cached is not None:
            return cached
        # Iterative post-order so very deep pages cannot hit the recursion limit.
        stack: list[tuple[Element, bool]] = [(el, False)]
        while stack:
            node, done = stack.pop()
            if id(node) in self._cache:
                continue
            if not done:
                stack.append((node, True))
                stack.extend((c, False) for c in node.elements if id(c) not in self._cache)
                continue
            text = link = commas = 0
            for child in node.children:
                if isinstance(child, str):
                    t = _collapse(child)
                    text += len(t)
                    commas += t.count(",") + t.count("，") + t.count("、")
                else:
                    ct, cl, cc = self._cache[id(child)]
                    text += ct
                    link += ct if child.tag == "a" else cl
                    commas += cc
            self._cache[id(node)] = (text, link, commas)
        return self._cache[id(el)]

    def text_len(self, el: Element) -> int:
        return self.of(el)[0]

    def link_density(self, el: Element) -> float:
        text, link, _ = self.of(el)
        return link / text if text else 0.0


def _prune(root: Element, opts: ExtractOptions) -> None:
    for el in list(root.iter()):
        if el.parent is None and el is not root:
            continue  # already detached with an ancestor
        tag = el.tag
        if tag in _ALWAYS_DROP or _is_hidden(el):
            el.remove()
            continue
        if not opts.hints or tag in ("html", "body", "#document", "article", "main", "a"):
            continue
        if tag in _BOILERPLATE_TAGS:
            el.remove()
            continue
        name = _class_id(el)
        if (
            name
            and _UNLIKELY.search(name)
            and not _MAYBE.search(name)
            and el.get("itemprop") != "articleBody"
            and not any(a.tag in ("table", "pre", "code") for a in el.ancestors())
        ):
            el.remove()
    # Unwrap the "div used as a paragraph" pattern: a div with only inline content.
    for el in root.iter("div"):
        if not any(c.tag in _BLOCK_CHILDREN for c in el.elements):
            el.attrs["data-web2md-paragraph"] = "1"


def _score(root: Element, opts: ExtractOptions, measure: _Measure) -> dict[int, float]:
    scores: dict[int, float] = {}
    nodes: dict[int, Element] = {}

    def init(el: Element) -> None:
        if id(el) in scores:
            return
        base = float(_TAG_BONUS.get(el.tag, 0))
        if opts.hints:
            base += class_weight(el)
        scores[id(el)] = base
        nodes[id(el)] = el

    def award(text_len: int, commas: int, first: Element | None) -> None:
        points = 1 + commas + min(text_len // 100, 3)
        level = 0
        anc = first
        while anc is not None and anc.tag not in ("#document", "html") and level <= 3:
            init(anc)
            divider = 1 if level == 0 else 2 if level == 1 else level * 3
            scores[id(anc)] += points / divider
            anc, level = anc.parent, level + 1

    for el in root.iter():
        is_para = el.tag in _PARAGRAPH_TAGS or "data-web2md-paragraph" in el.attrs
        if is_para:
            text_len, _, commas = measure.of(el)
            if text_len >= 25 and el.parent is not None:
                award(text_len, commas, el.parent)
            continue
        # Bare text between block children (<br>-separated prose, common on
        # Blogger and older CMSs) counts as paragraphs of this element.
        if el.tag in ("li", "dt", "dd", "th", "a") or not any(
            c.tag in _BLOCK_CHILDREN for c in el.elements
        ):
            continue
        for text_len, link_len, commas in _text_runs(el, measure):
            if text_len >= 25 and link_len * 2 < text_len:
                award(text_len, commas, el)
    if opts.link_density:
        for key, el in nodes.items():
            scores[key] *= 1 - measure.link_density(el)
    return scores


def _text_runs(el: Element, measure: _Measure) -> list[tuple[int, int, int]]:
    """(text, link text, commas) for each run of inline content between block children."""
    runs: list[tuple[int, int, int]] = []
    text = link = commas = 0
    for child in el.children:
        if isinstance(child, str):
            t = _collapse(child)
            text += len(t)
            commas += t.count(",") + t.count("，") + t.count("、")
        elif child.tag in _BLOCK_CHILDREN or child.tag in _PARAGRAPH_TAGS:
            if text:
                runs.append((text, link, commas))
            text = link = commas = 0
        else:
            ct, cl, cc = measure.of(child)
            text += ct
            link += ct if child.tag == "a" else cl
            commas += cc
    if text:
        runs.append((text, link, commas))
    return runs


def _ranked(scores: dict[int, float], root: Element) -> list[tuple[float, Element]]:
    ranked = [(scores[id(el)], el) for el in root.iter() if id(el) in scores]
    ranked.sort(key=lambda pair: pair[0], reverse=True)  # stable: ties keep document order
    return ranked


def _common_ancestor(nodes: list[Element]) -> Element | None:
    chains = [[n, *n.ancestors()] for n in nodes]
    shared = set.intersection(*({id(a) for a in chain} for chain in chains))
    return next((a for a in chains[0] if id(a) in shared), None)


def _promote(ranked: list[tuple[float, Element]]) -> Element | None:
    """Move from the best candidate up to the container of a split article.

    Long articles are often cut into several sibling or cousin containers by
    ads and pull quotes. Two signals say the best candidate is one such chunk:
    another strong candidate with the *same class* (a repeated body template), or
    three strong candidates of any kind that share an ancestor below ``<body>``.
    """
    if not ranked:
        return None
    top_score, top = ranked[0]
    if top_score <= 0:
        return top
    strong = [
        el
        for score, el in ranked[1:10]
        if score >= 0.5 * top_score and top not in el.ancestors() and el not in top.ancestors()
    ]
    same_class = [
        el
        for el in strong
        if el.tag == top.tag and el.get("class") and el.get("class") == top.get("class")
    ]
    group = same_class or ([el for el in strong if _score_ratio(ranked, el) >= 0.75][:3])
    if not group or (not same_class and len(group) < 3):
        return top
    lca = _common_ancestor([top, *group])
    if lca is None or lca.tag in ("body", "html", "#document"):
        return top
    return lca


def _score_ratio(ranked: list[tuple[float, Element]], el: Element) -> float:
    top_score = ranked[0][0]
    return next((s for s, e in ranked if e is el), 0.0) / top_score


def _merge_siblings(
    top: Element, scores: dict[int, float], measure: _Measure, opts: ExtractOptions
) -> Element:
    parent = top.parent
    if parent is None or parent.tag in ("#document", "html"):
        return top
    top_score = scores.get(id(top), 0.0)
    threshold = max(10.0, top_score * 0.2)
    kept: list[Element | str] = []
    for sib in parent.children:
        if isinstance(sib, str):
            continue
        if sib is top:
            kept.append(sib)
            continue
        bonus = top_score * 0.2 if sib.get("class") and sib.get("class") == top.get("class") else 0
        if scores.get(id(sib), 0.0) + bonus >= threshold:
            kept.append(sib)
            continue
        if sib.tag == "p" or "data-web2md-paragraph" in sib.attrs:
            text_len = measure.text_len(sib)
            density = measure.link_density(sib) if opts.link_density else 0.0
            text = _collapse(sib.text())
            if (text_len > 80 and density < 0.25) or (
                0 < text_len <= 80 and density == 0 and re.search(r"\.( |$)", text)
            ):
                kept.append(sib)
    if len(kept) == 1:
        return top
    container = Element("div", {}, [], None)
    for node in kept:
        assert isinstance(node, Element)
        node.parent = container
        container.children.append(node)
    return container


def _is_data_table(table: Element) -> bool:
    if table.get("role") == "presentation":
        return False
    if table.find("th", "caption", "thead") is not None:
        return True
    rows = [tr for tr in table.iter("tr")]
    if len(rows) >= 3 and all(len([c for c in tr.elements if c.tag == "td"]) >= 2 for tr in rows):
        return table.find("table") is table  # no nested layout tables
    return False


def _clean(
    root: Element,
    scores: dict[int, float],
    measure: _Measure,
    opts: ExtractOptions,
    title: str,
) -> None:
    # Articles nested inside the article are teasers ("you may also like") or
    # comments; a <header> inside it carries the headline, byline and date.
    for el in list(root.iter("article", "header")):
        if el is root or not _attached(el, root):
            continue
        inside_article = root.tag == "article" or any(
            a.tag == "article" for a in el.ancestors() if _attached(a, root)
        )
        if (
            el.tag == "article"
            and inside_article
            or el.tag == "header"
            and measure.text_len(el) < 400
            and el.find("p") is None
        ):
            el.remove()
    # Short blocks whose class says byline, share bar, tags, credit or caption.
    if opts.hints:
        for el in list(root.iter()):
            if (
                el is not root
                and el.tag not in ("a", "pre", "table", "tr", "td", "th", "code")
                and _attached(el, root)
                and class_weight(el) < 0
                and measure.text_len(el) < 150
                and el.find("pre", "table") is None
            ):
                el.remove()
        measure.invalidate()
    # Figures are pictures plus captions; captions are not article prose.
    for el in list(root.iter("figure", "figcaption")):
        if el is not root and _attached(el, root) and el.find("pre", "table") is None:
            el.remove()
    measure.invalidate()
    candidates = [el for el in root.iter(*_CLEANABLE) if el is not root]
    for el in reversed(candidates):  # innermost first
        if not _attached(el, root):
            continue  # an ancestor was already removed
        if el.find("pre") is not None or (el.tag == "table" and _is_data_table(el)):
            continue
        weight = class_weight(el) if opts.hints else 0
        if weight + scores.get(id(el), 0.0) < 0:
            el.remove()
            measure.invalidate()
            continue
        text_len, link_len, commas = measure.of(el)
        if commas >= 10:
            continue
        paras = _prose_blocks(el, measure)
        imgs = sum(1 for _ in el.iter("img"))
        items = sum(1 for _ in el.iter("li")) - 100
        inputs = sum(1 for _ in el.iter("input", "select", "textarea"))
        density = link_len / text_len if text_len else 0.0
        in_figure = el.tag == "figure" or any(a.tag == "figure" for a in el.ancestors())
        remove = (
            (imgs > 1 and paras / imgs < 0.5 and not in_figure)
            or (el.tag not in ("ul", "ol") and items > paras)
            or inputs > paras / 3
            or (text_len < 25 and (imgs == 0 or imgs > 2) and not in_figure)
        )
        if opts.link_density:
            remove = remove or (weight < 25 and density > 0.2) or (weight >= 25 and density > 0.5)
        if remove:
            el.remove()
            measure.invalidate()
    for heading in list(root.iter("h1", "h2", "h3", "h4", "h5", "h6")):
        text = _collapse(heading.text())
        if (
            (opts.hints and class_weight(heading) < 0)
            or (opts.link_density and measure.link_density(heading) > 0.33)
            or (title and heading.tag in ("h1", "h2") and _same_title(text, title))
        ):
            heading.remove()


def _prose_blocks(el: Element, measure: _Measure) -> int:
    """Paragraph count that also sees <br>-separated text and div-paragraphs."""
    count = 0
    for node in el.iter():
        if node.tag == "p" or (
            "data-web2md-paragraph" in node.attrs and measure.text_len(node) >= 25
        ):
            count += 1
        elif node.tag not in ("li", "a"):
            count += sum(1 for t, _, _ in _text_runs(node, measure) if t >= 25)
    return count


def _attached(el: Element, root: Element) -> bool:
    node: Element | None = el
    while node is not None:
        if node is root:
            return True
        node = node.parent
    return False


def _same_title(a: str, b: str) -> bool:
    wa = re.findall(r"\w+", a.lower())
    wb = re.findall(r"\w+", b.lower())
    if not wa or not wb:
        return False
    if wa == wb:
        return True
    # Titles in <title> often carry a site-name suffix; accept a containing match.
    shorter, longer = sorted((wa, wb), key=len)
    n = len(shorter)
    return n >= 3 and any(longer[i : i + n] == shorter for i in range(len(longer) - n + 1))


def _run(root: Element, opts: ExtractOptions, title: str) -> tuple[Element, str]:
    measure = _Measure()
    _prune(root, opts)
    body = root.find("body") or root
    scores = _score(body, opts, measure)
    top = _promote(_ranked(scores, body)) or body
    tag = top.tag
    article = _merge_siblings(top, scores, measure, opts) if opts.siblings else top
    if opts.clean:
        _clean(article, scores, measure, opts, title)
    return article, tag


def extract(
    parse_tree: Callable[[], Element],
    options: ExtractOptions | None = None,
    title: str = "",
) -> Extraction:
    """Extract the main content.

    ``parse_tree`` returns a fresh DOM each call: extraction mutates the tree, and
    the fallback pass needs an untouched one.
    """
    opts = options or ExtractOptions()
    root = parse_tree()
    total = len(_collapse(root.text()))
    article, tag = _run(root, opts, title)
    found = len(_collapse(article.text()))
    if opts.fallback and opts.hints and found < MIN_CHARS and total >= 2 * max(found, MIN_CHARS):
        retry, retry_tag = _run(parse_tree(), replace(opts, hints=False), title)
        if len(_collapse(retry.text())) > len(_collapse(article.text())):
            return Extraction(retry, fallback_used=True, candidate_tag=retry_tag)
    return Extraction(article, candidate_tag=tag)
