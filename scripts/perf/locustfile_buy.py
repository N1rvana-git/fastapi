"""Locust scenario: 100+ buyers racing for a 5-unit listing.

Expected outcomes:
* 5 requests -> ``200`` (order created, stock reaches 0);
* the rest -> ``400 OUT_OF_STOCK``, which is a *correct business outcome* and is
  therefore counted as success, so the statistics stay readable;
* anything else (5xx, 409 lock contention, 429) is a real failure.

Run (from the repo root, ``PYTHONUTF8=1`` avoids a GBK pyproject read on
Chinese Windows):

    $env:PYTHONUTF8="1"
    $env:PERF_TOKENS=".perf/<run>/tokens.json"
    locust -f scripts/perf/locustfile_buy.py --headless -u 100 -r 150 -t 8s \
           --host http://127.0.0.1:8124 --csv .perf/<run>/buy --only-summary
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from locust import HttpUser, between, events, task

_TOKENS_PATH = Path(os.environ.get("PERF_TOKENS", ".perf/tokens.json"))
_DATA = json.loads(_TOKENS_PATH.read_text(encoding="utf-8"))
_BUYERS: list[str] = list(_DATA["buyers"])
_ITEM_ID: int = int(_DATA["item_id"])
_ITEMS: list[int] = list(_DATA.get("items") or [])

_BURST: dict[str, float | int | None] = {"first": None, "last": None, "count": 0}


@events.quitting.add_listener
def _report_burst(environment, **kwargs) -> None:  # noqa: ANN001
    first, last = _BURST["first"], _BURST["last"]
    count = int(_BURST["count"] or 0)
    if isinstance(first, float) and isinstance(last, float) and count:
        span = max(last - first, 1e-9)
        print(
            f"BURST count={count} span={span:.3f}s "
            f"throughput={count / span:.1f} req/s"
        )


class Buyer(HttpUser):
    # Keep each simulated buyer well under the 20/min per-user rate limit while
    # still producing a dense first wave.
    wait_time = between(4.0, 6.0)

    def on_start(self) -> None:
        # Never route load-test traffic through a system/corporate proxy:
        # `requests` otherwise picks up Windows proxy settings and every request
        # pays the proxy latency (or fails with 502) while the target is local.
        self.client.trust_env = False
        # One token per simulated user: no shared buyer, no idempotent replay.
        self.auth = _BUYERS.pop() if _BUYERS else _DATA["buyers"][0]
        self.headers = {"Authorization": f"Bearer {self.auth}"}
        # With --items == buyers each user races for its own listing, which
        # removes the single-row lock and measures raw API/DB throughput.
        self.item_id = _ITEMS.pop() if _ITEMS else _ITEM_ID
        self.purchased = False

    @task
    def buy(self) -> None:
        # Open the connection outside the measured purchase: on Windows each new
        # loopback connection costs ~20ms, which would otherwise be attributed
        # to the API. The warm-up request is reported separately.
        self.client.get("/health/live", name="warmup")
        started = time.perf_counter()
        with self.client.post(
            f"/items/{self.item_id}/buy",
            headers=self.headers,
            catch_response=True,
            name="POST /items/[id]/buy",
        ) as response:
            finished = time.perf_counter()
            _BURST["first"] = (
                started if _BURST["first"] is None else min(float(_BURST["first"]), started)
            )
            _BURST["last"] = (
                finished if _BURST["last"] is None else max(float(_BURST["last"]), finished)
            )
            _BURST["count"] = int(_BURST["count"] or 0) + 1
            self.purchased = True
            # One attempt per simulated user: keep the burst clean and bounded.
            self.wait_time = lambda: 3600
            if response.status_code == 200:
                response.success()
                return
            if response.status_code == 400:
                try:
                    code = response.json().get("error", {}).get("code")
                except ValueError:
                    code = None
                if code == "OUT_OF_STOCK":
                    response.success()
                    return
            response.failure(f"{response.status_code}: {response.text[:200]}")
