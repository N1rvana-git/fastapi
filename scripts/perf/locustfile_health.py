"""Minimal locust scenario for framework-only throughput.

    $env:PYTHONUTF8="1"
    locust -f scripts/perf/locustfile_health.py --headless -u 100 -r 200 -t 10s \
           --host http://127.0.0.1:8124 --only-summary
"""

from __future__ import annotations

from locust import HttpUser, between, task


class Health(HttpUser):
    wait_time = between(0.05, 0.15)

    def on_start(self) -> None:
        self.client.trust_env = False

    @task
    def health(self) -> None:
        self.client.get("/health/live", name="GET /health/live")
