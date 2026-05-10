# WARNING: This module duplicates Alembic migrations.
# It is retained ONLY for use in test environments via RUN_SCHEMA_BOOTSTRAP=true.
# Production startup must NOT call this module.
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from bot.db.base import Base


async def ensure_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
