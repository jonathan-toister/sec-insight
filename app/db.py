"""Database engine/session and pgvector setup."""
from collections.abc import AsyncGenerator

from arq.connections import RedisSettings, create_pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def create_redis_pool():
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))
