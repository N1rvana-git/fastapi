"""Item endpoints.

Everything static (``/tags``, ``/dashboard``, ``/upload-image`` ...) is declared
before ``/{item_id}`` so FastAPI cannot shadow it.  Write endpoints are thin:
validate -> call a service -> shape the response (< 20 lines each, as the
quality gate requires).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, UploadFile, status
from starlette.responses import Response

from src.app.core.exceptions import FeatureUnavailableError
from src.app.core.idempotency import IdempotencyGuard, stable_key
from src.app.core.pagination import PageParams, pagination_params
from src.app.modules.items import service as items_service
from src.app.modules.items.schemas import (
    AnalyzeUploadResponse,
    FavoriteToggleResponse,
    ImageSearchResponse,
    ImageUploadResponse,
    ItemCreate,
    ItemListResponse,
    ItemRead,
    ItemSearchHit,
    ItemUpdate,
    TagCreate,
    TagRead,
    TextSearchRequest,
)
from src.app.modules.orders import service as orders_service
from src.app.shared.deps import (
    AdminUser,
    CurrentUser,
    SessionDep,
    idempotency_guard,
    rate_limit,
    replay_response,
)

router = APIRouter(prefix="/items", tags=["items"])

create_item_idempotency = idempotency_guard("items.create", include_body=True)
buy_item_idempotency = idempotency_guard("items.buy", include_body=False)


# --------------------------------------------------------------------------- #
# Collection
# --------------------------------------------------------------------------- #
@router.post(
    "",
    response_model=ItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a listing",
)
@router.post(
    "/", response_model=ItemRead, status_code=status.HTTP_201_CREATED, include_in_schema=False
)
async def create_new_item(
    request: Request,
    payload: ItemCreate,
    session: SessionDep,
    user: CurrentUser,
    guard: IdempotencyGuard = Depends(create_item_idempotency),
) -> ItemRead | Response:
    replayed = replay_response(guard)
    if replayed is not None:
        return replayed
    item = await items_service.create_item(
        session,
        payload,
        owner_id=user.id,
        dispatcher=request.app.state.container.dispatcher,
    )
    body = ItemRead.model_validate(item)
    await guard.remember(body.model_dump(mode="json"), status_code=status.HTTP_201_CREATED)
    return body


@router.get("", response_model=ItemListResponse, summary="List listings")
@router.get("/", response_model=ItemListResponse, include_in_schema=False)
async def read_items(
    session: SessionDep,
    params: PageParams = Depends(pagination_params),
    search: str | None = None,
    is_offer_filter: bool | None = None,
) -> ItemListResponse:
    items, total = await items_service.list_items(
        session,
        skip=params.skip,
        limit=params.limit,
        search=search,
        is_offer=is_offer_filter,
    )
    return ItemListResponse(
        total=total,
        items=[ItemRead.model_validate(item) for item in items],
        skip=params.skip,
        limit=params.limit,
    )


# --------------------------------------------------------------------------- #
# Static paths (must stay above /{item_id})
# --------------------------------------------------------------------------- #
@router.get("/dashboard/me", summary="Aggregated dashboard for the current user")
async def get_my_dashboard(session: SessionDep, user: CurrentUser) -> dict[str, object]:
    from src.app.modules.items import repository as items_repository

    my_items = await items_repository.list_for_owner(session, user.id)
    my_orders = await orders_service.list_my_orders(session, user)
    return {
        "user_email": user.email,
        "stats": {
            "published_count": len(my_items),
            "orders_count": len(my_orders),
            "favourites_count": sum(len(item.favourited_by) for item in my_items),
        },
        "my_items": [
            {"id": item.id, "name": item.name, "price": item.price, "is_sold": item.is_sold}
            for item in my_items
        ],
        "my_orders": [
            {
                "order_id": order.id,
                "item_name": order.item.name if order.item else "商品已下架",
                "price": order.price
                if order.price is not None
                else (order.item.price if order.item else 0),
                "quantity": order.quantity,
                "status": order.status,
                "time": order.created_at.isoformat() if order.created_at else None,
            }
            for order in my_orders
        ],
    }


@router.get("/admin/secret-base", summary="Admin-only demo endpoint")
async def get_secret_base(admin: AdminUser) -> dict[str, str]:
    return {
        "message": f"欢迎管理员 {admin.email}",
        "action": "你可以管理任意用户的商品",
    }


@router.post(
    "/upload-image",
    response_model=ImageUploadResponse,
    summary="Upload an item image",
)
async def upload_image(
    request: Request,
    file: UploadFile,
    user: CurrentUser,
    _: None = Depends(rate_limit("upload", limit=30, window_seconds=60)),
) -> ImageUploadResponse:
    container = request.app.state.container
    stored = await container.storage.save(file, prefix="items")
    embedding = None
    try:
        embedding = await container.vision.image_embedding(await _read_all(file))
    except FeatureUnavailableError:
        embedding = None
    return ImageUploadResponse(
        filename=stored.filename,
        url=stored.url,
        image_embedding=embedding,
        message="图片上传成功" + ("，特征提取完成" if embedding else "（视觉特征提取不可用）"),
    )


@router.post(
    "/search-by-image",
    response_model=ImageSearchResponse,
    summary="Search listings by image",
)
async def search_items_by_image(
    request: Request,
    session: SessionDep,
    file: UploadFile,
    _: None = Depends(rate_limit("search-image", limit=20, window_seconds=60)),
) -> ImageSearchResponse:
    container = request.app.state.container
    hits, mode = await items_service.search_by_image(
        session, await _read_all(file), vision=container.vision, limit=5
    )
    return ImageSearchResponse(
        message="检索成功",
        data=[_hit(item, score) for item, score in hits],
        mode=mode,
    )


@router.post(
    "/search-by-text",
    response_model=ImageSearchResponse,
    summary="Search listings by description",
)
async def search_items_by_text(
    request: Request,
    session: SessionDep,
    payload: TextSearchRequest,
    _: None = Depends(rate_limit("search-text", limit=30, window_seconds=60)),
) -> ImageSearchResponse:
    container = request.app.state.container
    hits, mode = await items_service.search_by_text(
        session,
        payload.query_text,
        embeddings=container.embeddings,
        vision=container.vision,
        limit=5,
    )
    return ImageSearchResponse(
        message=f"为您找到与 '{payload.query_text}' 相关的商品",
        data=[_hit(item, score) for item, score in hits],
        mode=mode,
    )


@router.post(
    "/analyze-upload",
    response_model=AnalyzeUploadResponse,
    summary="Suggest tags before publishing",
)
async def analyze_uploaded_image(
    request: Request,
    file: UploadFile,
    user: CurrentUser,
    _: None = Depends(rate_limit("analyze", limit=20, window_seconds=60)),
) -> AnalyzeUploadResponse:
    container = request.app.state.container
    candidates = [
        "手机",
        "电脑",
        "衣服",
        "鞋子",
        "化妆品",
        "包包",
        "书籍",
        "数码配件",
        "生活用品",
        "虚拟物品",
    ]
    data = await _read_all(file)
    stored = await container.storage.save(file, prefix="analyze")
    try:
        tags = await container.vision.predict_tags(data, candidates)
    except FeatureUnavailableError:
        tags = []
    title = f"二手{tags[0]}，成色不错，价格好商量！" if tags else ""
    return AnalyzeUploadResponse(
        message="图片分析完成" if tags else "视觉识别不可用，已保存图片，可手动填写标签",
        image_url=stored.url,
        suggested_tags=tags,
        suggested_title=title,
    )


# --------------------------------------------------------------------------- #
# Tags
# --------------------------------------------------------------------------- #
@router.get("/tags", response_model=list[TagRead], summary="List tags (cached)")
@router.get("/tags/", response_model=list[TagRead], include_in_schema=False)
async def read_tags(request: Request, session: SessionDep) -> list[TagRead]:
    cached = await items_service.list_tags(session, cache=request.app.state.container.cache)
    return [TagRead(**tag) for tag in cached]


@router.post(
    "/tags",
    response_model=TagRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tag",
)
@router.post(
    "/tags/", response_model=TagRead, status_code=status.HTTP_201_CREATED, include_in_schema=False
)
async def create_tag_endpoint(
    request: Request, payload: TagCreate, session: SessionDep, _user: CurrentUser
) -> TagRead:
    tag = await items_service.create_tag(
        session, payload.name, cache=request.app.state.container.cache
    )
    return TagRead.model_validate(tag)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a tag")
async def delete_tag_endpoint(
    request: Request, tag_id: int, session: SessionDep, _admin: AdminUser
) -> Response:
    await items_service.delete_tag(session, tag_id, cache=request.app.state.container.cache)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Item-scoped actions
# --------------------------------------------------------------------------- #
@router.post(
    "/{item_id}/favorite",
    response_model=FavoriteToggleResponse,
    summary="Toggle favourite",
)
async def toggle_favorite(
    item_id: int, session: SessionDep, user: CurrentUser
) -> FavoriteToggleResponse:
    favorited, count = await items_service.toggle_favourite(session, item_id, user=user)
    return FavoriteToggleResponse(
        message="收藏成功" if favorited else "已取消收藏",
        favorited=favorited,
        favourited_count=count,
    )


@router.post(
    "/{item_id}/buy",
    summary="Buy one unit (idempotent)",
    # The handler may return the cached JSONResponse (idempotent replay), so the
    # union return type must not be turned into a Pydantic response model.
    response_model=None,
)
async def buy_item(
    request: Request,
    item_id: int,
    session: SessionDep,
    user: CurrentUser,
    guard: IdempotencyGuard = Depends(buy_item_idempotency),
    _: None = Depends(rate_limit("buy", limit=20, window_seconds=60)),
) -> dict[str, object] | Response:
    replayed = replay_response(guard)
    if replayed is not None:
        return replayed
    result = await orders_service.purchase(
        session,
        item_id=item_id,
        buyer=user,
        settings=request.app.state.settings,
        quantity=1,
        # Hash the client key: it is namespaced upstream and the DB column is
        # VARCHAR(128), while the raw header may be up to 128 chars itself.
        idempotency_key=stable_key(guard.key, prefix="http:")
        if guard.key
        else f"http:{uuid.uuid4().hex}",
        require_approval=False,
        dispatcher=request.app.state.container.dispatcher,
    )
    body = {
        "order_id": result.order.id,
        "item_name": result.item_name,
        "unit_price": result.unit_price,
        "quantity": result.quantity,
        "remaining_inventory": result.remaining_inventory,
        "message": (
            f"抢购成功！订单 #{result.order.id} 已生成"
            + (
                f"，还剩 {result.remaining_inventory} 件库存"
                if result.remaining_inventory
                else "，已售罄"
            )
        ),
    }
    await guard.remember(body, status_code=status.HTTP_200_OK)
    return body


@router.get("/{item_id}", response_model=ItemRead, summary="Get one listing")
async def get_item(item_id: int, session: SessionDep) -> ItemRead:
    item = await items_service.get_item_or_404(session, item_id)
    return ItemRead.model_validate(item)


@router.put("/{item_id}", response_model=ItemRead, summary="Update a listing")
async def update_item(
    item_id: int, payload: ItemUpdate, session: SessionDep, user: CurrentUser
) -> ItemRead:
    item = await items_service.update_item(session, item_id, payload, actor=user)
    return ItemRead.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a listing")
async def delete_item(item_id: int, session: SessionDep, user: CurrentUser) -> Response:
    await items_service.delete_item(session, item_id, actor=user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
async def _read_all(file: UploadFile) -> bytes:
    await file.seek(0)
    return await file.read()


def _hit(item: object, score: float) -> ItemSearchHit:
    base = ItemRead.model_validate(item)
    return ItemSearchHit(**base.model_dump(), score=round(float(score), 4))


__all__ = ["router"]
