"""Pagination primitives (offset-based, explicit bounds)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")

MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class PageParams:
    skip: int
    limit: int


def pagination_params(
    skip: int = Query(0, ge=0, le=100_000, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=MAX_PAGE_SIZE, description="Page size (max 100)"),
) -> PageParams:
    return PageParams(skip=skip, limit=limit)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    skip: int = Field(ge=0)
    limit: int = Field(ge=1)
    has_more: bool = False

    @classmethod
    def build(cls, items: list[T], total: int, params: PageParams) -> Page[T]:
        return cls(
            items=items,
            total=total,
            skip=params.skip,
            limit=params.limit,
            has_more=params.skip + len(items) < total,
        )


__all__ = ["MAX_PAGE_SIZE", "Page", "PageParams", "pagination_params"]
