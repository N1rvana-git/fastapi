"""Hybrid retrieval against real SQLite rows (lexical leg + filters)."""

from __future__ import annotations

from typing import Any

import pytest
from src.app.modules.items import service as items_service
from src.app.modules.items.models import ItemModel, TagModel
from src.app.modules.knowledge import service as knowledge_service
from src.app.modules.knowledge.models import KnowledgeModel
from tests.conftest import create_listing


async def _tag(session: Any, item_ids: list[int], name: str) -> None:
    tag = TagModel(name=name)
    session.add(tag)
    for item_id in item_ids:
        item = await session.get(ItemModel, item_id)
        assert item is not None
        item.tags.append(tag)
    await session.commit()


@pytest.mark.asyncio
async def test_items_hybrid_search_filters_and_marks_lexical(
    client: Any, started_app: Any, auth_headers: dict[str, str]
) -> None:
    display = await create_listing(client, auth_headers, name="CS2 电竞显示器", price=1800)
    expensive = await create_listing(client, auth_headers, name="4K 专业显示器", price=5000)
    phone = await create_listing(client, auth_headers, name="旗舰手机", price=3000)

    container = started_app.state.container
    async with container.database.session() as session:
        await _tag(session, [display["id"], expensive["id"]], "显示器")

        hits, mode = await items_service.search_by_text_hybrid(
            session,
            "显示器",
            embeddings=None,
            vision=None,
            limit=5,
            category="显示器",
            max_price=2000,
        )
        assert mode == "lexical"
        assert [hit.item.id for hit in hits] == [display["id"]]
        assert hits[0].match_reason == "lexical"
        assert hits[0].score > 0

        unfiltered, _ = await items_service.search_by_text_hybrid(
            session, "显示器", embeddings=None, vision=None, limit=5
        )
        assert {hit.item.id for hit in unfiltered} == {display["id"], expensive["id"]}
        assert phone["id"] not in {hit.item.id for hit in unfiltered}


@pytest.mark.asyncio
async def test_knowledge_hybrid_search_uses_lexical_leg(started_app: Any) -> None:
    container = started_app.state.container
    async with container.database.session() as session:
        session.add_all(
            [
                KnowledgeModel(title="退换货政策", content="七天无理由退换货，需保持商品完好。"),
                KnowledgeModel(title="运费说明", content="满 99 元包邮。"),
            ]
        )
        await session.commit()

        hits, mode = await knowledge_service.search_policy_hybrid(
            session, "退换货", embeddings=None, limit=3
        )
        assert mode == "lexical"
        assert hits
        assert hits[0].item.title == "退换货政策"
        assert hits[0].match_reason == "lexical"

        empty, empty_mode = await knowledge_service.search_policy_hybrid(
            session, "  ", embeddings=None
        )
        assert empty == [] and empty_mode == "empty"
