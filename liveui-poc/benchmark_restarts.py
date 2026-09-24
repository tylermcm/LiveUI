"""Measure controller wall-clock shadow restart-to-READY latency."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Sequence

from shadow import generate_shadow
from shadow_poc import inspect_shadow_process, validate_shadow_provenance


POC_ROOT = Path(__file__).resolve().parent


def _summary(values: Sequence[float]) -> dict:
    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "min_ms": round(ordered[0], 2),
        "median_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[p95_index], 2),
        "max_ms": round(ordered[-1], 2),
    }


def benchmark(project_root: Path, *, runs: int = 20) -> dict:
    if runs < 1:
        raise ValueError("runs must be positive")
    full_restart = []
    generation = []
    process_ready = []
    in_process_ready = []

    for _ in range(runs):
        started = time.perf_counter()
        build = generate_shadow(project_root)
        snapshot = inspect_shadow_process(build.workspace)
        validate_shadow_provenance(snapshot)
        full_restart.append(round((time.perf_counter() - started) * 1000, 2))
        generation.append(build.generation_ms)
        process_ready.append(snapshot["process_ready_ms"])
        in_process_ready.append(snapshot["in_process_ready_ms"])

    return {
        "runs": runs,
        "first_observed_full_restart_ms": full_restart[0],
        "first_observed_process_ready_ms": process_ready[0],
        "full_regenerate_and_restart_to_ready": _summary(full_restart),
        "shadow_generation": _summary(generation),
        "controller_process_spawn_to_ready": _summary(process_ready),
        "target_internal_after_imports_to_snapshot": _summary(in_process_ready),
        "measurement_note": (
            "First observed is not a true cold OS boot; filesystem and DLL caches were not cleared"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=POC_ROOT / "multifile_demo")
    parser.add_argument("--runs", type=int, default=20)
    arguments = parser.parse_args()
    try:
        report = benchmark(arguments.project, runs=arguments.runs)
    except Exception as error:
        print(f"BENCHMARK FAIL: {type(error).__name__}: {error}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

