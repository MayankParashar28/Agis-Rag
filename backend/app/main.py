import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uuid

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.logging import setup_logging, logger
from app.core.init_db import init_db
from app.core.redis_client import init_redis, close_redis
from app.api.router import api_router

# Initialize logging
setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info("FastAPI service starting up...")
    try:
        # Initialize Database Tables
        await init_db()
        # Initialize Redis connection
        await init_redis()
        # Rebuild any vector collection that has gone missing. A Qdrant Cloud
        # free cluster is suspended after a week idle and deleted after four,
        # and a Space's own disk is ephemeral - so the index can vanish while
        # Postgres, the source of truth, still holds every chunk. Runs in the
        # background: it must never hold up the port binding.
        asyncio.create_task(_heal_vector_index())
        logger.info("Startup sequence completed successfully.")
    except Exception as e:
        logger.critical(f"Startup sequence failed: {str(e)}")
        # In a real environment, we might want to shut down, but we proceed so containers stay open for debug
    
    yield
    
    # Shutdown actions
    logger.info("FastAPI service shutting down...")
    await close_redis()
    logger.info("Shutdown sequence completed.")


async def _heal_vector_index() -> None:
    """Re-embed KBs whose Qdrant collection is missing or empty.

    Only rebuilds what is actually gone: an intact collection is left alone, so
    a normal restart costs one cheap count per KB rather than re-embedding the
    corpus.
    """
    try:
        from sqlalchemy import select
        from app.core.database import SessionLocal
        from app.models.knowledge import KnowledgeBase
        from app.services.indexer import document_indexer

        async with SessionLocal() as db:
            kbs = (await db.execute(select(KnowledgeBase))).scalars().all()
            for kb in kbs:
                name = document_indexer._get_collection_name(kb.id)
                try:
                    existing = document_indexer.qclient.get_collection(name).points_count
                except Exception:
                    existing = 0  # missing collection, or cluster unreachable
                if existing:
                    continue
                restored = await document_indexer.rebuild_collection_from_db(db, kb.id)
                if restored:
                    logger.warning(
                        f"Vector index for KB '{kb.name}' was empty; "
                        f"rebuilt {restored} points from Postgres."
                    )
    except Exception as e:
        # Never let self-healing take the service down with it.
        logger.error(f"Vector index self-heal skipped: {e}")


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Rate Limiter setup
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_id = str(uuid.uuid4())
    logger.error(f"Unhandled Exception [{error_id}]: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later.", "error_id": error_id}
    )

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Router
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/", tags=["health"])
async def health_check():
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "version": "1.0.0"
    }
