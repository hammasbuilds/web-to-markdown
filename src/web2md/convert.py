"""The one-call API: HTML in, markdown plus metadata and token counts out."""

from __future__ import annotations

from dataclasses import dataclass, field

from web2md.dom import parse
from web2md.extract import ExtractOptions, extract
from web2md.markdown import RenderOptions, to_markdown
from web2md.metadata import Metadata, extract_metadata
from web2md.tokens import estimate_tokens


@dataclass
class Conversion:
    markdown: str
    metadata: Metadata
    tokens_html: int
    tokens_markdown: int
    extracted: bool
    fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def token_saving(self) -> float:
        """Share of the HTML's estimated tokens that the markdown does not spend."""
        if not self.tokens_html:
            return 0.0
        return 1 - self.tokens_markdown / self.tokens_html

    def as_dict(self) -> dict[str, object]:
        return {
            "metadata": self.metadata.as_dict(),
            "markdown": self.markdown,
            "tokens": {
                "html": self.tokens_html,
                "markdown": self.tokens_markdown,
                "saving": round(self.token_saving, 4),
                "estimator": "web2md.tokens.estimate_tokens",
            },
            "extracted": self.extracted,
            "fallback_used": self.fallback_used,
            "warnings": self.warnings,
        }


def convert(
    html: str,
    url: str | None = None,
    *,
    main_content: bool = True,
    links: bool = True,
    images: bool = True,
    options: ExtractOptions | None = None,
) -> Conversion:
    """Convert an HTML document to agent-ready markdown.

    ``url`` resolves relative links and is the canonical-URL fallback.
    ``main_content=False`` renders the whole ``<body>`` instead of extracting.
    """
    tree = parse(html)
    metadata = extract_metadata(tree, base_url=url)
    if not metadata.canonical_url and url:
        metadata.canonical_url = url
    render = RenderOptions(base_url=url, links=links, images=images)
    fallback = False
    if main_content:
        result = extract(lambda: parse(html), options, title=metadata.title)
        root, fallback = result.root, result.fallback_used
    else:
        root = tree.find("body") or tree
    markdown = to_markdown(root, render)
    warnings: list[str] = []
    if not markdown.strip():
        warnings.append("no text content found")
    elif main_content and len(markdown) < 200:
        warnings.append("extracted content is very short; try --all for the full page")
    return Conversion(
        markdown=markdown,
        metadata=metadata,
        tokens_html=estimate_tokens(html),
        tokens_markdown=estimate_tokens(markdown),
        extracted=main_content,
        fallback_used=fallback,
        warnings=warnings,
    )
