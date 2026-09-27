# STATUS

**Status: READY-FOR-REVIEW** (self-score 97/100). No model arm: the core finding needs no model,
and the optional QA arm was skipped because no question set over these pages exists.

## Self-score

| Points | Criterion | Score | Reason |
|---:|---|---:|---|
| 15 | Works from a clean clone | 15 | Fresh `git clone` into a temp dir: `uv sync`, `uv run pytest -q` (102 passed, `WEB2MD_DATA` pointed at an empty dir), `uv run python demo.py` (all checks passed), `web2md --help`. Tests touch no network and no downloaded data. |
| 20 | Real data, real result | 20 | 181 AEB pages + 3,794 WCEB pages (7 public datasets), all numbers in `results/*.json` produced on this machine by `python -m bench.run`; metric port reproduces AEB's published F1 for three tools to within 0.0005. |
| 15 | Finding quality | 14 | Baselines (two home-grown, four third-party), five ablations, bootstrap CIs and paired bootstrap differences, site-based dev/held-out split, second benchmark fully held out, surprising numbers chased (63 empty L3S pages -> two parser bugs; Dragnet comment convention). Minus 1: structure labels are derived from plain-text truth, not annotated, and gold code blocks are few (231 on 32 pages). |
| 15 | Correctness | 14 | 102 tests including parser recovery, every markdown construct, fixture extraction, metric vs hand-computed cases, loaders on fixture trees. Minus 1: the 0.8 matching thresholds in the structure matcher are a judgement call, tested but not validated against human labels. |
| 10 | Usability | 10 | `web2md FILE|-|URL`, `--fetch` opt-in, `--json`, `--front-matter`, `--stats`, `--all`, clear errors for missing file, URL without `--fetch`, binary input, HTTP errors; warnings on empty/short output. |
| 10 | README | 10 | House skeleton, mermaid, claim blockquote, findings table at the top, four real Input/Output samples from `demo.py`, NOT-do list, ten real problems. |
| 10 | Code quality | 9 | ruff clean, typed, zero runtime deps, modules under ~600 lines. Minus 1: `extract.py` is the largest module and its cleaning rules are a list of heuristics rather than one principle. |
| 5 | Honesty | 5 | Every README number traceable via `python -m bench.summary` or a named results file; the non-transfer of the AEB lead, the clean stage hurting on WCEB, and the post-hoc parser fix are all stated; pre-fix scores kept in `results/history/`. |
| **100** | | **97** | |

## Done

- Library + CLI (`src/web2md/`): forgiving DOM on `html.parser`, extraction (prune, score,
  promote/merge, clean, fallback), GFM renderer (headings, nested lists, tables with colspan
  and layout-table detection, fenced code with language, links, images, blockquotes),
  metadata (OpenGraph, JSON-LD incl. `@graph`, microdata, canonical), token estimate,
  urllib fetch with charset handling.
- Benchmark (`bench/`): AEB + WCEB loaders, exact port of AEB's metric, eight systems + five
  ablations, structure survival (structure kept vs text kept), token savings with tiktoken,
  failure categories, all-extractors-fail analysis, Dragnet comment-convention rescoring,
  canonical-URL accuracy, alt-text sensitivity, per-site breakdown.
- `demo.py` over four hand-written example pages with known answers.

## Queued for a model run

Nothing. The optional arm (does cleaner markdown give better LLM answers?) needs a question set
over these HTML pages; none exists, so it was skipped rather than invented.

## Known weaknesses

- The extractor's lead on AEB does not hold on WCEB (tie with readability-lxml, +0.009 over
  trafilatura). The clean stage slightly hurts on WCEB (0.888 without it).
- Behind trafilatura on Google-Trends-2017 (0.799 vs 0.851).
- Structure labels are derived (text of a table/code/list/heading found in plain-text truth),
  so a table the annotators dropped is never counted.
- About twice trafilatura's run time per page (pure Python).
- `recipe-meta`-style classes remove useful short lines ("Serves 4") along with bylines.

## Reproduce

```bash
uv sync --group baselines
bash bench/fetch_data.sh                 # AEB (raw.githubusercontent) + WCEB (LFS, 48 range requests)
uv run python -m bench.run --workers 4   # all results/*.json except results/history/
uv run python -m bench.summary           # the README tables
uv run pytest -q && uv run ruff check . && uv run python demo.py
```

`results/history/extraction_before_parser_fix.json` is the extraction table from the run before
the `<noscript><body>` / broken-`<head>` parser fix (commit `dom: ignore nested html/head/body
tags ...`); it is kept for the README's before/after number and is not regenerated.
