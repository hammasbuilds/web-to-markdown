"""Run web2md on the four pages in examples/ and check each against its known answer.

Every example page is hand-written so the right output is known exactly: which
sentences are the article, which are navigation, adverts, related links or
comments, and which structures (table, code, nested list) must come through.

    uv run python demo.py            # summary + checks
    uv run python demo.py --show     # also print each page's markdown
"""

from __future__ import annotations

import sys
from pathlib import Path

from web2md import convert

EXAMPLES = Path(__file__).resolve().parent / "examples"

# page -> (text that must appear, text that must not appear)
EXPECTED: dict[str, tuple[list[str], list[str]]] = {
    "news_article.html": (
        [
            "reopened to traffic on Monday morning",
            "1,248 suspension hangers",
            "## What changed",
            "- A dedicated cycle lane on the northern side",
            "| 2021 | 40,200 |",
            "> It feels like getting half the town back.",
            "Tolls will not be charged for the first month.",
        ],
        [
            "cookies",
            "Sponsored",
            "Related stories",
            "Share on",
            "My commute",
            "All rights reserved",
            "Weather",
        ],
    ),
    "docs_page.html": (
        [
            "```python\nfrom fetchkit import Client, Retry\n\nclient = Client(",
            "| HTTP 503 | yes | honours `Retry-After` |",
            "3. 2 seconds\n   - capped by `max_backoff`",
            "```bash\n$ fetchkit get https://api.example/items --retries 3\n```",
        ],
        ["Search docs", "Installation", "Previous", "Built with Sphinx"],
    ),
    "blogger_post.html": (
        [
            "The first frost arrived three weeks early",
            "gone soft at the crown",
            "cover the brassicas with netting",
        ],
        ["Blog Archive", "Email This", "Shropshire", "Retired teacher", "Labels:"],
    ),
    "recipe_page.html": (
        [
            "- 250 g red lentils, rinsed",
            "3. Add the lentils, coconut milk and 500 ml of water.",
            "> Tip: the dal thickens as it cools.\n>\n> > Loosen leftovers",
        ],
        ["Newsletter", "Subscribe", "You might also like", "Chana masala", "Privacy"],
    ),
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    show = "--show" in sys.argv
    failures = 0
    for name, (must, must_not) in EXPECTED.items():
        html = (EXAMPLES / name).read_text(encoding="utf-8")
        result = convert(html)
        md = result.markdown
        missing = [m for m in must if m not in md]
        leaked = [m for m in must_not if m in md]
        failures += len(missing) + len(leaked)
        meta = result.metadata
        print(f"== {name}")
        print(f"   title   : {meta.title}")
        print(f"   author  : {meta.author or '-'}   date: {meta.date or '-'}")
        print(
            f"   tokens  : {result.tokens_html:,} html -> {result.tokens_markdown:,} markdown "
            f"({result.token_saving:.0%} fewer, estimated)"
        )
        print(f"   kept    : {len(must) - len(missing)}/{len(must)} required passages")
        print(f"   leaked  : {len(leaked)}/{len(must_not)} boilerplate passages")
        for m in missing:
            print(f"   MISSING : {m!r}")
        for m in leaked:
            print(f"   LEAKED  : {m!r}")
        if show:
            print("   " + md.replace("\n", "\n   "))
    print("all checks passed" if not failures else f"{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
