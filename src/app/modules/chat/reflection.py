"""Structured reflection hints for empty/failed tool calls.

The agent must be able to correct itself without the runtime hard-coding a
second query.  Instead of a generic error string, the tool observation carries a
machine-readable ``reflection_hint`` plus an attempt counter; the model can then
adjust the price range or use a broader keyword, while the runtime caps retries
at one to avoid loops.
"""

from __future__ import annotations

import json
from typing import Any

MAX_REFLECTION_ATTEMPTS = 1
SEARCH_TOOLS = {"search_items", "search_platform_policy"}


def parse_payload(result: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def is_error_result(result: str) -> bool:
    payload = parse_payload(result)
    if payload is None:
        return False
    return payload.get("status") in {"error", "unavailable"}


def inject_reflection(
    result: str,
    *,
    tool: str,
    arguments: dict[str, Any],
    attempt: int,
) -> tuple[str, int]:
    """Attach a reflection hint to an empty/error search observation.

    Returns ``(possibly_augmented_result, new_attempt_count)``.  Non-search tools
    and successful results pass through untouched.
    """

    payload = parse_payload(result)
    if payload is None:
        return result, attempt

    status = str(payload.get("status", ""))
    # Empty search results only make sense for retrieval tools; argument errors
    # can happen on any tool (e.g. create_order without an address).
    if status == "empty" and tool not in SEARCH_TOOLS:
        return result, attempt
    if status not in {"empty", "error"}:
        return result, attempt

    if attempt >= MAX_REFLECTION_ATTEMPTS:
        hint = (
            f"{tool} 已经自动重试过一次仍无结果。不要再重复调用；"
            "请如实告知用户暂时没有匹配项，并建议放宽预算、换个关键词或联系人工客服。"
        )
    elif status == "empty":
        hint = (
            "当前价格区间与关键词组合无结果，请尝试放宽价格上下限 20% 或使用上位词"
            f"重新调用 {tool}，最多重试 1 次。"
        )
    else:
        issues = payload.get("issues") or []
        detail = f"（{'；'.join(str(issue) for issue in issues)}）" if issues else ""
        hint = (
            f"{tool} 参数校验失败{detail}。请修正参数类型/必填字段后重新调用，"
            "最多重试 1 次；仍失败则向用户说明并给出替代方案。"
        )

    payload["reflection_hint"] = hint
    payload["reflection_attempt"] = attempt + 1
    payload["reflection_arguments"] = arguments
    return json.dumps(payload, ensure_ascii=False), attempt + 1


__all__ = [
    "MAX_REFLECTION_ATTEMPTS",
    "SEARCH_TOOLS",
    "inject_reflection",
    "is_error_result",
    "parse_payload",
]
