"""Buyer memory extraction and compression rules."""

from __future__ import annotations

import pytest
from src.app.modules.chat.memory import (
    BuyerMemory,
    build_chat_context,
    compress_context,
    extract_buyer_memory,
    render_memory_slot,
)


def _messages(*texts: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text} for text in texts]


def test_extracts_budget_categories_address_and_rejections() -> None:
    memory = extract_buyer_memory(
        _messages(
            "我预算 2000 以内，想买一台打 CS2 的显示器",
            "不要 ID 5 和 6，太丑了",
            "地址：上海市浦东新区测试路 1 号",
        )
    )
    assert memory.budget_max == 2000
    assert memory.preferred_categories == ("显示器",)
    assert memory.shipping_address == "上海市浦东新区测试路 1 号"
    assert memory.rejected_item_ids == (5, 6)
    assert "预算上限约 2000 元" in memory.summary


def test_parses_chinese_amounts() -> None:
    assert extract_buyer_memory(_messages("预算两千左右")).budget_max == 2000
    assert extract_buyer_memory(_messages("一千五以内")).budget_max == 1500


def test_empty_memory_and_render() -> None:
    memory = extract_buyer_memory(_messages("你好"))
    assert memory.empty is True
    assert render_memory_slot(memory) == ""


def test_render_keeps_a_stable_suffix_slot() -> None:
    memory = BuyerMemory(
        budget_max=3000,
        preferred_categories=("相机",),
        shipping_address="北京市朝阳区测试路 2 号",
        rejected_item_ids=(9,),
        summary="预算上限约 3000 元",
    )
    rendered = render_memory_slot(memory)
    assert rendered.startswith("\n## 会话记忆")
    assert "预算上限：3000 元" in rendered
    assert "商品 ID：9" in rendered


def test_compress_context_moves_early_messages_into_memory() -> None:
    messages = _messages(
        "预算 5000",
        "我要买相机",
        "不要 ID 3",
        "地址：广州市天河区测试路 8 号",
        "最近在吗",
        "还在吗",
    )
    recent, memory = compress_context(messages, window=2)
    assert [item["content"] for item in recent] == ["最近在吗", "还在吗"]
    assert memory.budget_max == 5000
    assert memory.preferred_categories == ("相机",)
    assert memory.shipping_address == "广州市天河区测试路 8 号"
    assert memory.rejected_item_ids == (3,)


def test_compress_context_short_history_has_no_memory() -> None:
    recent, memory = compress_context(_messages("预算 100", "你好"), window=8)
    assert len(recent) == 2
    assert memory.empty


def test_build_chat_context_keeps_system_prefix_stable() -> None:
    context = build_chat_context(
        "STATIC PROMPT",
        _messages("预算 2000", "推荐显示器", "最近在吗"),
        window=1,
    )
    assert context[0]["role"] == "system"
    assert str(context[0]["content"]).startswith("STATIC PROMPT")
    assert "## 会话记忆" in str(context[0]["content"])
    assert context[-1]["content"] == "最近在吗"


def test_window_must_be_positive() -> None:
    with pytest.raises(ValueError, match="window must be >= 1"):
        compress_context([], window=0)
