"""FastAPI main application entrypoint with lifespan events, CORS, and routing."""

from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import api_router
from app.config import get_settings
from app.database import engine
from app.utils.rate_limiter import close_redis_client, get_redis_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("async_webhook_engine")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event handler for application startup and shutdown tasks."""
    logger.info("Initializing Async Webhook Engine application...")

    # Validate Redis connection on startup
    try:
        redis_client = await get_redis_client()
        await redis_client.ping()
        logger.info("Redis connection established successfully.")
    except Exception as exc:
        logger.warning("Redis initial connection warning (may fail open): %s", exc)

    yield

    # Cleanup resources on shutdown
    logger.info("Shutting down Async Webhook Engine application...")
    await close_redis_client()
    await engine.dispose()
    logger.info("Database and Redis connections closed.")


app = FastAPI(
    title="Async Webhook Delivery Engine",
    description=(
        "Production-ready asynchronous webhook delivery engine built with "
        "FastAPI, Celery, PostgreSQL (SQLAlchemy 2.0 async), and Redis."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(api_router)


@app.get(
    "/health",
    tags=["System"],
    summary="Health check endpoint",
    status_code=status.HTTP_200_OK,
)
async def health_check() -> JSONResponse:
    """Verify application health and database connectivity."""
    db_status = "healthy"
    redis_status = "healthy"

    # Check Database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as err:
        db_status = f"unhealthy: {err}"

    # Check Redis
    try:
        redis_client = await get_redis_client()
        await redis_client.ping()
    except Exception as err:
        redis_status = f"unhealthy: {err}"

    overall_status = "healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded"

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": overall_status,
            "app_name": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "services": {
                "database": db_status,
                "redis": redis_status,
            },
        },
    )


@app.get(
    "/",
    tags=["System"],
    summary="Root landing information",
)
async def root() -> dict[str, str]:
    """Root endpoint welcoming visitors and linking to interactive docs."""
    return {
        "message": "Welcome to the Async Webhook Delivery Engine API",
        "documentation": "/docs",
        "health": "/health",
    }
