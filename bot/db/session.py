from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sqlalchemy.pool import NullPool

from bot.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    # NullPool is used to avoid "Event loop is closed" errors when sharing the engine across multiple loops (e.g. in workers using asyncio.run).
    poolclass=NullPool,
)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
