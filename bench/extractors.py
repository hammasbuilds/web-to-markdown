"""Every system the benchmark compares, behind one signature: ``html -> markdown``.

Two home-grown baselines bracket web2md: ``all-text`` renders the whole page
(the recall ceiling and precision floor), and ``largest-block`` is the classic
one-rule heuristic "the element holding the most paragraph text is the article".

Third-party tools are optional (``uv sync --group baselines``). When one cannot
be imported it is reported as unavailable, never silently dropped. Tools that
return HTML (readability-lxml) are rendered with web2md's own renderer, so the
comparison isolates *extraction*; tools that render markdown themselves
(html2text, markdownify, trafilatura) are taken as-is, so the structure
comparison also reflects their renderers.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from dataclasses import dataclass
from html import escape

from web2md import ExtractOptions, convert
from web2md.dom import VOID_TAGS, Element, parse
from web2md.extract import _collapse
from web2md.markdown import to_markdown

Extractor = Callable[[str], str]


@dataclass(frozen=True)
class System:
    name: str
    run: Extractor
    version: str
    markdown: bool  # does it emit markdown structure at all?
    note: str = ""


def _web2md(options: ExtractOptions | None = None) -> Extractor:
    def run(html: str) -> str:
        return convert(html, options=options).markdown

    return run


def _all_text(html: str) -> str:
    return convert(html, main_content=False).markdown


def _largest_block(html: str) -> str:
    """Pick the parent of the most paragraph text; render it. No pruning, no scoring."""
    root = parse(html)
    totals: dict[int, int] = {}
    nodes: dict[int, Element] = {}
    for p in root.iter("p"):
        if p.parent is None:
            continue
        n = len(_collapse(p.text()))
        if n >= 25:
            totals[id(p.parent)] = totals.get(id(p.parent), 0) + n
            nodes[id(p.parent)] = p.parent
    if not totals:
        body = root.find("body") or root
        return to_markdown(body)
    best = max(totals, key=lambda k: totals[k])
    return to_markdown(nodes[best])


def _version(dist: str) -> str:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _optional_systems() -> tuple[list[System], dict[str, str]]:
    systems: list[System] = []
    missing: dict[str, str] = {}

    try:
        import html2text

        def run_html2text(html: str) -> str:
            h = html2text.HTML2Text()
            h.body_width = 0
            return h.handle(html)

        systems.append(
            System(
                "html2text", run_html2text, _version("html2text"), True, "whole page, no extraction"
            )
        )
    except ImportError as exc:
        missing["html2text"] = str(exc)

    try:
        import markdownify

        def run_markdownify(html: str) -> str:
            # markdownify renders every tag it meets; drop non-content ones first.
            return markdownify.MarkdownConverter(
                heading_style="ATX", escape_underscores=False, escape_asterisks=False
            ).convert(_strip_invisible(html))

        systems.append(
            System(
                "markdownify",
                run_markdownify,
                _version("markdownify"),
                True,
                "whole page, no extraction",
            )
        )
    except ImportError as exc:
        missing["markdownify"] = str(exc)

    try:
        from readability import Document

        def run_readability(html: str) -> str:
            summary = Document(html).summary(html_partial=True)
            return to_markdown(parse(summary))

        systems.append(
            System(
                "readability-lxml",
                run_readability,
                _version("readability-lxml"),
                True,
                "extraction by readability-lxml, rendered by web2md",
            )
        )
    except ImportError as exc:
        missing["readability-lxml"] = str(exc)

    try:
        import trafilatura

        def run_trafilatura_md(html: str) -> str:
            return (
                trafilatura.extract(
                    html,
                    output_format="markdown",
                    include_comments=False,
                    include_tables=True,
                    include_formatting=True,
                    include_links=True,
                    include_images=True,
                )
                or ""
            )

        def run_trafilatura_txt(html: str) -> str:
            return trafilatura.extract(html, include_comments=False) or ""

        version = _version("trafilatura")
        systems.append(
            System(
                "trafilatura",
                run_trafilatura_txt,
                version,
                False,
                "default settings, plain text (as in the published benchmark)",
            )
        )
        systems.append(
            System(
                "trafilatura-md",
                run_trafilatura_md,
                version,
                True,
                "markdown output with tables, formatting, links, images",
            )
        )
    except ImportError as exc:
        missing["trafilatura"] = str(exc)
    return systems, missing


def _strip_invisible(html: str) -> str:
    root = parse(html)
    for el in list(root.iter("script", "style", "noscript", "template", "head", "svg")):
        el.remove()
    return _serialise(root)


def _serialise(el: Element | str) -> str:
    if isinstance(el, str):
        return escape(el, quote=False)
    inner = "".join(_serialise(c) for c in el.children)
    if el.tag == "#document":
        return inner
    attrs = "".join(f' {k}="{escape(v)}"' for k, v in el.attrs.items())
    if el.tag in VOID_TAGS:
        return f"<{el.tag}{attrs}>"
    return f"<{el.tag}{attrs}>{inner}</{el.tag}>"


def systems(include_ablations: bool = True) -> tuple[list[System], dict[str, str]]:
    ours = _version("web2md")
    out = [
        System("web2md", _web2md(), ours, True),
        System("all-text", _all_text, ours, True, "whole page rendered by web2md, no extraction"),
        System(
            "largest-block",
            _largest_block,
            ours,
            True,
            "parent of the most <p> text, rendered by web2md",
        ),
    ]
    if include_ablations:
        for field, label in (
            ("hints", "no-hints"),
            ("link_density", "no-link-density"),
            ("siblings", "no-siblings"),
            ("clean", "no-clean"),
            ("fallback", "no-fallback"),
        ):
            opts = ExtractOptions(**{field: False})
            out.append(
                System(f"web2md[{label}]", _web2md(opts), ours, True, f"ablation: {field} off")
            )
    extra, missing = _optional_systems()
    return out + extra, missing
