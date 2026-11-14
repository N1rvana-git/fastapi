"""User aggregate: account, role and Feishu binding."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.app.core.database import Base

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.app.modules.items.models import ItemModel

ROLE_USER = "user"
ROLE_ADMIN = "admin"
VALID_ROLES = frozenset({ROLE_USER, ROLE_ADMIN})


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, index=True)
    # Kept for backwards compatibility with the existing schema; the API no
    # longer exposes it.
    age: Mapped[int] = mapped_column(Integer, nullable=False, default=18, server_default="18")
    email: Mapped[str | None] = mapped_column(String, index=True)
    phone: Mapped[str | None] = mapped_column(String, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String)
    feishu_open_id: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True
    )
    role: Mapped[str] = mapped_column(
        String, default=ROLE_USER, server_default=ROLE_USER, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    items: Mapped[list[ItemModel]] = relationship(
        "ItemModel",
        back_populates="owner",
        cascade="all, delete-orphan",
        # Deliberately NOT eager: loading a user must never drag in every listing
        # they own (and then every listing's owner again). That "selectin
        # explosion" made a single /buy take seconds once the perf data grew.
        # Load explicitly when a use case really needs it.
        lazy="raise",
    )
    favourites: Mapped[list[ItemModel]] = relationship(
        "ItemModel",
        secondary="favourites",
        back_populates="favourited_by",
        lazy="raise",
    )

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<UserModel id={self.id} email={self.email!r} role={self.role!r}>"


# Case-insensitive uniqueness, enforced by the database rather than a service
# check (two replicas can otherwise both pass a "SELECT then INSERT" race).
# The partial predicate lets legacy/SSO accounts live without an e-mail.
Index(
    "users_email_lower_key",
    func.lower(UserModel.email),
    unique=True,
    postgresql_where=text("email IS NOT NULL"),
    sqlite_where=text("email IS NOT NULL"),
)
