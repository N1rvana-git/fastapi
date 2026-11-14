"""Promote a user to admin (CLI).

    python -m src.make_admin --email admin@example.com
    python -m src.make_admin --email admin@example.com --role user

Replaces the previous version, which wrote a hard-coded user and could create an
admin with a default password.  This one only changes an existing account's
role, and prints exactly what changed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.app.container import AppContainer
from src.app.core.config import get_settings
from src.app.core.logging import configure_logging
from src.app.modules.users.models import ROLE_ADMIN, ROLE_USER
from src.app.modules.users.repository import get_by_email


async def _run(email: str, role: str) -> int:
    settings = get_settings()
    configure_logging(settings)
    container = AppContainer.create(settings)
    await container.startup()
    try:
        async with container.database.session() as session:
            user = await get_by_email(session, email)
            if user is None:
                print(f"user not found: {email}", file=sys.stderr)
                return 1
            previous = user.role
            user.role = role
            await session.commit()
            print(f"user {email} (id={user.id}): role {previous} -> {role}")
            return 0
    finally:
        await container.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="Change a user's role")
    parser.add_argument("--email", required=True, help="account e-mail")
    parser.add_argument(
        "--role", default=ROLE_ADMIN, choices=[ROLE_ADMIN, ROLE_USER], help="target role"
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.email, args.role))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
