"""Functional tests for Webhook targets, event triggers, logs, HMAC signing, and Celery worker."""

from contextlib import contextmanager
import json
from unittest.mock import MagicMock, patch
import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.webhook import WebhookLog, WebhookTarget
from app.tasks.worker import _log_delivery_attempt, dispatch_webhook_task
from app.utils.security import generate_hmac_signature, verify_hmac_signature


@pytest.mark.asyncio
async def test_create_webhook_target(async_client: AsyncClient, auth_headers: dict[str, str]):
    """Test creating a new webhook destination target."""
    payload = {
        "name": "Payment Service Hook",
        "target_url": "https://api.example.com/webhooks/payments",
        "subscribed_events": ["payment.completed", "payment.refunded"],
    }
    response = await async_client.post("/api/v1/webhooks", json=payload, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["target_url"] == payload["target_url"]
    assert data["subscribed_events"] == payload["subscribed_events"]
    assert data["is_active"] is True
    assert "secret_token" in data
    assert len(data["secret_token"]) >= 16


@pytest.mark.asyncio
async def test_list_webhook_targets(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
):
    """Test listing only webhooks owned by the authenticated user."""
    # Create target for User 1
    await async_client.post(
        "/api/v1/webhooks",
        json={"name": "User 1 Hook", "target_url": "https://user1.example.com/hook"},
        headers=auth_headers,
    )
    # Create target for User 2
    await async_client.post(
        "/api/v1/webhooks",
        json={"name": "User 2 Hook", "target_url": "https://user2.example.com/hook"},
        headers=second_auth_headers,
    )

    # Fetch User 1 webhooks
    res1 = await async_client.get("/api/v1/webhooks", headers=auth_headers)
    assert res1.status_code == 200
    items1 = res1.json()
    assert len(items1) == 1
    assert items1[0]["name"] == "User 1 Hook"

    # Fetch User 2 webhooks
    res2 = await async_client.get("/api/v1/webhooks", headers=second_auth_headers)
    assert res2.status_code == 200
    items2 = res2.json()
    assert len(items2) == 1
    assert items2[0]["name"] == "User 2 Hook"


@pytest.mark.asyncio
async def test_get_and_update_webhook_target(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
):
    """Test retrieving and updating an existing webhook target."""
    create_res = await async_client.post(
        "/api/v1/webhooks",
        json={"name": "Initial Name", "target_url": "https://initial.example.com/hook"},
        headers=auth_headers,
    )
    target_id = create_res.json()["id"]

    # Get by ID
    get_res = await async_client.get(f"/api/v1/webhooks/{target_id}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Initial Name"

    # Update
    update_res = await async_client.put(
        f"/api/v1/webhooks/{target_id}",
        json={"name": "Updated Name", "is_active": False},
        headers=auth_headers,
    )
    assert update_res.status_code == 200
    updated_data = update_res.json()
    assert updated_data["name"] == "Updated Name"
    assert updated_data["is_active"] is False


@pytest.mark.asyncio
async def test_delete_webhook_target(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
):
    """Test deleting a webhook target."""
    create_res = await async_client.post(
        "/api/v1/webhooks",
        json={"name": "To Delete", "target_url": "https://delete.example.com/hook"},
        headers=auth_headers,
    )
    target_id = create_res.json()["id"]

    # Delete
    del_res = await async_client.delete(f"/api/v1/webhooks/{target_id}", headers=auth_headers)
    assert del_res.status_code == 204

    # Verify 404 on subsequent get
    get_res = await async_client.get(f"/api/v1/webhooks/{target_id}", headers=auth_headers)
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_user_cross_isolation_security(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
):
    """Test that User 2 cannot read, update, or delete User 1's webhook."""
    create_res = await async_client.post(
        "/api/v1/webhooks",
        json={"name": "User 1 Private Hook", "target_url": "https://user1.com/hook"},
        headers=auth_headers,
    )
    target_id = create_res.json()["id"]

    # User 2 attempts to read User 1's hook
    get_res = await async_client.get(f"/api/v1/webhooks/{target_id}", headers=second_auth_headers)
    assert get_res.status_code == 404

    # User 2 attempts to update User 1's hook
    put_res = await async_client.put(
        f"/api/v1/webhooks/{target_id}",
        json={"name": "Hacked Name"},
        headers=second_auth_headers,
    )
    assert put_res.status_code == 404

    # User 2 attempts to delete User 1's hook
    del_res = await async_client.delete(f"/api/v1/webhooks/{target_id}", headers=second_auth_headers)
    assert del_res.status_code == 404


@pytest.mark.asyncio
async def test_trigger_event_dispatches_celery_task(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    mock_celery_task: MagicMock,
):
    """Test triggering an event enqueues background Celery tasks for matching targets."""
    # Target 1: subscribed to "order.created"
    await async_client.post(
        "/api/v1/webhooks",
        json={
            "name": "Order Service",
            "target_url": "https://orders.example.com/hook",
            "subscribed_events": ["order.created"],
        },
        headers=auth_headers,
    )

    # Target 2: subscribed to wildcard "*"
    await async_client.post(
        "/api/v1/webhooks",
        json={
            "name": "Audit Service",
            "target_url": "https://audit.example.com/hook",
            "subscribed_events": ["*"],
        },
        headers=auth_headers,
    )

    # Target 3: subscribed to unrelated event "user.signup"
    await async_client.post(
        "/api/v1/webhooks",
        json={
            "name": "User Service",
            "target_url": "https://users.example.com/hook",
            "subscribed_events": ["user.signup"],
        },
        headers=auth_headers,
    )

    # Trigger "order.created" event
    event_payload = {
        "event_type": "order.created",
        "payload": {"order_id": 9876, "amount": 149.99, "currency": "USD"},
    }
    response = await async_client.post(
        "/api/v1/webhooks/trigger",
        json=event_payload,
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["event_type"] == "order.created"
    assert data["dispatched_targets_count"] == 2
    assert len(data["task_ids"]) == 2
    assert mock_celery_task.call_count == 2


@pytest.mark.asyncio
async def test_hmac_signature_generation_and_verification():
    """Unit test for HMAC-SHA256 signature generation and constant-time verification."""
    secret = "my_super_secret_signing_key_456"
    payload = {"user_id": 42, "action": "profile_updated", "timestamp": 1700000000}
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")

    # Generate signature
    signature = generate_hmac_signature(secret, payload_bytes)
    assert isinstance(signature, str)
    assert len(signature) == 64  # SHA256 hex length is 64 characters

    # Verify signature
    assert verify_hmac_signature(secret, payload_bytes, signature) is True
    # Verify rejection on tampered payload
    tampered_bytes = json.dumps({"user_id": 99}, sort_keys=True).encode("utf-8")
    assert verify_hmac_signature(secret, tampered_bytes, signature) is False
    # Verify rejection on wrong secret
    assert verify_hmac_signature("wrong_secret", payload_bytes, signature) is False


@pytest.mark.asyncio
async def test_get_webhook_logs(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    test_user: User,
):
    """Test retrieving delivery logs for a webhook target."""
    target = WebhookTarget(
        user_id=test_user.id,
        name="Log Test Hook",
        target_url="https://example.com/hook",
        secret_token="test_secret",
        subscribed_events=["test.event"],
        is_active=True,
    )
    db_session.add(target)
    await db_session.commit()
    await db_session.refresh(target)

    log1 = WebhookLog(
        webhook_id=target.id,
        event_type="test.event",
        payload={"msg": "first"},
        response_status_code=200,
        response_body='{"ok": true}',
        execution_duration_ms=45.2,
        attempt_count=1,
        status="SUCCESS",
    )
    log2 = WebhookLog(
        webhook_id=target.id,
        event_type="test.event",
        payload={"msg": "second"},
        response_status_code=500,
        response_body="Internal Server Error",
        execution_duration_ms=120.0,
        attempt_count=1,
        status="RETRYING",
        error_message="HTTP 500: Internal Server Error",
    )
    db_session.add_all([log1, log2])
    await db_session.commit()

    # Query logs endpoint
    response = await async_client.get(f"/api/v1/webhooks/{target.id}/logs", headers=auth_headers)
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) == 2
    statuses = {log["status"] for log in logs}
    assert statuses == {"SUCCESS", "RETRYING"}


@pytest.mark.asyncio
async def test_health_check_endpoint(async_client: AsyncClient):
    """Test the application /health endpoint."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "services" in data
    assert "app_name" in data


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient):
    """Test the application root / landing endpoint."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "documentation" in data


def test_models_repr():
    """Test WebhookTarget and WebhookLog __repr__ methods."""
    target = WebhookTarget(id=10, name="Repr Hook", target_url="https://repr.com")
    assert "Repr Hook" in repr(target)
    assert "10" in repr(target)

    log = WebhookLog(id=20, webhook_id=10, status="SUCCESS")
    assert "SUCCESS" in repr(log)
    assert "20" in repr(log)


def test_celery_worker_dispatch_success():
    """Test Celery dispatch task when destination responds with HTTP 200."""
    fake_target = MagicMock()
    fake_target.id = 1
    fake_target.is_active = True
    fake_target.target_url = "https://receiver.example.com/webhook"
    fake_target.secret_token = "secret123"

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = fake_target

    @contextmanager
    def mock_get_sync_db():
        yield mock_db

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"status": "ok"}'
    mock_response.is_success = True

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response

    dispatch_webhook_task.request.retries = 0
    dispatch_webhook_task.max_retries = 3

    with (
        patch("app.tasks.worker.get_sync_db", mock_get_sync_db),
        patch("httpx.Client") as mock_httpx_client,
    ):
        mock_httpx_client.return_value.__enter__.return_value = mock_client
        result = dispatch_webhook_task.__wrapped__(
            webhook_id=1,
            event_type="test.event",
            payload={"order_id": 123},
        )

        assert result["status"] == "SUCCESS"
        assert result["status_code"] == 200
        assert mock_client.post.called


def test_celery_worker_dispatch_skipped_when_inactive():
    """Test Celery dispatch task skips inactive target."""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    @contextmanager
    def mock_get_sync_db():
        yield mock_db

    dispatch_webhook_task.request.retries = 0

    with patch("app.tasks.worker.get_sync_db", mock_get_sync_db):
        result = dispatch_webhook_task.__wrapped__(
            webhook_id=999,
            event_type="test.event",
            payload={},
        )
        assert result["status"] == "SKIPPED"


def test_celery_worker_dispatch_retry_on_failure():
    """Test Celery dispatch task triggers retry on HTTP 500 error."""
    fake_target = MagicMock()
    fake_target.id = 1
    fake_target.is_active = True
    fake_target.target_url = "https://failing.example.com/webhook"
    fake_target.secret_token = "secret123"

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = fake_target

    @contextmanager
    def mock_get_sync_db():
        yield mock_db

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.reason_phrase = "Internal Server Error"
    mock_response.text = "Error"
    mock_response.is_success = False

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response

    dispatch_webhook_task.request.retries = 0
    dispatch_webhook_task.max_retries = 3

    with (
        patch("app.tasks.worker.get_sync_db", mock_get_sync_db),
        patch("httpx.Client") as mock_httpx_client,
        patch.object(dispatch_webhook_task, "retry", side_effect=Exception("Retry triggered")) as mock_retry,
    ):
        mock_httpx_client.return_value.__enter__.return_value = mock_client
        with pytest.raises(Exception, match="Retry triggered"):
            dispatch_webhook_task.__wrapped__(
                webhook_id=1,
                event_type="test.event",
                payload={},
            )
        assert mock_retry.called


def test_celery_worker_dispatch_exhausted_retries():
    """Test Celery dispatch task marks FAILED when max retries are exhausted."""
    fake_target = MagicMock()
    fake_target.id = 1
    fake_target.is_active = True
    fake_target.target_url = "https://failing.example.com/webhook"
    fake_target.secret_token = "secret123"

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = fake_target

    @contextmanager
    def mock_get_sync_db():
        yield mock_db

    mock_response = MagicMock()
    mock_response.status_code = 502
    mock_response.reason_phrase = "Bad Gateway"
    mock_response.text = "Gateway Down"
    mock_response.is_success = False

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response

    dispatch_webhook_task.request.retries = 3
    dispatch_webhook_task.max_retries = 3

    with (
        patch("app.tasks.worker.get_sync_db", mock_get_sync_db),
        patch("httpx.Client") as mock_httpx_client,
    ):
        mock_httpx_client.return_value.__enter__.return_value = mock_client
        result = dispatch_webhook_task.__wrapped__(
            webhook_id=1,
            event_type="test.event",
            payload={},
        )
        assert result["status"] == "FAILED"
        assert result["status_code"] == 502
