from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings
from app.core.logging import logger

import ssl
import urllib.parse

import certifi

# asyncpg does not understand libpq's URL parameters, and SQLAlchemy forwards
# any query argument it does not recognise straight to asyncpg.connect() - so
# one stray parameter is a TypeError at startup, not a warning. Only sslmode
# used to be stripped here; Neon now appends channel_binding by default, which
# raised "connect() got an unexpected keyword argument 'channel_binding'" and
# took the service down before it could serve a request.
_LIBPQ_ONLY_PARAMS = ("sslmode", "channel_binding", "gssencmode", "target_session_attrs")

db_uri = settings.DATABASE_URI
connect_args = {}

if db_uri:
    parsed = urllib.parse.urlparse(db_uri)
    query_params = urllib.parse.parse_qs(parsed.query)

    sslmode_val = (query_params.get("sslmode") or [None])[0]
    for param in _LIBPQ_ONLY_PARAMS:
        query_params.pop(param, None)

    if sslmode_val in ("require", "verify-ca", "verify-full"):
        # connect_args["ssl"] = True builds a context from the system trust
        # store, which a slim container image may not have - that surfaces as
        # SSLCertVerificationError "unable to get local issuer certificate".
        # certifi ships the bundle, so this works the same everywhere.
        connect_args["ssl"] = ssl.create_default_context(cafile=certifi.where())

    new_query = urllib.parse.urlencode(query_params, doseq=True)
    db_uri = urllib.parse.urlunparse(parsed._replace(query=new_query))

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
