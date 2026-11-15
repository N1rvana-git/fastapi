"""Tool JSON-schema validation and intent-scoped tool exposure."""

from __future__ import annotations

import json

import pytest
from src.app.modules.chat.tools import (
    TOOL_SPECS,
    ToolContext,
    ToolDeps,
    execute_tool,
    openai_tools,
    validate_tool_arguments,
)


def _ctx() -> ToolContext:
    return ToolContext(
        deps=ToolDeps(
            settings=object(),  # type: ignore[arg-type]
            database=object(),
            embeddings=None,
            vision=None,
            dispatcher=None,
        ),
        user_id=1,
        thread_id="t",
        tool_call_id="c",
    )


def test_search_items_schema_supports_structured_filters() -> None:
    schema = TOOL_SPECS["search_items"].parameters
    properties = schema["properties"]
    assert {"query", "keyword", "category", "min_price", "max_price", "sort_by"} <= set(properties)
    assert properties["sort_by"]["enum"] == ["relevance", "price_asc", "price_desc", "newest"]
    assert schema["required"] == ["query"]


def test_validate_accepts_a_well_formed_query() -> None:
    assert (
        validate_tool_arguments(
            "search_items",
            {"query": "显示器", "category": "显示器", "max_price": 2000, "sort_by": "price_asc"},
        )
        == []
    )


def test_validate_rejects_unknown_missing_bad_type_and_range() -> None:
    issues = validate_tool_arguments(
        "search_items",
        {"query": 123, "max_price": -1, "sort_by": "cheapest", "bogus": True},
    )
    assert any("query must be string" in issue for issue in issues)
    assert any("max_price must be >= 0" in issue for issue in issues)
    assert any("sort_by must be one of" in issue for issue in issues)
    assert any("unexpected field: bogus" in issue for issue in issues)

    missing = validate_tool_arguments("create_order", {"item_id": 1})
    assert "missing required field: address" in missing


@pytest.mark.asyncio
async def test_execute_tool_returns_structured_invalid_arguments() -> None:
    result = await execute_tool("search_items", {"query": "x", "max_price": -5}, _ctx())
    payload = json.loads(result)
    assert payload["status"] == "error"
    assert payload["code"] == "INVALID_ARGUMENTS"
    assert payload["issues"]


def test_openai_tools_can_be_scoped_to_an_intent() -> None:
    names = {tool["function"]["name"] for tool in openai_tools(("search_items",))}
    assert names == {"search_items"}
    assert all(tool["function"]["name"] in TOOL_SPECS for tool in openai_tools())
