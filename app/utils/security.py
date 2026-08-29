"""Security and cryptography utilities: password hashing, JWT tokens, and HMAC signing."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any
import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()


def get_password_hash(password: str) -> str:
    """Hash a plaintext password using bcrypt.

    Args:
        password: Plaintext password string.

    Returns:
        Hashed password string.
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Args:
        plain_password: Provided plaintext password.
        hashed_password: Stored bcrypt hashed string.

    Returns:
        True if password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    """Create and sign a new JWT access token.

    Args:
        data: Claims dictionary to include in token payload.
        expires_delta: Optional custom token lifetime.

    Returns:
        Encoded JWT token string.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": int(expire.timestamp())})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token.

    Args:
        token: JWT string.

    Returns:
        Decoded payload claims or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except (jwt.PyJWTError, ValueError):
        return None


def generate_hmac_signature(secret: str, payload_bytes: bytes) -> str:
    """Compute HMAC-SHA256 signature for webhook payload verification.

    Args:
        secret: Webhook shared secret token.
        payload_bytes: Raw JSON payload bytes to sign.

    Returns:
        Hex-encoded HMAC-SHA256 signature.
    """
    mac = hmac.new(secret.encode("utf-8"), msg=payload_bytes, digestmod=hashlib.sha256)
    return mac.hexdigest()


def verify_hmac_signature(secret: str, payload_bytes: bytes, signature: str) -> bool:
    """Safely verify HMAC-SHA256 signature against payload bytes.

    Args:
        secret: Webhook shared secret token.
        payload_bytes: Raw JSON payload bytes to verify.
        signature: Received hex signature.

    Returns:
        True if signature matches, False otherwise.
    """
    expected = generate_hmac_signature(secret, payload_bytes)
    return hmac.compare_digest(expected, signature)


def generate_secure_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure random hexadecimal token.

    Args:
        nbytes: Number of random bytes.

    Returns:
        Hex-encoded random token string.
    """
    return secrets.token_hex(nbytes)
