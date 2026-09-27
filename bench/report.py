"""Score cached outputs and write every ``results/*.json`` file.

``python -m bench.report`` after ``python -m bench.run``; ``bench/run.py`` calls
both. Each function below produces one results file and nothing else.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from bench.datasets import Page
from bench.metrics import (
    Counts,
    bootstrap,
    corpus_score,
    page_counts,
    page_f1,
    paired_bootstrap_diff,
    tokenize,
)
from bench.runner import Output
from bench.structure import KINDS, Gold, gold_structures, regions, survives, text_present
from bench.textview import markdown_to_text

RESULTS = Path(__file__).resolve().parent.parent / "results"
OURS = "web2md"

Outputs = dict[str, dict[str, Output]]  # system -> page_id -> output


def _r(x: float) -> float:
    return round(x, 4)


def write(name: str, data: Any) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def groups(pages: Sequence[Page]) -> dict[str, list[Page]]:
    """Every slice results are reported on: each dataset, AEB's two splits, WCEB pooled."""
    out: dict[str, list[Page]] = defaultdict(list)
    for p in pages:
        out[p.dataset].append(p)
        if p.dataset == "aeb":
            out[f"aeb/{p.split}"].append(p)
        else:
            out["wceb (all)"].append(p)
    return dict(out)


def all_counts(
    pages: Sequence[Page], outputs: Outputs, view: Callable[[str], str] = markdown_to_text
) -> dict[str, dict[str, Counts]]:
    return {
        system: {p.page_id: page_counts(p.truth, view(outs[p.page_id].markdown)) for p in pages}
        for system, outs in outputs.items()
    }


def extraction_scores(
    pages: Sequence[Page], outputs: Outputs, counts: dict[str, dict[str, Counts]], n_boot: int
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for group, members in groups(pages).items():
        rows = {}
        for system in outputs:
            c = [counts[system][p.page_id] for p in members]
            score = corpus_score(c)
            ci = bootstrap(c, n_boot=n_boot)
            outs = [outputs[system][p.page_id] for p in members]
            rows[system] = {
                "precision": _r(score.precision),
                "recall": _r(score.recall),
                "f1": _r(score.f1),
                "f1_ci95": [_r(ci["f1"][0]), _r(ci["f1"][1])],
                "precision_ci95": [_r(ci["precision"][0]), _r(ci["precision"][1])],
                "recall_ci95": [_r(ci["recall"][0]), _r(ci["recall"][1])],
                "errors": sum(1 for o in outs if o.error),
                "empty_outputs": sum(1 for o in outs if not o.markdown.strip()),
                "ms_per_page": _r(1000 * statistics.mean(o.seconds for o in outs)),
            }
        result[group] = {"n_pages": len(members), "systems": rows}
    return result


def paired_diffs(
    pages: Sequence[Page], outputs: Outputs, counts: dict[str, dict[str, Counts]], n_boot: int
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for group, members in groups(pages).items():
        ours = [counts[OURS][p.page_id] for p in members]
        rows = {}
        for system in outputs:
            if system == OURS:
                continue
            other = [counts[system][p.page_id] for p in members]
            diff, lo, hi = paired_bootstrap_diff(ours, other, n_boot=n_boot)
            rows[system] = {
                "f1_diff": _r(diff),
                "ci95": [_r(lo), _r(hi)],
                "significant": lo > 0 or hi < 0,
            }
        result[group] = rows
    return result


def per_site(pages: Sequence[Page], counts: dict[str, dict[str, Counts]]) -> dict[str, Any]:
    by_site: dict[str, list[Page]] = defaultdict(list)
    for p in pages:
        if p.dataset == "aeb":
            by_site[p.site].append(p)
    systems_ = list(counts)
    sites = {}
    for site, members in sorted(by_site.items()):
        sites[site] = {
            "n_pages": len(members),
            "split": members[0].split,
            "f1": {
                s: _r(corpus_score([counts[s][p.page_id] for p in members]).f1) for s in systems_
            },
        }
    wins: dict[str, dict[str, int]] = {}
    for s in systems_:
        if s == OURS:
            continue
        better = sum(1 for v in sites.values() if v["f1"][OURS] > v["f1"][s] + 0.01)
        worse = sum(1 for v in sites.values() if v["f1"][OURS] < v["f1"][s] - 0.01)
        wins[s] = {
            "web2md_better": better,
            "web2md_worse": worse,
            "tied_within_0.01": len(sites) - better - worse,
        }
    worst = sorted(sites.items(), key=lambda kv: kv[1]["f1"][OURS])[:15]
    return {
        "n_sites": len(sites),
        "site_wins": wins,
        "web2md_worst_sites": dict(worst),
        "sites": sites,
    }


# -- structure -----------------------------------------------------------------


def structure_scores(
    pages: Sequence[Page], outputs: Outputs, markdown_systems: set[str], n_boot: int
) -> dict[str, Any]:
    golds: dict[str, list[Gold]] = {p.page_id: gold_structures(p.html, p.truth) for p in pages}
    by_dataset: dict[str, list[Page]] = defaultdict(list)
    for p in pages:
        by_dataset["aeb" if p.dataset == "aeb" else "wceb (all)"].append(p)
        by_dataset["all"].append(p)
    result: dict[str, Any] = {}
    for group, members in by_dataset.items():
        totals = {
            k: sum(1 for p in members for g in golds[p.page_id] if g.kind == k) for k in KINDS
        }
        pages_with = {
            k: sum(1 for p in members if any(g.kind == k for g in golds[p.page_id])) for k in KINDS
        }
        rows: dict[str, Any] = {}
        for system in outputs:
            if system not in markdown_systems:
                continue
            per_page: list[dict[str, tuple[int, int]]] = []
            per_page_text: list[dict[str, tuple[int, int]]] = []
            for p in members:
                markdown = outputs[system][p.page_id].markdown
                reg = regions(markdown)
                text = markdown_to_text(markdown)
                tokens = tokenize(text)
                tally: dict[str, tuple[int, int]] = {}
                tally_text: dict[str, tuple[int, int]] = {}
                for k in KINDS:
                    gs = [g for g in golds[p.page_id] if g.kind == k]
                    tally[k] = (sum(survives(g, reg) for g in gs), len(gs))
                    tally_text[k] = (sum(text_present(g, tokens, text) for g in gs), len(gs))
                per_page.append(tally)
                per_page_text.append(tally_text)
            rows[system] = {
                k: {
                    "structure_kept": _survival(per_page, k, n_boot),
                    "text_kept": _survival(per_page_text, k, n_boot),
                }
                for k in KINDS
            }
        result[group] = {
            "n_pages": len(members),
            "gold_structures": totals,
            "pages_with_structure": pages_with,
            "survival": rows,
        }
    return result


def _survival(per_page: list[dict[str, tuple[int, int]]], kind: str, n_boot: int) -> dict:
    import random

    pairs = [t[kind] for t in per_page if t[kind][1] > 0]
    kept = sum(a for a, _ in pairs)
    total = sum(b for _, b in pairs)
    if not total:
        return {"kept": 0, "total": 0, "rate": None, "ci95": None}
    rng = random.Random(0)
    draws = []
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        draws.append(sum(a for a, _ in sample) / max(1, sum(b for _, b in sample)))
    draws.sort()
    return {
        "kept": kept,
        "total": total,
        "rate": _r(kept / total),
        "ci95": [_r(draws[int(0.025 * n_boot)]), _r(draws[int(0.975 * n_boot) - 1])],
    }


# -- failures ------------------------------------------------------------------


def failure_category(counts: Counts, output: str) -> str:
    tp, fp, fn = counts
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    if not output.strip():
        return "empty output"
    if r < 0.1:
        return "wrong block (almost none of the article)"
    if p >= 0.8 and r < 0.8:
        return "under-extraction (article partly missing)"
    if r >= 0.8 and p < 0.8:
        return "over-extraction (boilerplate kept)"
    if p < 0.8 and r < 0.8:
        return "mixed (part of the article plus boilerplate)"
    return "ok"


def failures(
    pages: Sequence[Page],
    outputs: Outputs,
    counts: dict[str, dict[str, Counts]],
    compare: Sequence[str],
) -> dict[str, Any]:
    cats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in pages:
        c = counts[OURS][p.page_id]
        cat = failure_category(c, outputs[OURS][p.page_id].markdown)
        group = "aeb" if p.dataset == "aeb" else p.dataset
        cats[group][cat] += 1
        cats["all"][cat] += 1
        if cat != "ok" and len(examples[cat]) < 12:
            examples[cat].append(
                {"dataset": p.dataset, "page_id": p.page_id, "url": p.url, "f1": _r(page_f1(c))}
            )
    # Pages no extractor gets right, and what distinguishes them.
    present = [s for s in compare if s in counts]
    hard, rest = [], []
    for p in pages:
        best = max(page_f1(counts[s][p.page_id]) for s in present)
        (hard if best < 0.5 else rest).append(p)
    marked = sum(1 for p in hard if p.dataset == "wceb/dragnet" and _COMMENTS.search(p.truth))
    return {
        "thresholds": "precision/recall 0.8; wrong block = recall < 0.1",
        "categories": {g: dict(v) for g, v in cats.items()},
        "examples": dict(examples),
        "all_extractors_fail": {
            "definition": f"best page F1 among {present} below 0.5",
            "n_pages": len(hard),
            "with_user_comments_in_truth": marked,
            "by_dataset": _count_by(hard, lambda p: p.dataset),
            "features_hard": _page_features(hard),
            "features_rest": _page_features(rest),
            "examples": [
                {
                    "dataset": p.dataset,
                    "page_id": p.page_id,
                    "url": p.url,
                    "truth_tokens": len(tokenize(p.truth)),
                }
                for p in hard[:15]
            ],
        },
    }


def _count_by(pages: Sequence[Page], key: Callable[[Page], str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for p in pages:
        out[key(p)] += 1
    return dict(sorted(out.items()))


def _page_features(pages: Sequence[Page]) -> dict[str, Any]:
    if not pages:
        return {}
    from web2md.dom import parse

    truth_tokens, share, paras = [], [], []
    for p in pages:
        root = parse(p.html)
        for el in list(root.iter("script", "style", "noscript", "template")):
            el.remove()
        page_tokens = len(tokenize(root.text())) or 1
        t = len(tokenize(p.truth))
        truth_tokens.append(t)
        share.append(min(1.0, t / page_tokens))
        paras.append(sum(1 for el in root.iter("p") if len(el.text().strip()) >= 25))
    return {
        "n": len(pages),
        "median_truth_tokens": statistics.median(truth_tokens),
        "median_article_share_of_page_text": _r(statistics.median(share)),
        "median_paragraphs_ge_25_chars": statistics.median(paras),
        "share_with_no_p_paragraphs": _r(sum(1 for x in paras if x == 0) / len(pages)),
    }


# -- metadata ------------------------------------------------------------------


def _norm_url(url: str) -> str:
    url = url.strip().lower()
    url = re.sub(r"^https?://(www\.)?", "", url)
    url = url.split("#")[0]
    return url.rstrip("/")


def canonical_accuracy(pages: Sequence[Page]) -> dict[str, Any]:
    from web2md.dom import parse
    from web2md.metadata import extract_metadata

    aeb = [p for p in pages if p.dataset == "aeb" and p.url]
    exact = found = 0
    fields: dict[str, int] = defaultdict(int)
    misses = []
    for p in aeb:
        md = extract_metadata(parse(p.html))
        for key, value in md.as_dict().items():
            fields[key] += bool(value)
        if md.canonical_url:
            found += 1
            if _norm_url(md.canonical_url) == _norm_url(p.url):
                exact += 1
            elif len(misses) < 10:
                misses.append({"truth": p.url, "extracted": md.canonical_url})
    n = len(aeb)
    return {
        "n_pages": n,
        "canonical_found": found,
        "canonical_matches_benchmark_url": exact,
        "match_rate": _r(exact / n) if n else None,
        "comparison": "scheme, leading www., fragment and trailing slash ignored",
        "field_coverage": {k: {"found": v, "rate": _r(v / n)} for k, v in fields.items()},
        "mismatch_examples": misses,
    }


# -- ground-truth conventions ----------------------------------------------------

COMMENTS_MARKER = "!@#$%^&*()  COMMENTS"
# The marker was typed by hand: 21 of the 420 marked Dragnet files carry a variant.
_COMMENTS = re.compile(r"[!@#$%^&*() ]{6,}COMMENTS")


def comment_convention(
    pages: Sequence[Page], outputs: Outputs, systems_: Sequence[str], n_boot: int
) -> dict[str, Any]:
    """Dragnet's truth files mark where user comments begin; WCEB's conversion kept them.

    Rescore those pages against the article alone (truth cut at the marker) to see
    how much of every extractor's Dragnet "failure" is that labelling choice.
    """
    marked = [p for p in pages if p.dataset == "wceb/dragnet" and _COMMENTS.search(p.truth)]
    if not marked:
        return {"n_pages_with_comments_in_truth": 0}
    rows: dict[str, Any] = {}
    for system in systems_:
        as_is, article_only = [], []
        for p in marked:
            text = markdown_to_text(outputs[system][p.page_id].markdown)
            as_is.append(page_counts(p.truth, text))
            article_only.append(page_counts(_COMMENTS.split(p.truth)[0], text))
        s1, s2 = corpus_score(as_is), corpus_score(article_only)
        ci2 = bootstrap(article_only, n_boot=n_boot)["f1"]
        rows[system] = {
            "f1_truth_with_comments": _r(s1.f1),
            "recall_truth_with_comments": _r(s1.recall),
            "f1_article_only": _r(s2.f1),
            "f1_article_only_ci95": [_r(ci2[0]), _r(ci2[1])],
            "recall_article_only": _r(s2.recall),
        }
    return {
        "marker": COMMENTS_MARKER + " (and hand-typed variants)",
        "n_pages_with_comments_in_truth": len(marked),
        "by_dataset": _count_by(marked, lambda p: p.dataset),
        "systems": rows,
    }
