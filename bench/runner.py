"""Run every system over every page once, caching outputs to ``data/runs/``.

Outputs are cached per (dataset, system) in JSON-lines files keyed by page id and
stamped with a *fingerprint*: the tool's version, plus a hash of web2md's source
for web2md's own variants. Editing the extractor invalidates exactly the cached
outputs it could have changed.
"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import Executor
from dataclasses import dataclass
from pathlib import Path

from bench.datasets import DATA, Page
from bench.extractors import System, systems

RUNS = DATA / "runs"
SRC = Path(__file__).resolve().parent.parent / "src" / "web2md"


# Modules that can change a conversion's output; the CLI and fetcher cannot.
OUTPUT_MODULES = ("convert.py", "dom.py", "extract.py", "markdown.py", "metadata.py", "tokens.py")


def source_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(SRC / name for name in OUTPUT_MODULES):
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:12]


def fingerprint(system: System) -> str:
    renders_with_web2md = system.name.startswith(
        ("web2md", "all-text", "largest-block", "readability-lxml")
    )
    extra = f"+src:{source_hash()}" if renders_with_web2md else ""
    return f"{system.name}@{system.version}{extra}"


@dataclass
class Output:
    page_id: str
    markdown: str
    seconds: float
    error: str = ""


_REGISTRY: dict[str, System] = {}


def _worker_run(args: tuple[str, str, str]) -> tuple[str, str, float, str]:
    system_name, page_id, html = args
    if not _REGISTRY:
        found, _ = systems()
        _REGISTRY.update({s.name: s for s in found})
    start = time.perf_counter()
    try:
        markdown = _REGISTRY[system_name].run(html)
        error = ""
    except Exception as exc:  # a crash is a result: an empty output, recorded
        markdown, error = "", f"{type(exc).__name__}: {exc}"[:300]
    return page_id, markdown, time.perf_counter() - start, error


def _cache_path(dataset: str, system: str) -> Path:
    return RUNS / dataset.replace("/", "__") / f"{system}.jsonl"


def load_cached(dataset: str, system: System) -> dict[str, Output]:
    path = _cache_path(dataset, system.name)
    if not path.exists():
        return {}
    fp = fingerprint(system)
    cached: dict[str, Output] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("fingerprint") == fp:
                cached[row["page_id"]] = Output(
                    row["page_id"], row["markdown"], row["seconds"], row.get("error", "")
                )
    return cached


def run_system(
    system: System, dataset: str, pages: list[Page], pool: Executor
) -> dict[str, Output]:
    cached = load_cached(dataset, system)
    todo = [p for p in pages if p.page_id not in cached]
    if todo:
        path = _cache_path(dataset, system.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        fp = fingerprint(system)
        mode = "a" if cached else "w"
        with path.open(mode, encoding="utf-8") as fh:
            jobs = ((system.name, p.page_id, p.html) for p in todo)
            for page_id, markdown, seconds, error in pool.map(_worker_run, jobs, chunksize=4):
                out = Output(page_id, markdown, seconds, error)
                cached[page_id] = out
                fh.write(json.dumps({"fingerprint": fp, **out.__dict__}, ensure_ascii=False))
                fh.write("\n")
    return cached
