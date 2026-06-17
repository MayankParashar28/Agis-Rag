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
        logger.info("Startup sequence completed successfully.")
    except Exception as e:
        logger.critical(f"Startup sequence failed: {str(e)}")
        # In a real environment, we might want to shut down, but we proceed so containers stay open for debug
    
    yield
    
    # Shutdown actions
    logger.info("FastAPI service shutting down...")
    await close_redis()
    logger.info("Shutdown sequence completed.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Rate Limiter setup
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
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
