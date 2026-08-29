"""FastAPI dependency injection providers: Database sessions, Auth, and Rate Limiting."""

from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.utils.rate_limiter import RateLimiter, get_redis_client
from app.utils.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    description="JWT Bearer token authentication",
)


async def get_current_user(
    request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Validate bearer token and retrieve the current authenticated User.

    Args:
        request: Incoming HTTP request.
        token: Bearer JWT token from Authorization header.
        db: Async database session.

    Returns:
        User: Authenticated User ORM model.

    Raises:
        HTTPException: 401 Unauthorized if token is invalid or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise credentials_exception

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is inactive",
        )

    # Attach user_id to request state for rate limiting & logging
    request.state.user_id = user.id
    return user


# Common reusable rate limiter dependencies
rate_limit_dispatch = RateLimiter(requests_limit=30, window_seconds=60)
rate_limit_auth = RateLimiter(requests_limit=15, window_seconds=60)
