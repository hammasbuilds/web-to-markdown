"""Shingle precision/recall/F1, as defined by scrapinghub/article-extraction-benchmark.

The scoring rule is a re-implementation of that benchmark's ``evaluate.py`` so
numbers here are comparable with its published table: text is tokenised on
``\\w+``, cut into 4-token shingles, and true/false positives are counted over
shingle multisets. Each page's counts are normalised to sum to 1 so long pages
do not dominate, and corpus precision and recall are *means over pages*; corpus
F1 is the harmonic mean of those two means (not the mean of per-page F1).

``tests/test_metrics.py`` pins this against hand-computed cases, and
``bench/run.py --check-published`` reproduces the benchmark's own numbers from
its published extractor outputs.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

_TOKEN = re.compile(r"\w+", re.UNICODE)

Counts = tuple[float, float, float]  # normalised (tp, fp, fn) for one page


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def shingles(text: str, n: int = 4) -> Counter[tuple[str, ...]]:
    tokens = tokenize(text)
    grams = [tuple(tokens[i : i + n]) for i in range(max(1, len(tokens) - n + 1))]
    return Counter(g for g in grams if g)


def page_counts(truth: str, pred: str, n: int = 4) -> Counts:
    t, p = shingles(truth, n), shingles(pred, n)
    tp = fp = fn = 0.0
    for key in t.keys() | p.keys():
        tc, pc = t.get(key, 0), p.get(key, 0)
        tp += min(tc, pc)
        fp += max(0, pc - tc)
        fn += max(0, tc - pc)
    total = tp + fp + fn
    if total > 0:
        return tp / total, fp / total, fn / total
    return 0.0, 0.0, 0.0


def _precision(tp: float, fp: float, fn: float) -> float:
    if fp == fn == 0:
        return 1.0
    if tp == fp == 0:
        return 0.0
    return tp / (tp + fp)


def _recall(tp: float, fp: float, fn: float) -> float:
    if fp == fn == 0:
        return 1.0
    if tp == fn == 0:
        return 0.0
    return tp / (tp + fn)


def page_f1(counts: Counts) -> float:
    p, r = _precision(*counts), _recall(*counts)
    return 2 * p * r / (p + r) if p + r else 0.0


@dataclass(frozen=True)
class Score:
    precision: float
    recall: float
    f1: float


def corpus_score(counts: Sequence[Counts]) -> Score:
    precisions = [_precision(*c) for c in counts if c[0] + c[1] > 0]
    recalls = [_recall(*c) for c in counts if c[0] + c[2] > 0]
    p = sum(precisions) / len(precisions) if precisions else 0.0
    r = sum(recalls) / len(recalls) if recalls else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return Score(p, r, f1)


class _PerPage:
    """Per-page precision and recall, computed once so resampling is just summing."""

    def __init__(self, counts: Sequence[Counts]) -> None:
        # (value, counted) pairs: a page with no predicted shingles has no precision.
        self.p = [(_precision(*c), c[0] + c[1] > 0) for c in counts]
        self.r = [(_recall(*c), c[0] + c[2] > 0) for c in counts]

    def score(self, idx: Sequence[int]) -> Score:
        ps = [self.p[i][0] for i in idx if self.p[i][1]]
        rs = [self.r[i][0] for i in idx if self.r[i][1]]
        p = sum(ps) / len(ps) if ps else 0.0
        r = sum(rs) / len(rs) if rs else 0.0
        return Score(p, r, 2 * p * r / (p + r) if p + r else 0.0)


def bootstrap(
    counts: Sequence[Counts], n_boot: int = 1000, seed: int = 0, alpha: float = 0.05
) -> dict[str, tuple[float, float]]:
    """Percentile bootstrap CI over pages for precision, recall and F1."""
    rng = random.Random(seed)
    n = len(counts)
    draws: dict[str, list[float]] = {"precision": [], "recall": [], "f1": []}
    if n == 0:
        return {k: (0.0, 0.0) for k in draws}
    pages = _PerPage(counts)
    for _ in range(n_boot):
        s = pages.score([rng.randrange(n) for _ in range(n)])
        draws["precision"].append(s.precision)
        draws["recall"].append(s.recall)
        draws["f1"].append(s.f1)
    lo_i, hi_i = int(alpha / 2 * n_boot), int((1 - alpha / 2) * n_boot) - 1
    return {k: (sorted(v)[lo_i], sorted(v)[hi_i]) for k, v in draws.items()}


def paired_bootstrap_diff(
    a: Sequence[Counts], b: Sequence[Counts], n_boot: int = 1000, seed: int = 0
) -> tuple[float, float, float]:
    """F1(a) - F1(b) with a 95% CI, resampling the same pages for both."""
    if len(a) != len(b):
        raise ValueError("paired bootstrap needs the same pages for both systems")
    rng = random.Random(seed)
    n = len(a)
    point = corpus_score(a).f1 - corpus_score(b).f1
    pa, pb = _PerPage(a), _PerPage(b)
    diffs = []
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(pa.score(idx).f1 - pb.score(idx).f1)
    diffs.sort()
    return point, diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot) - 1]
