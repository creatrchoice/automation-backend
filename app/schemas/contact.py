"""Contact list/search schemas with pagination."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ContactCreateRequest(BaseModel):
    """Create contact request."""

    account_id: str = Field(description="Account ID")
    ig_id: str = Field(description="Instagram user ID")
    ig_username: str = Field(description="Instagram username")
    ig_name: Optional[str] = Field(default=None, description="Display name")
    email: Optional[str] = Field(default=None, description="Email")
    phone: Optional[str] = Field(default=None, description="Phone")
    tags: List[str] = Field(default_factory=list, description="Tags")
    custom_fields: Dict[str, Any] = Field(default_factory=dict, description="Custom fields")
    notes: str = Field(default="", description="Notes")

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "acc_123",
                "ig_id": "123456",
                "ig_username": "john.doe",
                "tags": ["lead"],
                "notes": "Interested in product X"
            }
        }


class ContactUpdateRequest(BaseModel):
    """Update contact request."""

    ig_name: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)
    custom_fields: Optional[Dict[str, Any]] = Field(default=None)
    notes: Optional[str] = Field(default=None)
    opted_out: Optional[bool] = Field(default=None)


class ContactResponse(BaseModel):
    """Contact response."""

    id: str = Field(description="Contact ID")
    account_id: str = Field(description="Account ID")
    ig_id: str = Field(description="Instagram ID")
    ig_username: str = Field(description="Username")
    ig_name: Optional[str] = Field(description="Display name")
    email: Optional[str] = Field(description="Email")
    phone: Optional[str] = Field(description="Phone")
    tags: List[str] = Field(description="Tags")
    custom_fields: Dict[str, Any] = Field(description="Custom fields")
    notes: str = Field(description="Notes")
    opted_out: bool = Field(description="Opted out")
    total_messages_sent: int = Field(description="Messages sent")
    total_messages_received: int = Field(description="Messages received")
    last_interaction_at: Optional[datetime] = Field(description="Last interaction")
    created_at: datetime = Field(description="Created at")
    updated_at: datetime = Field(description="Updated at")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "con_123",
                "account_id": "acc_456",
                "ig_id": "123456",
                "ig_username": "john.doe",
                "tags": ["lead"],
                "opted_out": False,
                "total_messages_sent": 5,
                "total_messages_received": 2
            }
        }


class BulkCreateContactsRequest(BaseModel):
    """Bulk create contacts."""

    account_id: str = Field(description="Account ID")
    contacts: List[ContactCreateRequest] = Field(description="Contacts to create")

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "acc_123",
                "contacts": []
            }
        }


class BulkCreateContactsResponse(BaseModel):
    """Bulk create response."""

    created: int = Field(description="Created count")
    failed: int = Field(description="Failed count")
    errors: List[Dict[str, str]] = Field(default_factory=list, description="Errors")

    class Config:
        json_schema_extra = {
            "example": {
                "created": 95,
                "failed": 5,
                "errors": [
                    {"ig_username": "invalid_user", "error": "Not found"}
                ]
            }
        }


class AddTagRequest(BaseModel):
    """Add tag to contact."""

    tag: str = Field(description="Tag to add")

    class Config:
        json_schema_extra = {
            "example": {
                "tag": "engaged"
            }
        }


class RemoveTagRequest(BaseModel):
    """Remove tag from contact."""

    tag: str = Field(description="Tag to remove")


class ContactSearchRequest(BaseModel):
    """Search contacts."""

    query: Optional[str] = Field(default=None, description="Search query")
    tags: Optional[List[str]] = Field(default=None, description="Filter by tags")
    custom_field: Optional[str] = Field(default=None, description="Custom field name")
    custom_field_value: Optional[str] = Field(default=None, description="Custom field value")
    opted_out: Optional[bool] = Field(default=None, description="Filter opted out")
    has_messaged: Optional[bool] = Field(default=None, description="Filter by message status")
    sort_by: str = Field(default="updated_at", description="Sort field")
    sort_order: str = Field(default="desc", description="Sort order (asc, desc)")
    page: int = Field(default=1, description="Page number")
    page_size: int = Field(default=25, description="Page size (max 100)")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "john",
                "tags": ["lead"],
                "page": 1,
                "page_size": 25
            }
        }


class PaginationMeta(BaseModel):
    """Pagination metadata."""

    total: int = Field(description="Total items")
    page: int = Field(description="Current page")
    page_size: int = Field(description="Items per page")
    total_pages: int = Field(description="Total pages")
    has_next: bool = Field(description="Has next page")
    has_prev: bool = Field(description="Has previous page")


class ContactListResponse(BaseModel):
    """Contact list response."""

    contacts: List[ContactResponse] = Field(description="Contacts")
    pagination: PaginationMeta = Field(description="Pagination info")

    class Config:
        json_schema_extra = {
            "example": {
                "contacts": [],
                "pagination": {
                    "total": 100,
                    "page": 1,
                    "page_size": 25,
                    "total_pages": 4,
                    "has_next": True,
                    "has_prev": False
                }
            }
        }


class ContactExportRequest(BaseModel):
    """Export contacts."""

    format: str = Field(default="csv", description="Format (csv, json)")
    tags: Optional[List[str]] = Field(default=None, description="Filter by tags")
    fields: List[str] = Field(
        default_factory=lambda: ["ig_username", "email", "tags", "last_interaction_at"],
        description="Fields to include"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "format": "csv",
                "fields": ["ig_username", "email", "tags"]
            }
        }


class ContactImportRequest(BaseModel):
    """Import contacts."""

    account_id: str = Field(description="Account ID")
    file_name: str = Field(description="File name")
    file_size_bytes: int = Field(description="File size")
    format: str = Field(description="Format (csv, json)")
    mapping: Dict[str, str] = Field(
        description="Column mapping {csv_column: field_name}"
    )
    default_tags: List[str] = Field(default_factory=list, description="Default tags to add")

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "acc_123",
                "file_name": "contacts.csv",
                "format": "csv",
                "mapping": {"Username": "ig_username", "Email": "email"},
                "default_tags": ["imported"]
            }
        }


class ContactImportResponse(BaseModel):
    """Import response."""

    import_id: str = Field(description="Import job ID")
    status: str = Field(description="Status")
    created: int = Field(description="Created count")
    updated: int = Field(description="Updated count")
    failed: int = Field(description="Failed count")
    file_url: Optional[str] = Field(default=None, description="Failed records file")

    class Config:
        json_schema_extra = {
            "example": {
                "import_id": "imp_123",
                "status": "pending",
                "created": 0,
                "updated": 0,
                "failed": 0
            }
        }
