"""Open N concurrent SSE streams and measure time-to-first-token + completion.

Locust is excellent for short request/response load, but SSE is a long-lived
stream; this harness starts every request from a common barrier and records:

* HTTP status / error events / number of token frames;
* time-to-first-token (TTFT) and total stream duration;
* the observed maximum number of simultaneously open streams.

    $env:PERF_TOKENS=".perf/<run>/tokens.json"
    python scripts/perf/sse_load.py --streams 50
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100) * len(ordered) + 0.5)) - 1))
    return ordered[index]


def _max_concurrency(intervals: list[tuple[float, float]]) -> int:
    points: list[tuple[float, int]] = []
    for start, end in intervals:
        points.append((start, 1))
        points.append((end, -1))
    points.sort(key=lambda item: (item[0], -item[1]))
    running = peak = 0
    for _ts, delta in points:
        running += delta
        peak = max(peak, running)
    return peak


async def _stream(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    token: str,
    run_id: str,
    index: int,
    barrier: asyncio.Event,
    results: list[dict[str, object]],
) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Idempotency-Key": f"perf-{run_id}-sse-{index}",
        "X-Thread-ID": f"perf-{run_id}-sse-{index}",
    }
    await barrier.wait()
    started = time.perf_counter()
    first_token: float | None = None
    tokens = 0
    error: str | None = None
    status = 0
    try:
        async with client.stream(
            "POST",
            f"{base_url}/items/ai/agent/stream",
            json={"message": "你好，推荐一台相机"},
            headers=headers,
            timeout=httpx.Timeout(60.0, connect=10.0),
        ) as response:
            status = response.status_code
            if status != 200:
                error = f"HTTP {status}"
            else:
                async for line in response.aiter_lines():
                    if line.startswith("event: token"):
                        tokens += 1
                        if first_token is None:
                            first_token = time.perf_counter() - started
                    elif line.startswith("event: error"):
                        error = "event:error"
                    elif line.startswith("event: done"):
                        break
    except Exception as exc:  # noqa: BLE001 - recorded as a failed stream
        error = f"{type(exc).__name__}: {exc}"
    finished = time.perf_counter()
    results.append(
        {
            "index": index,
            "status": status,
            "tokens": tokens,
            "ttft": first_token if first_token is not None else 0.0,
            "duration": finished - started,
            "error": error,
            "started": started,
            "finished": finished,
        }
    )


async def run(streams: int, tokens_path: Path, output: Path | None) -> dict[str, object]:
    data = json.loads(tokens_path.read_text(encoding="utf-8"))
    base_url = str(data["base_url"])
    buyers = list(data["buyers"])[:streams]
    if len(buyers) < streams:
        raise SystemExit(f"need {streams} buyer tokens, found {len(buyers)}")

    run_id = str(data["run_id"])
    barrier = asyncio.Event()
    results: list[dict[str, object]] = []
    limits = httpx.Limits(max_connections=streams + 10, max_keepalive_connections=streams)
    # trust_env=False: Windows registry proxy settings must not intercept a
    # localhost load test (it would add seconds of latency or return 502).
    async with httpx.AsyncClient(limits=limits, timeout=120.0, trust_env=False) as client:
        # Warm the pool first: opening dozens of loopback connections on Windows
        # costs ~20ms each, which is unrelated to SSE handling.
        await asyncio.gather(
            *[
                client.get(f"{base_url}/health/live") for _ in range(streams)
            ]
        )
        tasks = [
            asyncio.create_task(
                _stream(
                    client,
                    base_url=base_url,
                    token=buyers[index],
                    run_id=run_id,
                    index=index,
                    barrier=barrier,
                    results=results,
                )
            )
            for index in range(streams)
        ]
        await asyncio.sleep(0.2)
        wall_start = time.perf_counter()
        barrier.set()
        await asyncio.gather(*tasks)
        wall_end = time.perf_counter()

    ok = [item for item in results if item["error"] is None and int(item["status"]) == 200]
    ttfts = [float(item["ttft"]) for item in ok if float(item["ttft"]) > 0]
    durations = [float(item["duration"]) for item in ok]
    intervals = [(float(item["started"]), float(item["finished"])) for item in results]
    summary = {
        "run_id": run_id,
        "streams_requested": streams,
        "streams_ok": len(ok),
        "streams_failed": len(results) - len(ok),
        "errors": sorted({str(item["error"]) for item in results if item["error"]}),
        "tokens_total": sum(int(item["tokens"]) for item in ok),
        "ttft_ms": {
            "p50": round(_percentile(ttfts, 50) * 1000, 1),
            "p95": round(_percentile(ttfts, 95) * 1000, 1),
            "p99": round(_percentile(ttfts, 99) * 1000, 1),
            "max": round(max(ttfts) * 1000, 1) if ttfts else 0.0,
        },
        "duration_ms": {
            "p50": round(_percentile(durations, 50) * 1000, 1),
            "p95": round(_percentile(durations, 95) * 1000, 1),
            "p99": round(_percentile(durations, 99) * 1000, 1),
        },
        "max_observed_concurrency": _max_concurrency(intervals),
        "wall_seconds": round(wall_end - wall_start, 3),
        "streams_per_second": round(streams / max(wall_end - wall_start, 1e-9), 2),
        "duration_stdev_ms": round(statistics.pstdev(durations) * 1000, 1) if durations else 0.0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"summary": summary, "streams": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent SSE load harness")
    parser.add_argument("--streams", type=int, default=50)
    parser.add_argument(
        "--tokens", default=None, help="tokens.json path (default: newest under .perf)"
    )
    parser.add_argument("--out", default=None, help="result JSON path")
    args = parser.parse_args()

    tokens_path = (
        Path(args.tokens)
        if args.tokens
        else max(Path(".perf").glob("*/tokens.json"), key=lambda path: path.stat().st_mtime)
    )
    output = Path(args.out) if args.out else tokens_path.parent / "sse_results.json"
    asyncio.run(run(args.streams, tokens_path, output))


if __name__ == "__main__":
    main()
