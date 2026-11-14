"""Agent tool registry.

Every tool:

* opens its **own** short-lived database session (no request session is pinned
  for the duration of an LLM turn - the PDF's "法则 1");
* has an explicit Pydantic-style JSON schema so the model cannot invent
  parameters;
* returns compact text, truncated to keep the context window (and the token
  bill) bounded, instead of dumping whole RAG documents;
* raises ``ApprovalRequiredError`` out to the runtime when a human decision is
  needed, so the runtime can suspend the workflow instead of silently failing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.app.core.config import Settings
from src.app.core.exceptions import AppError, ApprovalRequiredError, FeatureUnavailableError
from src.app.modules.chat.scraper import ScraperUnavailable, search_market_price
from src.app.modules.items import service as items_service
from src.app.modules.knowledge import service as knowledge_service
from src.app.modules.orders import repository as orders_repository
from src.app.modules.orders import service as orders_service
from src.app.modules.users.models import UserModel

logger = logging.getLogger(__name__)

_MAX_TOOL_CHARS = 1600


@dataclass(frozen=True)
class ToolDeps:
    settings: Settings
    database: Any  # src.app.core.database.Database
    embeddings: Any
    vision: Any
    dispatcher: Any


@dataclass(frozen=True)
class ToolContext:
    deps: ToolDeps
    user_id: int
    thread_id: str
    tool_call_id: str


ToolHandler = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
async def _search_platform_products(ctx: ToolContext, query: str) -> str:
    async with ctx.deps.database.session() as session:
        hits, mode = await items_service.search_by_text(
            session,
            query,
            embeddings=ctx.deps.embeddings,
            vision=ctx.deps.vision,
            limit=5,
        )
        if not hits:
            return "平台当前没有匹配的在售商品。"
        lines = [
            f"ID:{item.id} | {item.name} | ￥{item.price:.2f} | 库存:{item.inventory} | 标签:"
            f"{','.join(tag.name for tag in item.tags) or '无'}"
            for item, _score in hits
        ]
        return _truncate(f"检索方式:{mode}\n平台在售商品：\n" + "\n".join(lines))


async def _search_platform_policy(ctx: ToolContext, query: str) -> str:
    async with ctx.deps.database.session() as session:
        docs, mode = await knowledge_service.search_policy(
            session, query, embeddings=ctx.deps.embeddings, limit=3
        )
        if not docs:
            return "知识库暂未收录相关规则，请建议用户联系人工客服。"
        snippets = [f"《{doc.title}》：{(doc.content or '')[:260]}" for doc in docs]
        return _truncate(f"检索方式:{mode}\n平台规则：\n" + "\n".join(snippets))


async def _search_web_price(ctx: ToolContext, item_name: str) -> str:
    try:
        data = await search_market_price(item_name)
    except ScraperUnavailable as exc:
        return f"全网比价不可用：{exc}。请建议用户参考平台内价格。"
    return _truncate(f"全网搜索结果（{item_name}）：{data}")


async def _list_my_orders(ctx: ToolContext) -> str:
    async with ctx.deps.database.session() as session:
        orders = await orders_repository.list_by_buyer(session, ctx.user_id, limit=5)
        if not orders:
            return "该用户还没有订单。"
        lines = [
            f"订单{order.id} | {order.item.name if order.item else '商品已下架'} | "
            f"￥{order.price or 0:.2f} x{order.quantity} | 状态:{order.status} | "
            f"{order.created_at.isoformat() if order.created_at else ''}"
            for order in orders
        ]
        return "最近订单：\n" + "\n".join(lines)


async def _create_order(
    ctx: ToolContext, item_id: int, address: str, quantity: int = 1, item_name: str = ""
) -> str:
    cleaned_address = (address or "").strip()
    if len(cleaned_address) < 5:
        return json.dumps(
            {"status": "need_address", "message": "请先向用户索取省市区街道的详细收货地址"},
            ensure_ascii=False,
        )
    async with ctx.deps.database.session() as session:
        buyer = await session.get(UserModel, ctx.user_id)
        if buyer is None:
            return json.dumps({"status": "error", "message": "用户不存在"}, ensure_ascii=False)
        try:
            result = await orders_service.purchase(
                session,
                item_id=int(item_id),
                buyer=buyer,
                settings=ctx.deps.settings,
                quantity=max(1, int(quantity)),
                address=cleaned_address,
                # Deterministic per tool call: agent retries cannot double-order.
                idempotency_key=f"tool:{ctx.thread_id}:{ctx.tool_call_id}",
                require_approval=True,
                dispatcher=ctx.deps.dispatcher,
            )
        except ApprovalRequiredError:
            raise
        except AppError as exc:
            return json.dumps(
                {
                    "status": "error",
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "success",
                "order_id": result.order.id,
                "item_name": result.item_name or item_name,
                "unit_price": result.unit_price,
                "quantity": result.quantity,
                "remaining_inventory": result.remaining_inventory,
                "message": "下单成功",
            },
            ensure_ascii=False,
        )


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
TOOL_SPECS: dict[str, ToolSpec] = {
    "search_platform_products": ToolSpec(
        name="search_platform_products",
        description=(
            "检索平台真实在售库存（支持语义搜索）。当用户询问有什么商品、想买某类商品、"
            "请求推荐时必须调用，禁止编造商品和价格。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "商品名称、特征或需求描述"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_search_platform_products,
    ),
    "search_platform_policy": ToolSpec(
        name="search_platform_policy",
        description=(
            "检索平台规则知识库。用户询问退换货、防骗、运费、纠纷、平台规则时必须调用此工具，"
            "不要用商品检索工具查规则。"
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "规则类问题"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_search_platform_policy,
    ),
    "search_web_price": ToolSpec(
        name="search_web_price",
        description=(
            "全网比价。仅当用户明确要求查看外部市场价、全网比价、别人卖多少钱时调用；"
            "其他场景严禁调用。"
        ),
        parameters={
            "type": "object",
            "properties": {"item_name": {"type": "string", "description": "要搜索的商品名"}},
            "required": ["item_name"],
            "additionalProperties": False,
        },
        handler=_search_web_price,
    ),
    "list_my_orders": ToolSpec(
        name="list_my_orders",
        description="查询当前用户最近的订单记录。",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_list_my_orders,
    ),
    "create_order": ToolSpec(
        name="create_order",
        description=(
            "为用户下单。必须在拿到商品 ID 和用户详细收货地址后调用；金额超过人工审核阈值时"
            "系统会挂起等待审批。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "item_id": {"type": "integer", "description": "商品 ID，必须来自库存检索结果"},
                "item_name": {"type": "string", "description": "商品名称"},
                "address": {"type": "string", "description": "详细收货地址"},
                "quantity": {"type": "integer", "minimum": 1, "maximum": 10, "default": 1},
            },
            "required": ["item_id", "address"],
            "additionalProperties": False,
        },
        handler=_create_order,
    ),
}


def openai_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in TOOL_SPECS.values()
    ]


async def execute_tool(name: str, arguments: dict[str, Any], ctx: ToolContext) -> str:
    spec = TOOL_SPECS.get(name)
    if spec is None:
        return json.dumps({"status": "error", "message": f"未知工具: {name}"}, ensure_ascii=False)
    try:
        return await spec.handler(ctx, **arguments)
    except ApprovalRequiredError:
        raise
    except FeatureUnavailableError as exc:
        return json.dumps({"status": "unavailable", "message": exc.message}, ensure_ascii=False)
    except TypeError as exc:  # model sent wrong/missing arguments
        logger.warning("tool %s rejected arguments %s: %s", name, arguments, exc)
        return json.dumps({"status": "error", "message": "工具参数不合法"}, ensure_ascii=False)
    except Exception as exc:
        logger.exception("tool %s failed", name)
        return json.dumps(
            {"status": "error", "message": f"工具执行失败: {exc}"}, ensure_ascii=False
        )


def _truncate(text: str) -> str:
    if len(text) <= _MAX_TOOL_CHARS:
        return text
    return text[:_MAX_TOOL_CHARS] + "…(内容已截断)"


__all__ = [
    "TOOL_SPECS",
    "ToolContext",
    "ToolDeps",
    "ToolSpec",
    "execute_tool",
    "openai_tools",
]
