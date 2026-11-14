"""Summarize ``http_request`` records from the JSON access log.

    python scripts/perf/analyze_log.py .perf/logs/api.out.log --filter /buy
"""

from __future__ import annotations

import argparse
import json
import pathlib


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100) * len(ordered) + 0.5)) - 1))
    return ordered[index]


def _read_text(path: pathlib.Path) -> str:
    """PowerShell's ``>`` writes UTF-16LE on Windows; our own handlers write UTF-8."""

    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze JSON access logs")
    parser.add_argument("log", help="api.out.log")
    parser.add_argument("--filter", default="/buy", help="path substring filter")
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for line in _read_text(pathlib.Path(args.log)).splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("event") != "http_request":
            continue
        if args.filter not in str(item.get("path", "")):
            continue
        rows.append(item)

    durations = [float(row.get("duration_ms", 0) or 0) for row in rows]
    statuses: dict[int, int] = {}
    for row in rows:
        code = int(row.get("status_code", 0) or 0)
        statuses[code] = statuses.get(code, 0) + 1

    print(f"requests={len(rows)} statuses={statuses}")
    if durations:
        print(
            "server duration ms "
            f"p50={_percentile(durations, 50):.1f} "
            f"p95={_percentile(durations, 95):.1f} "
            f"p99={_percentile(durations, 99):.1f} "
            f"max={max(durations):.1f}"
        )
    for row in rows[-5:]:
        print(
            row.get("ts"),
            row.get("status_code"),
            row.get("duration_ms"),
            row.get("path"),
        )


if __name__ == "__main__":
    main()
