"""Item aggregate: listings, tags and the many-to-many helpers around them."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.core.database import Base

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.app.modules.users.models import UserModel

#: Tags are a light-weight taxonomy, many-to-many with items.
item_tag = Table(
    "item_tag",
    Base.metadata,
    Column("item_id", Integer, ForeignKey("item.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)

#: Favourites ("collect") - previously referenced by the router but missing from
#: the models, which made ``POST /items/{id}/favorite`` fail at runtime.
favourites = Table(
    "favourites",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("item_id", Integer, ForeignKey("item.id", ondelete="CASCADE"), primary_key=True),
)


class TagModel(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)

    items: Mapped[list[ItemModel]] = relationship(
        "ItemModel", secondary=item_tag, back_populates="tags"
    )


class ItemModel(Base):
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    price: Mapped[float] = mapped_column(Float)
    is_offer: Mapped[bool | None] = mapped_column(Boolean, default=True)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    inventory: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_sold: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # 1024-d semantic text embedding (Zhipu embedding-2)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    # 512-d visual embedding for "search by image" (Chinese-CLIP)
    image_embedding: Mapped[list[float] | None] = mapped_column(Vector(512), nullable=True)

    owner: Mapped[UserModel | None] = relationship(
        "UserModel", back_populates="items", lazy="selectin"
    )
    tags: Mapped[list[TagModel]] = relationship(
        "TagModel", secondary=item_tag, back_populates="items", lazy="selectin"
    )
    favourited_by: Mapped[list[UserModel]] = relationship(
        "UserModel", secondary=favourites, back_populates="favourites", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ItemModel id={self.id} name={self.name!r} inventory={self.inventory}>"
