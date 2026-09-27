"""Print the README's tables from ``results/*.json``, so every number is traceable.

uv run python -m bench.summary
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RESULTS = Path(__file__).resolve().parent.parent / "results"
ORDER = [
    "web2md",
    "trafilatura",
    "trafilatura-md",
    "readability-lxml",
    "largest-block",
    "all-text",
    "html2text",
    "markdownify",
]


def load(name: str) -> Any:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def f1_table() -> str:
    groups = load("extraction.json")["groups"]
    cols = ["aeb/dev", "aeb/heldout", "wceb (all)"]
    lines = [
        "| system | AEB dev (80) | AEB held-out (101) | WCEB, 7 datasets (3,794) |",
        "|---|---|---|---|",
    ]
    for s in ORDER:
        cells = []
        for g in cols:
            row = groups[g]["systems"][s]
            lo, hi = row["f1_ci95"]
            cells.append(f"{row['f1']:.3f} [{lo:.3f}, {hi:.3f}]")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def per_dataset_table() -> str:
    groups = load("extraction.json")["groups"]
    names = [g for g in groups if g.startswith("wceb/")]
    systems = ["web2md", "trafilatura", "readability-lxml", "all-text"]
    lines = [
        "| dataset | pages | " + " | ".join(systems) + " |",
        "|---|---|" + "---|" * len(systems),
    ]
    for g in names:
        row = groups[g]
        best = max(row["systems"][s]["f1"] for s in systems)
        cells = []
        for s in systems:
            f1 = row["systems"][s]["f1"]
            cells.append(f"**{f1:.3f}**" if f1 == best else f"{f1:.3f}")
        lines.append(f"| {g.split('/')[1]} | {row['n_pages']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def paired_table() -> str:
    groups = load("paired_diffs.json")["groups"]
    lines = ["| web2md minus | AEB held-out | WCEB (all) |", "|---|---|---|"]
    for s in ORDER[1:]:
        cells = []
        for g in ("aeb/heldout", "wceb (all)"):
            d = groups[g][s]
            mark = "" if d["significant"] else " (n.s.)"
            cells.append(f"{d['f1_diff']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]{mark}")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def ablation_table() -> str:
    groups = load("ablations.json")["groups"]
    lines = ["| variant | AEB dev | AEB held-out | WCEB (all) |", "|---|---|---|---|"]
    for s in groups["aeb/dev"]["systems"]:
        cells = [
            f"{groups[g]['systems'][s]['f1']:.3f}" for g in ("aeb/dev", "aeb/heldout", "wceb (all)")
        ]
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def structure_table(group: str = "all") -> str:
    data = load("structure.json")["groups"][group]
    totals = data["gold_structures"]
    kinds = ["table", "code", "list", "heading"]
    head = " | ".join(f"{k} (n={totals[k]})" for k in kinds)
    lines = [f"| system | {head} |", "|---|" + "---|" * len(kinds)]
    for s in ORDER:
        if s not in data["survival"]:
            continue
        row = data["survival"][s]
        cells = []
        for k in kinds:
            st, tx = row[k]["structure_kept"], row[k]["text_kept"]
            cells.append(f"{st['rate']:.0%} / {tx['rate']:.0%}" if st["rate"] is not None else "-")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def token_table() -> str:
    t = load("tokens.json")
    lines = [
        "| system | median output tokens | median saving vs raw HTML | tokens per article token |",
        "|---|---|---|---|",
    ]
    for s in ORDER:
        if s not in t["systems"]:
            continue
        r = t["systems"][s]
        lines.append(
            f"| {s} | {r['median_output_tokens']:,.0f} | {r['median_saving_vs_html']:.1%} "
            f"| {r['median_tokens_per_article_token']:.2f} |"
        )
    return "\n".join(lines)


def comments_table() -> str:
    c = load("comments_convention.json")
    lines = [
        f"Pages whose truth contains user comments: {c['n_pages_with_comments_in_truth']}",
        "",
        "| system | F1, truth as published | F1, article only |",
        "|---|---|---|",
    ]
    for s in ORDER:
        if s in c["systems"]:
            r = c["systems"][s]
            lines.append(
                f"| {s} | {r['f1_truth_with_comments']:.3f} | {r['f1_article_only']:.3f} |"
            )
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    for title, fn in (
        ("F1 with 95% bootstrap CI", f1_table),
        ("WCEB per dataset", per_dataset_table),
        ("Paired differences", paired_table),
        ("Ablations", ablation_table),
        ("Structure kept / text kept (all pages)", structure_table),
        ("Tokens (cl100k_base)", token_table),
        ("Dragnet comment convention", comments_table),
    ):
        print(f"## {title}\n\n{fn()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
