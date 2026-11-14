"""Latency decomposition for the load test.

Separates framework, database and storage costs so the report can explain the
numbers instead of guessing:

1. raw PostgreSQL ``INSERT + COMMIT`` (fsync cost of the local Docker volume);
2. API latency for a dependency-free endpoint and a DB read;
3. a single authenticated ``/buy`` request.

    python scripts/perf/diagnose_latency.py --tokens .perf/<run>/tokens.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402
import httpx  # noqa: E402

from src.app.core.config import get_settings  # noqa: E402


def _dsn() -> str:
    # psycopg/asyncpg DSN without the SQLAlchemy driver suffix.
    return get_settings().DATABASE_URL.replace("postgresql+asyncpg", "postgresql")


async def raw_commit_latency(rounds: int = 5) -> list[float]:
    connection = await asyncpg.connect(_dsn())
    samples: list[float] = []
    try:
        for _ in range(rounds):
            started = time.perf_counter()
            async with connection.transaction():
                await connection.execute(
                    "INSERT INTO tags (name) VALUES ($1)", f"perf-tag-{time.time_ns()}"
                )
            samples.append((time.perf_counter() - started) * 1000)
    finally:
        await connection.close()
    return samples


async def api_latency(tokens_path: Path, rounds: int) -> None:
    data = json.loads(tokens_path.read_text(encoding="utf-8"))
    base_url = str(data["base_url"])
    item_id = int(data["item_id"])
    token = str(data["buyers"][0])

    async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
        for path in ("/health/live", "/items"):
            samples: list[float] = []
            status = 0
            for _ in range(rounds):
                started = time.perf_counter()
                response = await client.get(f"{base_url}{path}")
                samples.append((time.perf_counter() - started) * 1000)
                status = response.status_code
            samples.sort()
            print(
                f"API {path:<15} status={status} "
                f"p50={samples[len(samples) // 2]:7.1f} ms max={samples[-1]:7.1f} ms"
            )

        buy_samples: list[float] = []
        for _ in range(min(rounds, 5)):
            started = time.perf_counter()
            response = await client.post(
                f"{base_url}/items/{item_id}/buy",
                headers={"Authorization": f"Bearer {token}"},
            )
            buy_samples.append((time.perf_counter() - started) * 1000)
        buy_samples.sort()
        print(
            f"API /items/{item_id}/buy  status={response.status_code} "
            f"p50={buy_samples[len(buy_samples) // 2]:7.1f} ms max={buy_samples[-1]:7.1f} ms"
        )


async def raw_query_latency(rounds: int = 10) -> None:
    connection = await asyncpg.connect(_dsn())
    try:
        for sql in ("SELECT 1", "SELECT id FROM item ORDER BY id DESC LIMIT 20"):
            samples: list[float] = []
            for _ in range(rounds):
                started = time.perf_counter()
                await connection.fetch(sql)
                samples.append((time.perf_counter() - started) * 1000)
            samples.sort()
            print(f"asyncpg {sql[:32]:<32} p50={samples[len(samples)//2]:7.1f} ms")
    finally:
        await connection.close()


async def orm_query_latency(rounds: int = 10) -> None:
    from src.app.core.database import Database, import_all_models
    from src.app.modules.items import repository

    import_all_models()
    database = Database(get_settings())
    try:
        async with database.session() as session:
            samples = []
            for _ in range(rounds):
                started = time.perf_counter()
                await repository.list_items(session, skip=0, limit=20)
                samples.append((time.perf_counter() - started) * 1000)
            samples.sort()
            print(f"SQLAlchemy list_items              p50={samples[len(samples)//2]:7.1f} ms")
    finally:
        await database.dispose()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Latency decomposition")
    parser.add_argument("--tokens", required=True, help="tokens.json from seed_loadtest.py")
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()

    commits = await raw_commit_latency()
    print("PG INSERT+COMMIT ms:", [round(value, 1) for value in commits])
    await raw_query_latency()
    await orm_query_latency()
    await api_latency(Path(args.tokens), args.rounds)


if __name__ == "__main__":
    asyncio.run(main())
