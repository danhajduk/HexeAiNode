#!/usr/bin/env python3
import math
import os
import sys


def _percent(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, 1.0), 100.0)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("command_required")
    allowed = sorted(os.sched_getaffinity(0))
    if not allowed:
        raise SystemExit("no_cpu_affinity_available")
    limit_percent = _percent("HEXE_COMFYUI_CPU_CORE_LIMIT_PERCENT", 50.0)
    core_count = max(1, math.ceil(len(allowed) * limit_percent / 100.0))
    selected = set(allowed[:core_count])
    os.sched_setaffinity(0, selected)
    threads = str(len(selected))
    os.environ.setdefault("OMP_NUM_THREADS", threads)
    os.environ.setdefault("MKL_NUM_THREADS", threads)
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
