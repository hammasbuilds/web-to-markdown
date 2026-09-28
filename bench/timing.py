"""Time every system on one pinned CPU core, with repeats: ``results/timing.json``.

    uv run python -m bench.timing                  # 40 pages per dataset, 5 repeats

The run times recorded by ``bench.run`` come from four worker processes on a
machine that other jobs share, so they are noisy. Here one process is pinned to
one core; each repeat visits every page and, per page, every system in turn,
so slow drift in the machine's load hits all systems alike. A page's time is the
median over repeats; each system is summarised by the median and interquartile
range over pages. A fixed pure-Python loop is timed before every repeat, and its
spread is reported as a measure of how steady the core was.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import os
import platform
import statistics
import sys
import time
from collections.abc import Iterator
from typing import Any

from bench import report
from bench.datasets import Page, iter_wceb, load_aeb
from bench.extractors import System, systems

DEFAULT_SYSTEMS = (
    "web2md",
    "all-text",
    "largest-block",
    "trafilatura",
    "trafilatura-md",
    "readability-lxml",
    "html2text",
    "markdownify",
)


def pin_to_core(core: int) -> bool:
    """Restrict this process to one logical CPU. Returns whether it worked."""
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {core})
        return True
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        return bool(kernel32.SetProcessAffinityMask(kernel32.GetCurrentProcess(), 1 << core))
    return False


def sample(pages: Iterator[Page], per_dataset: int) -> list[Page]:
    """The ``per_dataset`` pages of each dataset with the smallest id hash: fixed, unbiased."""
    by: dict[str, list[tuple[str, Page]]] = {}
    for p in pages:
        key = hashlib.sha1(p.page_id.encode()).hexdigest()
        bucket = by.setdefault(p.dataset, [])
        bucket.append((key, p))
        bucket.sort(key=lambda kp: kp[0])
        del bucket[per_dataset:]
    return [p for name in sorted(by) for _, p in by[name]]


def calibrate(loops: int = 2_000_000) -> float:
    """Milliseconds for a fixed pure-Python loop: the core's speed right now."""
    start = time.perf_counter()
    total = 0
    for i in range(loops):
        total += i & 7
    return 1000 * (time.perf_counter() - start)


def quartiles(values: list[float]) -> dict[str, float]:
    q1, q2, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return {"median": round(q2, 1), "q1": round(q1, 1), "q3": round(q3, 1)}


def time_systems(
    pages: list[Page], chosen: list[System], repeats: int
) -> tuple[dict[str, dict[str, list[float]]], list[float]]:
    """Per system, per page id, the run time in ms of each repeat; and calibration times."""
    times: dict[str, dict[str, list[float]]] = {s.name: {} for s in chosen}
    for s in chosen:  # warm-up: imports, regex compilation, lazy tables
        s.run(pages[0].html)
    calib: list[float] = []
    for rep in range(repeats):
        gc.collect()
        calib.append(calibrate())
        for p in pages:
            for s in chosen:
                start = time.perf_counter()
                s.run(p.html)
                elapsed = 1000 * (time.perf_counter() - start)
                times[s.name].setdefault(p.page_id, []).append(elapsed)
        print(f"  repeat {rep + 1}/{repeats} done", file=sys.stderr, flush=True)
    calib.append(calibrate())
    return times, calib


def summarise(
    pages: list[Page], times: dict[str, dict[str, list[float]]]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, per_page in times.items():
        medians = {pid: statistics.median(v) for pid, v in per_page.items()}
        by_dataset: dict[str, list[float]] = {}
        for p in pages:
            by_dataset.setdefault(p.dataset, []).append(medians[p.page_id])
        spread = [
            (max(v) - min(v)) / statistics.median(v)
            for v in per_page.values()
            if statistics.median(v) > 0
        ]
        out[name] = {
            "ms_per_page": quartiles(list(medians.values())),
            "mean_ms_per_page": round(statistics.mean(medians.values()), 1),
            "max_ms_per_page": round(max(medians.values()), 1),
            "median_repeat_spread": round(statistics.median(spread), 3),
            "by_dataset_median_ms": {
                d: round(statistics.median(v), 1) for d, v in sorted(by_dataset.items())
            },
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--per-dataset", type=int, default=40, help="pages sampled per dataset")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--core", type=int, default=(os.cpu_count() or 1) - 1)
    ap.add_argument("--systems", nargs="+", default=list(DEFAULT_SYSTEMS))
    args = ap.parse_args(argv)

    pinned = pin_to_core(args.core)
    found, missing = systems(include_ablations=False)
    chosen = [s for s in found if s.name in args.systems]
    pages = sample(iter([*load_aeb(), *iter_wceb()]), args.per_dataset)
    print(
        f"{len(pages)} pages x {len(chosen)} systems x {args.repeats} repeats, "
        f"core {args.core} pinned={pinned}",
        file=sys.stderr,
    )
    started = time.time()
    times, calib = time_systems(pages, chosen, args.repeats)
    report.write(
        "timing.json",
        {
            "conditions": {
                "pinned_core": args.core if pinned else None,
                "logical_cpus": os.cpu_count(),
                "processor": platform.processor(),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "pages": len(pages),
                "pages_per_dataset": args.per_dataset,
                "repeats": args.repeats,
                "order": "per repeat: every page, every system in turn on that page",
                "page_time": "median over repeats",
                "wall_seconds": round(time.time() - started),
                "note": "a shared machine: other processes ran on other cores",
            },
            "calibration_ms": {
                "runs": [round(c, 1) for c in calib],
                "max_over_min": round(max(calib) / min(calib), 3),
            },
            "systems": {s.name: {"version": s.version, "note": s.note} for s in chosen},
            "unavailable": missing,
            "timing": summarise(pages, times),
        },
    )
    print(f"results written to {report.RESULTS / 'timing.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
