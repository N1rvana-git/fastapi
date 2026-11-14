"""Real PostgreSQL checkpointer: dedicated pool + persistence across instances.

Skipped unless ``POSTGRES_RAW_DSN`` is exported, e.g.

    $env:POSTGRES_RAW_DSN = "postgresql://xjb:xjbpass@127.0.0.1:55432/xjbdb"
    pytest tests/integration/test_langgraph_pg.py

This is the PDF's "dual-pool physical isolation" requirement: the checkpointer
never borrows the SQLAlchemy business pool.
"""

from __future__ import annotations

import os
from typing import TypedDict

import pytest
from src.app.core.compat import ensure_event_loop_policy

ensure_event_loop_policy()

pytest.importorskip("langgraph")
pytest.importorskip("psycopg_pool")

from langgraph.graph import END, START, StateGraph  # noqa: E402
from src.app.modules.chat.checkpointer import build_checkpointer  # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.getenv("POSTGRES_RAW_DSN"),
    reason="set POSTGRES_RAW_DSN to a PostgreSQL DSN to run the real checkpointer test",
)


class CounterState(TypedDict, total=False):
    value: int


def _counter_graph(saver: object):
    async def increment(state: CounterState) -> CounterState:
        return {"value": int(state.get("value", 0)) + 1}

    builder = StateGraph(CounterState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile(checkpointer=saver)


@pytest.mark.asyncio
async def test_checkpoint_survives_runtime_instances(settings) -> None:
    dsn = os.environ["POSTGRES_RAW_DSN"]
    configured = settings.model_copy(
        update={"POSTGRES_RAW_DSN": dsn, "CHECKPOINTER_POOL_MIN": 1, "CHECKPOINTER_POOL_MAX": 4}
    )
    first = await build_checkpointer(configured)
    second = None
    try:
        assert first.backend == "postgres"
        assert first.pool is not None

        graph = _counter_graph(first.saver)
        config = {"configurable": {"thread_id": "pg-checkpointer-test"}}
        await graph.ainvoke({"value": 1}, config=config)
        state = await graph.aget_state(config)
        assert state.values["value"] == 2

        # A second handle (separate pool, separate process-like instance) must
        # see the same checkpoint: state lives in PostgreSQL, not in memory.
        second = await build_checkpointer(configured)
        graph2 = _counter_graph(second.saver)
        restored = await graph2.aget_state(config)
        assert restored.values["value"] == 2
    finally:
        await first.aclose()
        if second is not None:
            await second.aclose()
