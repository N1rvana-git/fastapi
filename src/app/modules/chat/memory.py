"""Buyer session memory and rolling context compression.

The old runtime truncated history to the last N messages, so a budget or an
address mentioned ten turns ago silently disappeared.  This module extracts a
small, stable ``BuyerMemory`` from the *early* part of a conversation and renders
it into a fixed slot at the end of the system prompt; the static prompt prefix
stays untouched so provider prefix caching still works.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

MAX_MEMORY_CHARS = 600

_CATEGORY_WORDS = (
    "显示器",
    "相机",
    "手机",
    "电脑",
    "笔记本",
    "耳机",
    "键盘",
    "显卡",
    "平板",
    "手表",
    "主机",
)

_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}

_BUDGET_PATTERNS = (
    re.compile(r"预算(?:是|为|在|大概|约)?\s*([0-9]+(?:\.[0-9]+)?)\s*(万)?"),
    re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(?:元|块|rmb|以内|左右)"),
    re.compile(r"预算(?:是|为|在|大概|约)?\s*([零一二两三四五六七八九十百千万]+)"),
    re.compile(r"([零一二两三四五六七八九十百千万]+)\s*(?:元|块)\s*(?:以内|左右)?"),
    re.compile(r"([零一二两三四五六七八九十百千万]+)\s*(?:以内|左右)"),
)
_ADDRESS_PATTERN = re.compile(r"(?:地址|送到|寄到|收货地址)[：:\s]*([^，。；;\n]{5,80})")
_REJECT_PATTERN = re.compile(
    r"(?:不要|不想要|排除|不感冒)\s*(?:ID|id|#)?\s*"
    r"([0-9]+(?:\s*(?:和|、|,|，|及|/)\s*(?:ID|id|#)?\s*[0-9]+)*)"
)


def _parse_chinese_amount(text: str) -> float | None:
    # Colloquial trailing digit: "一千五" == 1500, "两千五" == 2500.
    match = re.fullmatch(r"([一二两三四五六七八九])?([千百])([一二三四五六七八九])", text)
    if match:
        lead = _DIGITS.get(match.group(1) or "一", 1)
        unit = _UNITS[match.group(2)]
        return float(lead * unit + _DIGITS[match.group(3)] * (unit // 10))

    section = 0
    number = 0
    seen = False
    for char in text:
        if char in _DIGITS:
            number = _DIGITS[char]
            seen = True
        elif char in _UNITS:
            unit = _UNITS[char]
            if unit == 10000:
                section = (section + number) * unit
            else:
                section += (number or 1) * unit
            number = 0
            seen = True
        else:
            return None
    return float(section + number) if seen else None


def _extract_budget(text: str) -> float | None:
    candidates: list[float] = []
    for index, pattern in enumerate(_BUDGET_PATTERNS):
        for match in pattern.finditer(text):
            raw = match.group(1)
            if index in (0, 1):
                value = float(raw)
                if match.lastindex and match.lastindex >= 2 and match.group(2) == "万":
                    value *= 10000
            else:
                parsed = _parse_chinese_amount(raw)
                if parsed is None:
                    continue
                value = parsed
            candidates.append(value)
    return max(candidates) if candidates else None


def _extract_address(text: str) -> str | None:
    match = _ADDRESS_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    if ("省" in text or "市" in text) and ("路" in text or "号" in text):
        return text.strip()
    return None


@dataclass(frozen=True)
class BuyerMemory:
    budget_max: float | None = None
    preferred_categories: tuple[str, ...] = ()
    shipping_address: str | None = None
    rejected_item_ids: tuple[int, ...] = ()
    summary: str = ""
    source_messages: int = 0
    details: dict[str, str] = field(default_factory=dict, compare=False)

    @property
    def empty(self) -> bool:
        return not (
            self.budget_max
            or self.preferred_categories
            or self.shipping_address
            or self.rejected_item_ids
            or self.summary
        )


def extract_buyer_memory(messages: Sequence[Mapping[str, object]]) -> BuyerMemory:
    """Rule-based extraction from early chat records (no extra LLM call)."""

    contents: list[str] = []
    for message in messages:
        if message.get("role") not in {"user", "assistant"}:
            continue
        content = str(message.get("content") or "").strip()
        if content:
            contents.append(content)

    text = "\n".join(contents)
    budget = _extract_budget(text)
    categories = tuple(word for word in _CATEGORY_WORDS if word in text)
    address = _extract_address(text)
    rejected = tuple(
        sorted(
            {
                int(value)
                for match in _REJECT_PATTERN.finditer(text)
                for value in re.findall(r"\d+", match.group(1))
            }
        )
    )

    summary_parts: list[str] = []
    if budget:
        summary_parts.append(f"预算上限约 {budget:.0f} 元")
    if categories:
        summary_parts.append("关注类目：" + "、".join(categories))
    if address:
        summary_parts.append(f"收货地址：{address}")
    if rejected:
        summary_parts.append("已排除商品 ID：" + "、".join(str(value) for value in rejected))
    summary = "；".join(summary_parts)[:MAX_MEMORY_CHARS]

    return BuyerMemory(
        budget_max=budget,
        preferred_categories=categories,
        shipping_address=address,
        rejected_item_ids=rejected,
        summary=summary,
        source_messages=len(contents),
    )


def render_memory_slot(memory: BuyerMemory) -> str:
    """Stable suffix appended to the system prompt (never before it)."""

    if memory.empty:
        return ""
    lines = ["", "## 会话记忆（早期对话提炼，供参考，不要逐字复述）"]
    if memory.budget_max:
        lines.append(f"- 预算上限：{memory.budget_max:.0f} 元（推荐时不得超预算）")
    if memory.preferred_categories:
        lines.append("- 偏好类目：" + "、".join(memory.preferred_categories))
    if memory.shipping_address:
        lines.append(f"- 已知收货地址：{memory.shipping_address}（下单前仍需用户确认）")
    if memory.rejected_item_ids:
        lines.append(
            "- 用户明确拒绝的商品 ID："
            + "、".join(str(value) for value in memory.rejected_item_ids)
        )
    if memory.summary:
        lines.append(f"- 历史摘要：{memory.summary}")
    return "\n".join(lines)


def compress_context(
    messages: Sequence[Mapping[str, object]],
    *,
    window: int,
) -> tuple[list[dict[str, Any]], BuyerMemory]:
    """Split into early (compressed to memory) and recent (kept verbatim)."""

    if window < 1:
        raise ValueError("window must be >= 1")
    normalized = [
        {"role": str(message.get("role") or "user"), "content": str(message.get("content") or "")}
        for message in messages
        if message.get("content")
    ]
    if len(normalized) <= window:
        return normalized, BuyerMemory(source_messages=len(normalized))
    early = normalized[:-window]
    recent = normalized[-window:]
    memory = extract_buyer_memory(early)
    return recent, memory


def build_chat_context(
    system_prompt: str,
    messages: Sequence[Mapping[str, object]],
    *,
    window: int,
) -> list[dict[str, Any]]:
    """Return ``[system, ...recent]`` with memory appended to the system slot."""

    recent, memory = compress_context(messages, window=window)
    system = system_prompt + render_memory_slot(memory)
    return [{"role": "system", "content": system}, *recent]


__all__ = [
    "BuyerMemory",
    "build_chat_context",
    "compress_context",
    "extract_buyer_memory",
    "render_memory_slot",
]
