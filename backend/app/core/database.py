from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings
from app.core.logging import logger

import urllib.parse

# Strip sslmode from URI for asyncpg and pass ssl=True in connect_args
db_uri = settings.DATABASE_URI
connect_args = {}

if db_uri and "sslmode=" in db_uri:
    parsed = urllib.parse.urlparse(db_uri)
    query_params = urllib.parse.parse_qs(parsed.query)
    if "sslmode" in query_params:
        sslmode_val = query_params.pop("sslmode")[0]
        if sslmode_val in ["require", "verify-ca", "verify-full"]:
            connect_args["ssl"] = True
    new_query = urllib.parse.urlencode(query_params, doseq=True)
    parsed = parsed._replace(query=new_query)
    db_uri = urllib.parse.urlunparse(parsed)

# Create Async Engine
engine = create_async_engine(
    db_uri,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=connect_args
)

# Async Sessionmaker
SessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

# Base class for SQLAlchemy Models
class Base(DeclarativeBase):
    pass

# FastAPI dependency for async db session
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error: {str(e)}")
            await session.rollback()
            raise
        finally:
            await session.close()
