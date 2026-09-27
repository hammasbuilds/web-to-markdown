"""``web2md`` command line."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from web2md import __version__
from web2md.convert import Conversion, convert
from web2md.fetch import FetchError, decode_html, fetch

EPILOG = """examples:
  web2md page.html                      main content as markdown
  curl -s https://example.com | web2md - --url https://example.com
  web2md page.html --front-matter       metadata as YAML front matter
  web2md page.html --json               markdown, metadata and token counts
  web2md https://example.com --fetch    fetch over the network (off by default)
"""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="web2md",
        description="Turn a web page into clean, agent-ready markdown. Offline by default.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("source", help="HTML file, '-' for stdin, or a URL (needs --fetch)")
    p.add_argument("--fetch", action="store_true", help="allow fetching SOURCE over HTTP(S)")
    p.add_argument(
        "--url", help="page URL, for resolving relative links (default: SOURCE if a URL)"
    )
    p.add_argument("--all", action="store_true", help="render the whole page, no extraction")
    p.add_argument("--no-links", action="store_true", help="keep link text, drop link targets")
    p.add_argument("--no-images", action="store_true", help="replace images with their alt text")
    out = p.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="print a JSON object instead")
    out.add_argument("--front-matter", action="store_true", help="prefix YAML front matter")
    p.add_argument("--stats", action="store_true", help="print token counts to stderr")
    p.add_argument("-o", "--output", type=Path, help="write to a file instead of stdout")
    p.add_argument("--timeout", type=float, default=20.0, help="fetch timeout in seconds")
    p.add_argument("--version", action="version", version=f"web2md {__version__}")
    return p


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a JSON string is valid YAML


def _front_matter(conv: Conversion) -> str:
    lines = ["---"]
    for key, value in conv.metadata.as_dict().items():
        if value:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---\n\n")
    return "\n".join(lines)


def _read_source(args: argparse.Namespace) -> tuple[str, str | None]:
    source: str = args.source
    if re.match(r"^https?://", source, re.I):
        if not args.fetch:
            raise SystemExit(
                f"web2md: {source} is a URL; pass --fetch to download it "
                "(web2md never touches the network unless asked)"
            )
        html, final_url = fetch(source, timeout=args.timeout)
        return html, args.url or final_url
    if source == "-":
        return decode_html(sys.stdin.buffer.read()), args.url
    path = Path(source)
    if not path.is_file():
        raise SystemExit(f"web2md: no such file: {source}")
    return decode_html(path.read_bytes()), args.url


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        html, url = _read_source(args)
    except FetchError as exc:
        print(f"web2md: {exc}", file=sys.stderr)
        return 2
    conv = convert(
        html,
        url,
        main_content=not args.all,
        links=not args.no_links,
        images=not args.no_images,
    )
    if args.json:
        text = json.dumps(conv.as_dict(), ensure_ascii=False, indent=2) + "\n"
    elif args.front_matter:
        text = _front_matter(conv) + conv.markdown
    else:
        text = conv.markdown
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stdout.write(text)
    for warning in conv.warnings:
        print(f"web2md: warning: {warning}", file=sys.stderr)
    if args.stats:
        print(
            f"tokens: html {conv.tokens_html:,} -> markdown {conv.tokens_markdown:,} "
            f"({conv.token_saving:.1%} saved, estimated)",
            file=sys.stderr,
        )
    return 0 if conv.markdown.strip() else 1


if __name__ == "__main__":
    raise SystemExit(main())
