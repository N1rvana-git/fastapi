"""Intent routing and reflection hints are pure functions worth pinning down."""

from __future__ import annotations

import json

import pytest
from src.app.modules.chat.intent import INTENT_TOOLS, classify_intent
from src.app.modules.chat.reflection import inject_reflection, is_error_result


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("平台退换货政策是什么？", "policy_qa"),
        ("运费和防骗规则", "policy_qa"),
        ("帮我下单，地址是上海市浦东新区测试路 1 号", "order_action"),
        ("我的订单到哪了", "order_action"),
        ("预算 2000 想买打 CS2 的显示器", "shopping_search"),
        ("帮我全网比价相机", "shopping_search"),
        ("你好呀，今天心情不错", "chitchat"),
    ],
)
def test_intent_routing(query: str, intent: str) -> None:
    decision = classify_intent(query)
    assert decision.intent == intent
    assert decision.tools == INTENT_TOOLS[intent]


def test_policy_intent_never_exposes_order_tools() -> None:
    decision = classify_intent("退货政策怎么规定的")
    assert "create_order" not in decision.tools
    assert "search_web_price" not in decision.tools


def test_empty_message_is_chitchat() -> None:
    decision = classify_intent("  ")
    assert decision.intent == "chitchat"
    assert decision.tools == ()


def test_empty_search_gets_reflection_hint_once() -> None:
    result = json.dumps({"status": "empty", "results": []})
    augmented, attempt = inject_reflection(
        result, tool="search_items", arguments={"query": "显示器"}, attempt=0
    )
    payload = json.loads(augmented)
    assert attempt == 1
    assert "放宽价格上下限 20%" in payload["reflection_hint"]
    assert payload["reflection_attempt"] == 1

    exhausted, attempt2 = inject_reflection(
        augmented, tool="search_items", arguments={"query": "显示器"}, attempt=attempt
    )
    assert attempt2 == 2
    assert "已经自动重试过一次" in json.loads(exhausted)["reflection_hint"]


def test_invalid_arguments_reflection_includes_issues() -> None:
    result = json.dumps({"status": "error", "issues": ["missing address"]})
    augmented, attempt = inject_reflection(
        result, tool="search_items", arguments={"query": "x"}, attempt=0
    )
    payload = json.loads(augmented)
    assert attempt == 1
    assert "missing address" in payload["reflection_hint"]
    assert payload["reflection_arguments"] == {"query": "x"}


def test_non_search_and_successful_results_pass_through() -> None:
    success = json.dumps({"status": "ok", "results": [1]})
    assert inject_reflection(success, tool="search_items", arguments={}, attempt=0) == (
        success,
        0,
    )
    other = json.dumps({"status": "empty"})
    assert inject_reflection(other, tool="create_order", arguments={}, attempt=0) == (other, 0)
    assert inject_reflection("plain text", tool="search_items", arguments={}, attempt=0) == (
        "plain text",
        0,
    )


def test_is_error_result() -> None:
    assert is_error_result(json.dumps({"status": "error"})) is True
    assert is_error_result(json.dumps({"status": "unavailable"})) is True
    assert is_error_result(json.dumps({"status": "empty"})) is False
    assert is_error_result("not json") is False
