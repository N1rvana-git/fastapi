"""Seed data for the Route B load test.

Creates a fresh seller + N buyers + one low-stock listing, and writes JWTs to
``.perf/<run_id>/tokens.json`` so the load generator never needs to log in
(login/registration are rate-limited, and we are measuring the purchase path).

    $env:DATABASE_URL="postgresql+asyncpg://xjb:xjbpass@127.0.0.1:55432/xjbdb"
    python scripts/perf/seed_loadtest.py --buyers 120 --stock 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from pathlib import Path

# Allow `python scripts/perf/seed_loadtest.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.app.container import AppContainer
from src.app.core.config import get_settings
from src.app.core.security import TokenService, password_hasher
from src.app.modules.items.models import ItemModel
from src.app.modules.users.models import UserModel


def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


async def seed(
    buyers: int, stock: int, price: float, items: int, out_dir: Path
) -> dict[str, object]:
    settings = get_settings()
    container = AppContainer.create(settings)
    await container.startup()
    try:
        run_id = f"{_ts()}-{secrets.token_hex(2)}"
        hashed = password_hasher.hash("Password123")
        async with container.database.session() as session:
            seller = UserModel(
                email=f"perf.{run_id}.seller@example.com",
                username=f"perf-seller-{run_id}",
                age=18,
                hashed_password=hashed,
                role="user",
            )
            buyers_models = [
                UserModel(
                    email=f"perf.{run_id}.buyer.{index}@example.com",
                    username=f"perf-buyer-{run_id}-{index}",
                    age=18,
                    hashed_password=hashed,
                    role="user",
                )
                for index in range(buyers)
            ]
            session.add_all([seller, *buyers_models])
            await session.commit()
            await session.refresh(seller)

            listings = [
                ItemModel(
                    name=f"perf-item-{run_id}-{index}",
                    price=price,
                    is_offer=True,
                    inventory=stock,
                    owner_id=seller.id,
                )
                for index in range(max(1, items))
            ]
            session.add_all(listings)
            await session.commit()

            buyer_ids = [model.id for model in buyers_models]
            seller_id = seller.id
            item_ids = [listing.id for listing in listings]

        token_service = TokenService(settings)
        tokens = {
            "run_id": run_id,
            "base_url": "http://127.0.0.1:8124",
            "item_id": item_ids[0],
            "items": item_ids,
            "stock": stock,
            "price": price,
            "seller_token": token_service.create_access_token(seller_id),
            "buyers": [token_service.create_access_token(buyer_id) for buyer_id in buyer_ids],
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        tokens_path = out_dir / "tokens.json"
        tokens_path.write_text(json.dumps(tokens), encoding="utf-8")
        summary = {
            "run_id": run_id,
            "item_id": item_ids[0],
            "items": len(item_ids),
            "buyers": buyers,
            "stock": stock,
            "price": price,
            "tokens_file": str(tokens_path),
        }
        print(json.dumps(summary, ensure_ascii=False))
        return summary
    finally:
        await container.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed buyers/listing for the load test")
    parser.add_argument("--buyers", type=int, default=120)
    parser.add_argument("--stock", type=int, default=5)
    parser.add_argument("--price", type=float, default=100.0)
    parser.add_argument(
        "--items",
        type=int,
        default=1,
        help="number of listings (use buyers for no hot-row contention)",
    )
    parser.add_argument("--out", default=".perf")
    args = parser.parse_args()
    out_dir = Path(args.out) / _ts()
    asyncio.run(seed(args.buyers, args.stock, args.price, args.items, out_dir))


if __name__ == "__main__":
    main()
