"""Isolate where concurrency time goes: framework vs DB read vs purchase.

    python scripts/perf/concurrency_probe.py --tokens .perf/<run>/tokens.json --n 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx


async def _probe(client: httpx.AsyncClient, base: str, method: str, path: str, token: str | None) -> float:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    started = time.perf_counter()
    if method == "GET":
        await client.get(f"{base}{path}", headers=headers)
    else:
        await client.post(f"{base}{path}", headers=headers)
    return (time.perf_counter() - started) * 1000


async def _round(name: str, base: str, n: int, method: str, path: str, tokens: list[str] | None) -> None:
    limits = httpx.Limits(max_connections=n + 10, max_keepalive_connections=n)
    async with httpx.AsyncClient(limits=limits, timeout=120.0, trust_env=False) as client:
        # Warm up the connection pool: on Windows, opening 100 simultaneous
        # loopback connections costs ~20ms each (also measurable against a stdlib
        # http.server), which would otherwise dominate the measurement.
        await asyncio.gather(
            *[_probe(client, base, "GET", "/health/live", None) for _ in range(n)]
        )
        started = time.perf_counter()
        samples = await asyncio.gather(
            *[
                _probe(client, base, method, path, tokens[i] if tokens else None)
                for i in range(n)
            ]
        )
        wall = (time.perf_counter() - started) * 1000
    ordered = sorted(samples)
    print(
        f"{name:<18} n={n} wall={wall:7.0f}ms "
        f"p50={ordered[len(ordered)//2]:7.0f}ms "
        f"p95={ordered[int(len(ordered)*0.95)]:7.0f}ms "
        f"max={ordered[-1]:7.0f}ms"
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokens", required=True)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument(
        "--only",
        choices=["health", "items", "buy"],
        default=None,
        help="run a single probe instead of the whole suite",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="issue requests one after another on a single keep-alive connection",
    )
    parser.add_argument(
        "--raw-url",
        default=None,
        help="probe an arbitrary URL (used to compare against a non-uvicorn server)",
    )
    args = parser.parse_args()

    if args.raw_url:
        await _round("raw-url", "", args.n, "GET", args.raw_url, None)
        return

    data = json.loads(Path(args.tokens).read_text(encoding="utf-8"))
    base = str(data["base_url"])
    buyers = list(data["buyers"])
    items = list(data.get("items") or [data["item_id"]])

    if args.sequential:
        async with httpx.AsyncClient(trust_env=False, timeout=60.0) as client:
            samples = []
            for _ in range(args.n):
                started = time.perf_counter()
                await client.get(f"{base}/health/live")
                samples.append((time.perf_counter() - started) * 1000)
        samples.sort()
        print(
            f"{'health/seq':<18} n={args.n} "
            f"p50={samples[len(samples)//2]:7.1f}ms max={samples[-1]:7.1f}ms"
        )
        return

    if args.only in (None, "health"):
        await _round("health/live", base, args.n, "GET", "/health/live", None)
    if args.only in (None, "items"):
        await _round("items(list)", base, args.n, "GET", "/items", None)
    if args.only == "health":
        return
    if len(items) >= args.n:
        concurrency_paths = [f"/items/{item}/buy" for item in items[: args.n]]
        async with httpx.AsyncClient(
            limits=httpx.Limits(max_connections=args.n + 10), timeout=120.0, trust_env=False
        ) as client:
            await asyncio.gather(
                *[
                    _probe(client, base, "GET", "/health/live", None)
                    for _ in range(args.n)
                ]
            )
            started = time.perf_counter()
            samples = await asyncio.gather(
                *[
                    _probe(client, base, "POST", concurrency_paths[i], buyers[i])
                    for i in range(args.n)
                ]
            )
            wall = (time.perf_counter() - started) * 1000
        ordered = sorted(samples)
        print(
            f"{'buy(distinct)':<18} n={args.n} wall={wall:7.0f}ms "
            f"p50={ordered[len(ordered)//2]:7.0f}ms "
            f"p95={ordered[int(len(ordered)*0.95)]:7.0f}ms "
            f"max={ordered[-1]:7.0f}ms"
        )
    else:
        print("not enough items for a distinct-item purchase probe")


if __name__ == "__main__":
    asyncio.run(main())
