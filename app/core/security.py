"""Security utilities for DM automation: HMAC verification, JWT auth, token encryption."""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from jose import JWTError, jwt
from pydantic import BaseModel
import base64
import os

from app.core.config import dm_settings


class SecurityError(Exception):
    """Custom security exception."""
    pass


class TokenData(BaseModel):
    """JWT token payload data."""
    user_id: str
    account_id: Optional[str] = None
    iat: datetime
    exp: datetime
    token_type: str = "access"  # access or refresh


class WebhookVerifier:
    """Verify webhook signatures from Instagram."""

    @staticmethod
    def verify_webhook_signature(
        body: str,
        signature: str,
        verify_token: str
    ) -> bool:
        """
        Verify Instagram webhook signature using HMAC-SHA256.

        Args:
            body: Raw webhook request body
            signature: X-Hub-Signature header value (sha1=xxx)
            verify_token: Expected verification token

        Returns:
            True if signature is valid, False otherwise

        Raises:
            SecurityError: If verification token doesn't match
        """
        if not verify_token or verify_token != dm_settings.WEBHOOK_VERIFY_TOKEN:
            raise SecurityError("Webhook verification token mismatch")

        # Extract algorithm and hash from signature header
        try:
            algo, signature_hash = signature.split("=", 1)
        except (ValueError, AttributeError):
            return False

        if algo != "sha256":
            return False

        # Calculate expected signature
        expected_signature = hmac.new(
            dm_settings.INSTAGRAM_APP_SECRET.encode(),
            body.encode(),
            hashlib.sha256
        ).hexdigest()

        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(signature_hash, expected_signature)


class JWTManager:
    """JWT token generation and validation."""

    @staticmethod
    def create_access_token(
        user_id: str,
        account_id: Optional[str] = None,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create a JWT access token.

        Args:
            user_id: User ID to encode in token
            account_id: Optional Instagram account ID
            expires_delta: Custom expiration time

        Returns:
            Encoded JWT token

        Raises:
            SecurityError: If token creation fails
        """
        if not dm_settings.JWT_SECRET_KEY:
            raise SecurityError("JWT_SECRET_KEY not configured")

        now = datetime.utcnow()
        if expires_delta is None:
            expires_delta = timedelta(minutes=dm_settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

        expire = now + expires_delta

        to_encode = {
            "user_id": user_id,
            "account_id": account_id,
            "iat": now.isoformat(),
            "exp": expire.isoformat(),
            "token_type": "access"
        }

        try:
            encoded_jwt = jwt.encode(
                to_encode,
                dm_settings.JWT_SECRET_KEY,
                algorithm=dm_settings.JWT_ALGORITHM
            )
            return encoded_jwt
        except Exception as e:
            raise SecurityError(f"Failed to create access token: {str(e)}")

    @staticmethod
    def create_refresh_token(user_id: str) -> str:
        """
        Create a JWT refresh token.

        Args:
            user_id: User ID to encode in token

        Returns:
            Encoded JWT refresh token
        """
        if not dm_settings.JWT_SECRET_KEY:
            raise SecurityError("JWT_SECRET_KEY not configured")

        now = datetime.utcnow()
        expire = now + timedelta(days=dm_settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

        to_encode = {
            "user_id": user_id,
            "iat": now.isoformat(),
            "exp": expire.isoformat(),
            "token_type": "refresh"
        }

        try:
            encoded_jwt = jwt.encode(
                to_encode,
                dm_settings.JWT_SECRET_KEY,
                algorithm=dm_settings.JWT_ALGORITHM
            )
            return encoded_jwt
        except Exception as e:
            raise SecurityError(f"Failed to create refresh token: {str(e)}")

    @staticmethod
    def verify_token(token: str, token_type: str = "access") -> TokenData:
        """
        Verify and decode a JWT token.

        Args:
            token: JWT token to verify
            token_type: Expected token type (access or refresh)

        Returns:
            Decoded token data

        Raises:
            SecurityError: If token is invalid or expired
        """
        if not dm_settings.JWT_SECRET_KEY:
            raise SecurityError("JWT_SECRET_KEY not configured")

        try:
            payload = jwt.decode(
                token,
                dm_settings.JWT_SECRET_KEY,
                algorithms=[dm_settings.JWT_ALGORITHM]
            )

            # Verify token type
            if payload.get("token_type") != token_type:
                raise SecurityError(f"Invalid token type: expected {token_type}")

            user_id = payload.get("user_id")
            if not user_id:
                raise SecurityError("Missing user_id in token")

            return TokenData(
                user_id=user_id,
                account_id=payload.get("account_id"),
                iat=datetime.fromisoformat(payload.get("iat", "")),
                exp=datetime.fromisoformat(payload.get("exp", "")),
                token_type=payload.get("token_type", "access")
            )

        except JWTError as e:
            raise SecurityError(f"Invalid token: {str(e)}")
        except (ValueError, KeyError) as e:
            raise SecurityError(f"Token validation error: {str(e)}")

    @staticmethod
    def refresh_access_token(refresh_token: str) -> str:
        """
        Generate new access token from refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            New access token
        """
        token_data = JWTManager.verify_token(refresh_token, token_type="refresh")
        return JWTManager.create_access_token(
            user_id=token_data.user_id,
            account_id=token_data.account_id
        )


class TokenEncryption:
    """Encrypt/decrypt sensitive tokens for storage."""

    @staticmethod
    def _derive_key(password: str, salt: bytes) -> bytes:
        """
        Derive encryption key from password using PBKDF2.

        Args:
            password: Password/secret to derive from
            salt: Salt for key derivation

        Returns:
            32-byte encryption key
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000
        )
        return kdf.derive(password.encode())

    @staticmethod
    def encrypt_token(token: str) -> str:
        """
        Encrypt token using AES-256-GCM.

        Args:
            token: Token to encrypt

        Returns:
            Base64-encoded encrypted token with nonce and tag (format: nonce:ciphertext:tag)

        Raises:
            SecurityError: If encryption fails or key not configured
        """
        if not dm_settings.JWT_SECRET_KEY:
            raise SecurityError("JWT_SECRET_KEY not configured for token encryption")

        try:
            # Generate random nonce (96 bits for GCM)
            nonce = os.urandom(12)

            # Derive key from secret
            key = TokenEncryption._derive_key(dm_settings.JWT_SECRET_KEY, nonce)

            # Encrypt
            cipher = AESGCM(key)
            ciphertext = cipher.encrypt(nonce, token.encode(), None)

            # Encode as base64 with nonce prepended
            # Format: base64(nonce + ciphertext)
            encrypted_data = nonce + ciphertext
            encoded = base64.b64encode(encrypted_data).decode("utf-8")

            return encoded

        except Exception as e:
            raise SecurityError(f"Token encryption failed: {str(e)}")

    @staticmethod
    def decrypt_token(encrypted_token: str) -> str:
        """
        Decrypt AES-256-GCM encrypted token.

        Args:
            encrypted_token: Base64-encoded encrypted token

        Returns:
            Decrypted token

        Raises:
            SecurityError: If decryption fails
        """
        if not dm_settings.JWT_SECRET_KEY:
            raise SecurityError("JWT_SECRET_KEY not configured for token decryption")

        try:
            # Decode from base64
            encrypted_data = base64.b64decode(encrypted_token)

            # Extract nonce and ciphertext
            nonce = encrypted_data[:12]
            ciphertext = encrypted_data[12:]

            # Derive key from secret using the nonce as salt
            key = TokenEncryption._derive_key(dm_settings.JWT_SECRET_KEY, nonce)

            # Decrypt
            cipher = AESGCM(key)
            token = cipher.decrypt(nonce, ciphertext, None)

            return token.decode("utf-8")

        except Exception as e:
            raise SecurityError(f"Token decryption failed: {str(e)}")


class CredentialManager:
    """Manage encrypted credentials storage and retrieval."""

    @staticmethod
    def encrypt_credentials(credentials: Dict[str, str]) -> str:
        """
        Encrypt credential dict to JSON string.

        Args:
            credentials: Dictionary of credentials

        Returns:
            Encrypted JSON string
        """
        json_str = json.dumps(credentials)
        return TokenEncryption.encrypt_token(json_str)

    @staticmethod
    def decrypt_credentials(encrypted_credentials: str) -> Dict[str, str]:
        """
        Decrypt credentials from encrypted JSON string.

        Args:
            encrypted_credentials: Encrypted credentials string

        Returns:
            Decrypted credentials dictionary
        """
        json_str = TokenEncryption.decrypt_token(encrypted_credentials)
        return json.loads(json_str)

    @staticmethod
    def generate_secure_state(length: int = 32) -> str:
        """
        Generate secure random state for OAuth flows.

        Args:
            length: Length of state string

        Returns:
            Random state string
        """
        return base64.urlsafe_b64encode(os.urandom(length)).decode("utf-8").rstrip("=")
