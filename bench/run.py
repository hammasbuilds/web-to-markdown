"""Reproduce every number in the README.

    uv sync --group baselines
    bash bench/fetch_data.sh            # ~57 MB, once
    uv run python -m bench.run          # all datasets, all systems

``--datasets aeb`` runs the 181-page benchmark only (about two minutes);
``--limit`` caps pages per dataset for a smoke test (results are then not
written unless ``--out`` points elsewhere).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from bench import report
from bench.datasets import DATA, Page, load_aeb, load_wceb
from bench.extractors import systems
from bench.metrics import bootstrap, corpus_score, page_counts
from bench.runner import run_system, source_hash
from bench.textview import markdown_to_text


def metric_check(pages: list[Page]) -> dict:
    """Score the benchmark's own published outputs with bench.metrics.

    If this port of the scoring rule is right, the F1 values match the table in
    scrapinghub/article-extraction-benchmark's README.
    """
    published = {"trafilatura": 0.958, "readability": 0.922, "html-text": 0.665}
    base = DATA / "aeb" / "published"
    truth = {p.page_id: p.truth for p in pages if p.dataset == "aeb"}
    rows = {}
    for name, expected in published.items():
        path = base / f"{name}.json"
        if not path.exists():
            rows[name] = {"status": f"missing {path.name}; run bench/fetch_data.sh"}
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data.get("output", data)
        counts = [
            page_counts(t, (data.get(pid) or {}).get("articleBody") or "")
            for pid, t in truth.items()
        ]
        score = corpus_score(counts)
        ci = bootstrap(counts, n_boot=200)
        rows[name] = {
            "published_f1": expected,
            "our_f1": round(score.f1, 4),
            "abs_diff": round(abs(score.f1 - expected), 4),
            "f1_ci95": [round(ci["f1"][0], 4), round(ci["f1"][1], 4)],
        }
    return {
        "purpose": "reproduce the benchmark's published F1 from its published outputs",
        "results": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--datasets", nargs="+", default=["aeb", "wceb"], choices=["aeb", "wceb"])
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--limit", type=int, help="pages per dataset (smoke test)")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=report.RESULTS)
    args = ap.parse_args(argv)
    if args.limit and args.out == report.RESULTS:
        print("--limit results are partial; pass --out to write them elsewhere", file=sys.stderr)
        return 2
    report.RESULTS = args.out

    pages: list[Page] = []
    if "aeb" in args.datasets:
        pages += load_aeb()[: args.limit]
    if "wceb" in args.datasets:
        wceb = load_wceb()
        if args.limit:
            by: dict[str, list[Page]] = {}
            for p in wceb:
                by.setdefault(p.dataset, []).append(p)
            wceb = [p for ps in by.values() for p in ps[: args.limit]]
        pages += wceb
    found, missing = systems()
    for name, why in missing.items():
        print(f"unavailable: {name} ({why})", file=sys.stderr)
    print(
        f"{len(pages)} pages, {len(found)} systems, web2md source {source_hash()}", file=sys.stderr
    )

    outputs: report.Outputs = {s.name: {} for s in found}
    with ProcessPoolExecutor(args.workers) as pool:  # one pool: worker start-up is slow
        for dataset in sorted({p.dataset for p in pages}):
            subset = [p for p in pages if p.dataset == dataset]
            for s in found:
                t = time.time()
                outputs[s.name].update(run_system(s, dataset, subset, pool))
                print(f"  {dataset:28s} {s.name:26s} {time.time() - t:6.1f}s", file=sys.stderr)

    markdown_systems = {s.name for s in found if s.markdown}
    counts = report.all_counts(pages, outputs)
    headline = [s for s in outputs if not s.startswith("web2md[")]
    ablations = [s for s in outputs if s.startswith("web2md")]

    def only(names: list[str]) -> report.Outputs:
        return {k: v for k, v in outputs.items() if k in names}

    report.write(
        "extraction.json",
        {
            "metric": "shingle (4-gram) P/R/F1 as in scrapinghub/article-extraction-benchmark",
            "scoring_view": "images dropped, link targets and fence info removed "
            "(bench/textview.py)",
            "systems": {s.name: {"version": s.version, "note": s.note} for s in found},
            "unavailable": missing,
            "groups": report.extraction_scores(pages, only(headline), counts, args.n_boot),
        },
    )
    report.write(
        "ablations.json",
        {
            "note": "each row switches one web2md stage off; see ExtractOptions",
            "groups": report.extraction_scores(pages, only(ablations), counts, args.n_boot),
        },
    )
    report.write(
        "paired_diffs.json",
        {
            "note": "F1(web2md) - F1(system), paired bootstrap over the same pages, 95% CI",
            "groups": report.paired_diffs(pages, outputs, counts, args.n_boot),
        },
    )
    report.write("per_site.json", report.per_site(pages, only(headline + ["web2md"])))
    report.write(
        "structure.json",
        {
            "definition": "bench/structure.py",
            "groups": report.structure_scores(pages, only(headline), markdown_systems, args.n_boot),
        },
    )
    report.write(
        "failures.json",
        report.failures(pages, outputs, counts, ["web2md", "trafilatura", "readability-lxml"]),
    )
    alt_counts = report.all_counts(
        pages,
        only(["web2md", "trafilatura-md"]),
        view=lambda md: markdown_to_text(md.replace("![", "[")),
    )
    report.write(
        "sensitivity.json",
        {
            "question": "what if image alt text were scored as article text?",
            "groups": report.extraction_scores(
                pages, only(["web2md", "trafilatura-md"]), alt_counts, 200
            ),
        },
    )
    report.write("metadata.json", report.canonical_accuracy(pages))
    if "aeb" in args.datasets:
        report.write("metric_check.json", metric_check(pages))
    try:
        from bench.tokens import token_report

        report.write("tokens.json", token_report(pages, only(headline)))
    except ImportError as exc:
        print(f"tokens.json skipped: {exc}", file=sys.stderr)
    print(f"results written to {report.RESULTS}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
