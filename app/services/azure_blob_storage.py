"""Azure Blob Storage helpers for signed frontend uploads."""
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import uuid4

from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas

from app.core.config import dm_settings


class AzureBlobConfigError(ValueError):
    """Raised when required Blob Storage settings are missing."""


class AzureBlobStorageService:
    """Generate short-lived signed upload URLs for blob storage."""

    def __init__(self) -> None:
        self._client: Optional[BlobServiceClient] = None

    def _get_client(self) -> BlobServiceClient:
        if self._client is not None:
            return self._client

        conn_str = (dm_settings.AZURE_STORAGE_CONNECTION_STRING or "").strip()
        if not conn_str:
            raise AzureBlobConfigError("AZURE_STORAGE_CONNECTION_STRING is not set")

        self._client = BlobServiceClient.from_connection_string(conn_str)
        return self._client

    @staticmethod
    def _sanitize_segment(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", value or "")
        return cleaned.strip("._-") or "file"

    def build_upload_url(
        self, *, user_id: str, filename: str, content_type: str
    ) -> Dict[str, Any]:
        """Create a signed PUT URL for a frontend image upload."""
        container = (dm_settings.AZURE_STORAGE_CONTAINER_NAME or "").strip()
        if not container:
            raise AzureBlobConfigError("AZURE_STORAGE_CONTAINER_NAME is not set")

        client = self._get_client()
        if not user_id:
            raise ValueError("user_id is required")
        if not filename:
            raise ValueError("filename is required")

        safe_user = self._sanitize_segment(user_id)
        base_name = os.path.basename(filename)
        safe_name = self._sanitize_segment(base_name)
        blob_name = (
            f"uploads/{safe_user}/{datetime.utcnow():%Y/%m/%d}/"
            f"{uuid4().hex}_{safe_name}"
        )

        blob_client = client.get_blob_client(container=container, blob=blob_name)
        expiry = datetime.utcnow() + timedelta(
            minutes=max(1, dm_settings.AZURE_STORAGE_SAS_EXPIRY_MINUTES)
        )

        account_key = getattr(client.credential, "account_key", None)
        if not account_key:
            raise AzureBlobConfigError(
                "Blob client credential is not a shared account key; "
                "cannot generate account-key SAS token"
            )

        sas = generate_blob_sas(
            account_name=client.account_name,
            container_name=container,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(write=True, create=True),
            expiry=expiry,
            content_type=content_type,
        )

        return {
            "upload_url": f"{blob_client.url}?{sas}",
            "blob_url": blob_client.url,
            "blob_name": blob_name,
            "container": container,
            "expires_at": expiry.isoformat() + "Z",
            "method": "PUT",
            "headers": {
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": content_type,
            },
        }


azure_blob_storage = AzureBlobStorageService()
