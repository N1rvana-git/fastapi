"""Item API contracts.

Request and response models are strict: ``extra="forbid"`` on writes so typos in
client payloads fail loudly instead of being silently ignored, and response
models never expose embeddings (the old list endpoint hand-built dicts to avoid
serialising 1024-float vectors - a schema should make that impossible).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=32)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("tag name must not be blank")
        return cleaned


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ItemBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    price: float = Field(ge=0, le=10_000_000)
    is_offer: bool = True
    image_path: str | None = Field(default=None, max_length=1024)
    inventory: int = Field(default=1, ge=0, le=1_000_000)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class ItemCreate(ItemBase):
    tag_ids: list[int] = Field(default_factory=list, max_length=32)


class ItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    price: float | None = Field(default=None, ge=0, le=10_000_000)
    is_offer: bool | None = None
    image_path: str | None = Field(default=None, max_length=1024)
    inventory: int | None = Field(default=None, ge=0, le=1_000_000)
    tag_ids: list[int] | None = Field(default=None, max_length=32)


class ItemRead(BaseModel):
    """Public representation - no embedding vectors, ever."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    price: float
    is_offer: bool | None = True
    is_sold: bool = False
    image_path: str | None = None
    inventory: int = 1
    owner_id: int | None = None
    tags: list[TagRead] = Field(default_factory=list)
    created_at: datetime | None = None


class ItemListResponse(BaseModel):
    total: int
    items: list[ItemRead]
    skip: int = 0
    limit: int = 20


class FavoriteToggleResponse(BaseModel):
    message: str
    favorited: bool
    favourited_count: int


class ImageUploadResponse(BaseModel):
    filename: str
    url: str
    image_embedding: list[float] | None = None
    message: str


class TextSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_text: str = Field(min_length=1, max_length=500)


class ItemSearchHit(ItemRead):
    score: float | None = Field(default=None, description="Cosine similarity (higher is better)")


class ImageSearchResponse(BaseModel):
    message: str
    data: list[ItemSearchHit]
    mode: str = Field(default="python", description="python | pgvector")


class AnalyzeUploadResponse(BaseModel):
    message: str
    image_url: str
    suggested_tags: list[str]
    suggested_title: str


__all__ = [
    "AnalyzeUploadResponse",
    "FavoriteToggleResponse",
    "ImageSearchResponse",
    "ImageUploadResponse",
    "ItemCreate",
    "ItemListResponse",
    "ItemRead",
    "ItemSearchHit",
    "ItemUpdate",
    "TagCreate",
    "TagRead",
    "TextSearchRequest",
]
