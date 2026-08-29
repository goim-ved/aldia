"""Celery background worker task for robust HTTP webhook dispatch."""

from contextlib import contextmanager
import json
import logging
import time
from typing import Any, Generator
import uuid
from celery import shared_task
import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SyncSessionLocal
from app.models.webhook import WebhookLog, WebhookTarget
from app.utils.security import generate_hmac_signature

logger = logging.getLogger(__name__)
settings = get_settings()


@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    """Provide a transactional synchronous database session for Celery workers."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _log_delivery_attempt(
    webhook_id: int,
    event_type: str,
    payload: dict[str, Any],
    status: str,
    attempt_count: int,
    response_status_code: int | None = None,
    response_body: str | None = None,
    execution_duration_ms: float | None = None,
    error_message: str | None = None,
) -> None:
    """Helper function to record delivery attempt in the database."""
    try:
        with get_sync_db() as db:
            log_entry = WebhookLog(
                webhook_id=webhook_id,
                event_type=event_type,
                payload=payload,
                response_status_code=response_status_code,
                response_body=response_body[:4000] if response_body else None,
                execution_duration_ms=execution_duration_ms,
                attempt_count=attempt_count,
                status=status,
                error_message=error_message[:2000] if error_message else None,
            )
            db.add(log_entry)
    except Exception as db_err:
        logger.error("Failed to write WebhookLog to database: %s", db_err)


@shared_task(
    bind=True,
    name="tasks.dispatch_webhook",
    max_retries=settings.WEBHOOK_MAX_RETRIES,
    acks_late=True,
)
def dispatch_webhook_task(
    self,
    webhook_id: int,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch webhook POST request to target URL with HMAC signature and exponential backoff."""
    attempt_count = self.request.retries + 1

    # Fetch target details
    with get_sync_db() as db:
        target = db.query(WebhookTarget).filter(WebhookTarget.id == webhook_id).first()
        if not target or not target.is_active:
            logger.warning(
                "Webhook target %s not found or inactive. Skipping dispatch.",
                webhook_id,
            )
            return {"status": "SKIPPED", "reason": "Target not found or inactive"}

        target_url = target.target_url
        secret_token = target.secret_token

    # Serialize payload and compute HMAC-SHA256 signature
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    signature = generate_hmac_signature(secret_token, payload_bytes)
    timestamp = str(int(time.time()))
    delivery_id = str(uuid.uuid4())

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Async-Webhook-Engine/1.0",
        "X-Webhook-Event": event_type,
        "X-Webhook-Signature": signature,
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Delivery-Id": delivery_id,
    }

    start_time = time.perf_counter()
    response_status: int | None = None
    response_text: str | None = None
    error_msg: str | None = None
    success = False

    try:
        with httpx.Client(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
            response = client.post(
                target_url,
                content=payload_bytes,
                headers=headers,
            )
            response_status = response.status_code
            response_text = response.text
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            if response.is_success:
                success = True
            else:
                error_msg = f"HTTP {response_status}: {response.reason_phrase}"

    except httpx.RequestError as req_err:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        error_msg = f"Request error: {req_err}"
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        error_msg = f"Unexpected error: {exc}"

    if success:
        _log_delivery_attempt(
            webhook_id=webhook_id,
            event_type=event_type,
            payload=payload,
            status="SUCCESS",
            attempt_count=attempt_count,
            response_status_code=response_status,
            response_body=response_text,
            execution_duration_ms=duration_ms,
        )
        logger.info(
            "Webhook %s delivered successfully in %sms (attempt %s)",
            webhook_id,
            duration_ms,
            attempt_count,
        )
        return {
            "status": "SUCCESS",
            "status_code": response_status,
            "duration_ms": duration_ms,
            "attempt": attempt_count,
        }

    # Handle delivery failure & retries
    if self.request.retries < self.max_retries:
        retry_delays = settings.WEBHOOK_RETRY_DELAYS
        countdown = (
            retry_delays[self.request.retries]
            if self.request.retries < len(retry_delays)
            else 45
        )

        _log_delivery_attempt(
            webhook_id=webhook_id,
            event_type=event_type,
            payload=payload,
            status="RETRYING",
            attempt_count=attempt_count,
            response_status_code=response_status,
            response_body=response_text,
            execution_duration_ms=duration_ms,
            error_message=f"{error_msg} (Retrying in {countdown}s)",
        )
        logger.warning(
            "Webhook %s delivery failed: %s. Scheduling retry %s in %ss",
            webhook_id,
            error_msg,
            attempt_count + 1,
            countdown,
        )
        raise self.retry(
            exc=Exception(error_msg),
            countdown=countdown,
        )

    # All retries exhausted
    _log_delivery_attempt(
        webhook_id=webhook_id,
        event_type=event_type,
        payload=payload,
        status="FAILED",
        attempt_count=attempt_count,
        response_status_code=response_status,
        response_body=response_text,
        execution_duration_ms=duration_ms,
        error_message=f"{error_msg} (All {attempt_count} attempts exhausted)",
    )
    logger.error(
        "Webhook %s delivery permanently failed after %s attempts: %s",
        webhook_id,
        attempt_count,
        error_msg,
    )
    return {
        "status": "FAILED",
        "status_code": response_status,
        "duration_ms": duration_ms,
        "attempt": attempt_count,
        "error": error_msg,
    }
