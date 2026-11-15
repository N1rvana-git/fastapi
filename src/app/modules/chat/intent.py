"""Cheap, deterministic intent routing.

A full LLM classifier would add latency and a second failure mode to every
turn.  E-commerce conversations have strong lexical signals, so a rule-based
router is both faster and testable; it decides which tool subset is even shown
to the main model, reducing prompt tokens and accidental tool calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Intent = Literal["chitchat", "policy_qa", "shopping_search", "order_action"]

INTENT_TOOLS: dict[str, tuple[str, ...]] = {
    # No tools: general chat should not burn tokens on schemas it cannot use.
    "chitchat": (),
    # Policy questions must not tempt the model into create_order/scrape.
    "policy_qa": ("search_platform_policy",),
    "shopping_search": ("search_items", "search_web_price"),
    "order_action": ("search_items", "create_order", "list_my_orders"),
}

_POLICY_WORDS = (
    "规则",
    "政策",
    "退换货",
    "退货流程",
    "怎么退",
    "运费",
    "防骗",
    "纠纷",
    "保障",
    "平台规定",
    "售后政策",
)
_ORDER_WORDS = (
    "下单",
    "购买",
    "我要买",
    "要买",
    "买这台",
    "买它",
    "买了",
    "订单",
    "退款",
    "投诉",
    "取消订单",
    "售后",
    "收货地址",
    "发货",
    "支付",
)
_SHOPPING_WORDS = (
    "预算",
    "推荐",
    "想买",
    "比价",
    "全网",
    "多少钱",
    "显示器",
    "相机",
    "手机",
    "电脑",
    "耳机",
    "键盘",
    "显卡",
    "笔记本",
    "有没有",
    "适合",
    "找",
    "买",
)


@dataclass(frozen=True)
class IntentDecision:
    intent: Intent
    confidence: float
    tools: tuple[str, ...]
    matched: str = ""


def classify_intent(message: str) -> IntentDecision:
    text = (message or "").strip().lower()
    if not text:
        return IntentDecision("chitchat", 0.2, INTENT_TOOLS["chitchat"], "empty")

    for word in _POLICY_WORDS:
        if word in text:
            return IntentDecision("policy_qa", 0.9, INTENT_TOOLS["policy_qa"], word)

    for word in _ORDER_WORDS:
        if word in text:
            return IntentDecision("order_action", 0.85, INTENT_TOOLS["order_action"], word)

    for word in _SHOPPING_WORDS:
        if word in text:
            return IntentDecision("shopping_search", 0.8, INTENT_TOOLS["shopping_search"], word)

    return IntentDecision("chitchat", 0.5, INTENT_TOOLS["chitchat"], "default")


__all__ = ["INTENT_TOOLS", "Intent", "IntentDecision", "classify_intent"]
