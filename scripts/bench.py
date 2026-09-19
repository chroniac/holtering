"""Timings on a record: heavy pass, warm start, recompute after a label edit, API endpoints.

  bench.py <dir with raw.scp + qrs.txt> [--start "YYYY-MM-DD HH:MM:SS"] [--repeat N]

Prints a Markdown table; the numbers in README.md come from a 24-hour synthetic
record (`python tests/synth.py bench 86400`).
"""

import argparse
import platform
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import psutil
from litestar.testing import TestClient

from holtering.analysis import build
from holtering.api import create_app
from holtering.settings import Settings


def timed[T](fn: Callable[[], T], repeat: int) -> tuple[float, T]:
    """Median wall time in ms over `repeat` runs, plus the last result."""
    samples = []
    t0 = time.perf_counter()
    result = fn()
    samples.append((time.perf_counter() - t0) * 1000)
    for _ in range(repeat - 1):
        t0 = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return float(np.median(samples)), result


def rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1e6


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("data", type=Path)
    ap.add_argument("--start", default="2026-09-17 09:30:00")
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args(argv)

    cache = args.data / ".bench-cache"
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir()
    settings = Settings(
        record={
            "scp": args.data / "raw.scp",
            "qrs": args.data / "qrs.txt",
            "start": args.start,
            "cache_dir": cache,
        },
        api={"static_dir": None},
    )
    rows: list[tuple[str, str]] = []
    size_mb = settings.record.scp.stat().st_size / 1e6

    cold_ms, state = timed(lambda: build(settings.record), 1)
    rows.append(
        (
            "first start: parse + heavy pass + recompute (file in OS page cache)",
            f"{cold_ms / 1000:.1f} s",
        )
    )
    warm_ms, state = timed(lambda: build(settings.record), 1)
    rows.append(("next start: parse + cached heavy pass + recompute", f"{warm_ms:.0f} ms"))
    beats = len(state.t_ms)
    recompute_ms, _ = timed(state.recompute, args.repeat)
    rows.append(("recompute() after a label edit", f"{recompute_ms:.0f} ms"))

    client = TestClient(create_app(settings, state))
    endpoints = [
        ("GET /api/summary", "/api/summary", {}),
        ("GET /api/overview (24 h minute HR + noise map)", "/api/overview", {}),
        ("GET /api/episodes", "/api/episodes", {}),
        ("GET /api/beats?dur=10800 (3 h context strip)", "/api/beats", {"dur": 10800}),
        ("GET /api/ecg?dur=10 (12 leads)", "/api/ecg", {"start": 3600, "dur": 10}),
        ("GET /api/ecg?dur=120 (12 leads)", "/api/ecg", {"start": 3600, "dur": 120}),
        (
            "GET /api/raw?dur=3600 (one lead, int16)",
            "/api/raw",
            {"start": 3600, "dur": 3600, "lead": "II"},
        ),
        ("GET /api/templates", "/api/templates", {}),
        ("GET /api/report (protocol text + strips)", "/api/report", {}),
        ("GET /api/export (every beat)", "/api/export", {}),
    ]
    for label, path, params in endpoints:
        ms, response = timed(lambda p=path, q=params: client.get(p, params=q), args.repeat)
        size = len(response.content) / 1e3
        rows.append((label, f"{ms:.0f} ms, {size:.0f} kB"))
    k = int(beats // 2)
    ms, _ = timed(lambda: client.post(f"/api/annotations/{k}", json={"label": "V"}), args.repeat)
    rows.append(("POST /api/annotations/{index} (label edit + recompute)", f"{ms:.0f} ms"))
    client.post(f"/api/annotations/{k}", json={"label": None})
    rows.append(("process RSS after all of the above", f"{rss_mb():.0f} MB"))

    out = sys.stdout
    out.write(
        f"Record: {size_mb:.0f} MB (file just written, so it sits in the OS page cache), {state.total_ms / 3.6e6:.1f} h, {beats:,} beats, "
        f"{state.rec.n_leads} leads @ {state.fs} Hz. "
        f"{platform.python_implementation()} {platform.python_version()}, {platform.system()}.\n\n"
    )
    out.write("| Step | Result |\n|---|---|\n")
    for label, value in rows:
        out.write(f"| {label} | {value} |\n")
    shutil.rmtree(cache, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
