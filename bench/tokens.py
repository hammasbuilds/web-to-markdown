"""Token savings measured with a real tokenizer, and the built-in estimator's error.

Uses tiktoken's ``cl100k_base`` (``uv sync --group baselines``). The library's
zero-dependency :func:`web2md.tokens.estimate_tokens` is scored against it on the
same texts, so the README can say how far to trust the estimate.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any

from bench.datasets import Page
from bench.metrics import tokenize
from bench.runner import Output
from web2md.tokens import estimate_tokens


def _encoder():  # type: ignore[no-untyped-def]
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def token_report(pages: Sequence[Page], outputs: dict[str, dict[str, Output]]) -> dict[str, Any]:
    enc = _encoder()

    def n(text: str) -> int:
        return len(enc.encode(text, disallowed_special=()))

    html_tokens = {p.page_id: n(p.html) for p in pages}
    truth_tokens = {p.page_id: n(p.truth) for p in pages}
    systems: dict[str, Any] = {}
    for system, outs in outputs.items():
        out_tokens = [n(outs[p.page_id].markdown) for p in pages]
        savings = [
            1 - o / html_tokens[p.page_id]
            for o, p in zip(out_tokens, pages, strict=True)
            if html_tokens[p.page_id]
        ]
        overhead = [
            o / truth_tokens[p.page_id]
            for o, p in zip(out_tokens, pages, strict=True)
            if truth_tokens[p.page_id]
        ]
        systems[system] = {
            "median_output_tokens": statistics.median(out_tokens),
            "total_output_tokens": sum(out_tokens),
            "median_saving_vs_html": round(statistics.median(savings), 4),
            "median_tokens_per_article_token": round(statistics.median(overhead), 3),
        }
    # The estimator's constants were fitted on AEB's dev split; judge it elsewhere.
    unseen = [p for p in pages if not (p.dataset == "aeb" and p.split == "dev")]
    est_errors_html = _errors(unseen, html_tokens, lambda p: p.html)
    ours = outputs.get("web2md", {})
    est_errors_md = _errors(
        unseen,
        {p.page_id: n(ours[p.page_id].markdown) for p in unseen if p.page_id in ours},
        lambda p: ours[p.page_id].markdown,
    )
    return {
        "tokenizer": "tiktoken cl100k_base",
        "n_pages": len(pages),
        "median_html_tokens": statistics.median(html_tokens.values()),
        "median_article_tokens": statistics.median(truth_tokens.values()),
        "total_html_tokens": sum(html_tokens.values()),
        "systems": systems,
        "estimator": {
            "function": "web2md.tokens.estimate_tokens",
            "evaluated_on": "every page except the AEB dev split its constants were fitted on",
            "on_html": est_errors_html,
            "on_web2md_markdown": est_errors_md,
        },
        "article_words_per_token": round(
            sum(len(tokenize(p.truth)) for p in pages) / max(1, sum(truth_tokens.values())), 3
        ),
    }


def _errors(pages: Sequence[Page], exact: dict[str, int], text_of) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    rel = []
    for p in pages:
        truth = exact.get(p.page_id)
        if not truth:
            continue
        rel.append((estimate_tokens(text_of(p)) - truth) / truth)
    if not rel:
        return {}
    abs_rel = sorted(abs(x) for x in rel)
    return {
        "n": len(rel),
        "median_signed_error": round(statistics.median(rel), 4),
        "median_abs_error": round(statistics.median(abs_rel), 4),
        "p90_abs_error": round(abs_rel[int(0.9 * (len(abs_rel) - 1))], 4),
    }
