"""Webhook management and dispatch trigger API router."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, rate_limit_dispatch
from app.models.user import User
from app.models.webhook import WebhookLog, WebhookTarget
from app.schemas.webhook import (
    WebhookDispatchResult,
    WebhookEventTrigger,
    WebhookLogResponse,
    WebhookTargetCreate,
    WebhookTargetResponse,
    WebhookTargetUpdate,
)
from app.tasks.worker import dispatch_webhook_task
from app.utils.security import generate_secure_token

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post(
    "",
    response_model=WebhookTargetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new webhook destination target",
)
async def create_webhook_target(
    target_in: WebhookTargetCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WebhookTarget:
    """Create a new webhook endpoint with an HMAC secret token."""
    secret = target_in.secret_token or generate_secure_token(24)

    webhook = WebhookTarget(
        user_id=current_user.id,
        name=target_in.name,
        target_url=str(target_in.target_url),
        secret_token=secret,
        subscribed_events=target_in.subscribed_events,
        is_active=target_in.is_active,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return webhook


@router.get(
    "",
    response_model=list[WebhookTargetResponse],
    summary="List all registered webhook targets for current user",
)
async def list_webhook_targets(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[WebhookTarget]:
    """List paginated webhook endpoints created by the current user."""
    stmt = (
        select(WebhookTarget)
        .where(WebhookTarget.user_id == current_user.id)
        .order_by(desc(WebhookTarget.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{target_id}",
    response_model=WebhookTargetResponse,
    summary="Get a specific webhook target by ID",
)
async def get_webhook_target(
    target_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WebhookTarget:
    """Retrieve details for a specific webhook target."""
    stmt = select(WebhookTarget).where(
        WebhookTarget.id == target_id,
        WebhookTarget.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    webhook = result.scalar_one_or_none()

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook target with ID {target_id} not found.",
        )
    return webhook


@router.put(
    "/{target_id}",
    response_model=WebhookTargetResponse,
    summary="Update an existing webhook target",
)
async def update_webhook_target(
    target_id: int,
    target_update: WebhookTargetUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WebhookTarget:
    """Update properties of an existing webhook endpoint."""
    stmt = select(WebhookTarget).where(
        WebhookTarget.id == target_id,
        WebhookTarget.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    webhook = result.scalar_one_or_none()

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook target with ID {target_id} not found.",
        )

    update_data = target_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            if field == "target_url":
                setattr(webhook, field, str(value))
            else:
                setattr(webhook, field, value)

    await db.commit()
    await db.refresh(webhook)
    return webhook


@router.delete(
    "/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a webhook target and associated logs",
)
async def delete_webhook_target(
    target_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Delete a webhook endpoint and all its delivery logs."""
    stmt = select(WebhookTarget).where(
        WebhookTarget.id == target_id,
        WebhookTarget.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    webhook = result.scalar_one_or_none()

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook target with ID {target_id} not found.",
        )

    await db.delete(webhook)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/trigger",
    response_model=WebhookDispatchResult,
    dependencies=[Depends(rate_limit_dispatch)],
    summary="Trigger an event and dispatch webhooks to all subscribed targets",
)
async def trigger_webhook_event(
    event_data: WebhookEventTrigger,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WebhookDispatchResult:
    """Publish an event, queuing Celery background dispatch tasks for all matching active targets."""
    stmt = select(WebhookTarget).where(
        WebhookTarget.user_id == current_user.id,
        WebhookTarget.is_active.is_(True),
    )
    result = await db.execute(stmt)
    targets = list(result.scalars().all())

    # Find targets subscribed to '*' or matching the specific event
    matching_targets = [
        t for t in targets
        if "*" in t.subscribed_events or event_data.event_type in t.subscribed_events
    ]

    task_ids: list[str] = []
    for target in matching_targets:
        async_result = dispatch_webhook_task.delay(
            webhook_id=target.id,
            event_type=event_data.event_type,
            payload=event_data.payload,
        )
        task_ids.append(async_result.id)

    return WebhookDispatchResult(
        event_type=event_data.event_type,
        dispatched_targets_count=len(matching_targets),
        task_ids=task_ids,
        message=f"Successfully queued {len(matching_targets)} webhook delivery task(s).",
    )


@router.get(
    "/{target_id}/logs",
    response_model=list[WebhookLogResponse],
    summary="Get delivery logs for a specific webhook target",
)
async def get_webhook_logs(
    target_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[WebhookLog]:
    """Retrieve historical delivery attempts and responses for a target."""
    # Ensure user owns target
    target_stmt = select(WebhookTarget).where(
        WebhookTarget.id == target_id,
        WebhookTarget.user_id == current_user.id,
    )
    target_result = await db.execute(target_stmt)
    target = target_result.scalar_one_or_none()

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook target with ID {target_id} not found.",
        )

    log_stmt = (
        select(WebhookLog)
        .where(WebhookLog.webhook_id == target_id)
        .order_by(desc(WebhookLog.created_at))
        .offset(offset)
        .limit(limit)
    )
    log_result = await db.execute(log_stmt)
    return list(log_result.scalars().all())
