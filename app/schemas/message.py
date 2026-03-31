"""Message template schemas."""
from typing import Optional, List
from pydantic import BaseModel, Field


class TextMessageSchema(BaseModel):
    """Simple text message."""

    text: str = Field(description="Message text", min_length=1, max_length=1000)

    class Config:
        json_schema_extra = {
            "example": {
                "text": "Hello {{first_name}}, how are you?"
            }
        }


class ButtonSchema(BaseModel):
    """Button in template."""

    title: str = Field(description="Button text", min_length=1, max_length=50)
    type: str = Field(description="Type (web_url, postback)")
    url: Optional[str] = Field(default=None, description="URL for web_url")
    payload: Optional[str] = Field(default=None, description="Payload for postback")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Learn More",
                "type": "web_url",
                "url": "https://example.com"
            }
        }


class GenericElementSchema(BaseModel):
    """Element in generic template."""

    title: str = Field(description="Title", min_length=1, max_length=80)
    subtitle: Optional[str] = Field(default=None, description="Subtitle", max_length=80)
    image_url: Optional[str] = Field(default=None, description="Image URL")
    default_action_url: Optional[str] = Field(default=None, description="Default action URL")
    buttons: List[ButtonSchema] = Field(default_factory=list, description="Buttons", max_items=3)

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Product Name",
                "subtitle": "Product description",
                "image_url": "https://example.com/image.jpg",
                "buttons": []
            }
        }


class GenericTemplateSchema(BaseModel):
    """Generic template with single element."""

    title: str = Field(description="Template title")
    subtitle: Optional[str] = Field(default=None, description="Subtitle")
    image_url: Optional[str] = Field(default=None, description="Image URL")
    buttons: List[ButtonSchema] = Field(default_factory=list, description="Buttons", max_items=3)

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Check this out!",
                "subtitle": "Something interesting",
                "image_url": "https://example.com/img.jpg",
                "buttons": []
            }
        }


class CarouselSchema(BaseModel):
    """Carousel template with multiple elements."""

    elements: List[GenericElementSchema] = Field(
        description="Carousel elements",
        min_items=2,
        max_items=10
    )

    class Config:
        json_schema_extra = {
            "example": {
                "elements": [
                    {
                        "title": "Product 1",
                        "subtitle": "Description",
                        "buttons": []
                    },
                    {
                        "title": "Product 2",
                        "subtitle": "Description",
                        "buttons": []
                    }
                ]
            }
        }


class ImageMessageSchema(BaseModel):
    """Image message."""

    image_url: str = Field(description="Image URL")
    caption: Optional[str] = Field(default=None, description="Image caption")

    class Config:
        json_schema_extra = {
            "example": {
                "image_url": "https://example.com/image.jpg",
                "caption": "Check out this image"
            }
        }


class VideoMessageSchema(BaseModel):
    """Video message."""

    video_url: str = Field(description="Video URL")
    caption: Optional[str] = Field(default=None, description="Video caption")
    thumbnail_url: Optional[str] = Field(default=None, description="Thumbnail URL")

    class Config:
        json_schema_extra = {
            "example": {
                "video_url": "https://example.com/video.mp4",
                "caption": "Watch this video",
                "thumbnail_url": "https://example.com/thumb.jpg"
            }
        }


class FileMessageSchema(BaseModel):
    """File message."""

    file_url: str = Field(description="File URL")
    file_name: str = Field(description="File name")

    class Config:
        json_schema_extra = {
            "example": {
                "file_url": "https://example.com/document.pdf",
                "file_name": "document.pdf"
            }
        }


class CreateMessageTemplateRequest(BaseModel):
    """Create message template."""

    name: str = Field(description="Template name")
    message_type: str = Field(
        description="Type (text, generic_template, carousel, image, video, file)"
    )
    content: dict = Field(description="Template content")
    variables: List[str] = Field(default_factory=list, description="Variables used")
    tags: List[str] = Field(default_factory=list, description="Template tags")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Welcome Message",
                "message_type": "text",
                "content": {"text": "Hello {{first_name}}!"},
                "variables": ["first_name"]
            }
        }


class UpdateMessageTemplateRequest(BaseModel):
    """Update message template."""

    name: Optional[str] = Field(default=None, description="Template name")
    content: Optional[dict] = Field(default=None, description="Template content")
    variables: Optional[List[str]] = Field(default=None, description="Variables")
    tags: Optional[List[str]] = Field(default=None, description="Tags")


class MessageTemplateResponse(BaseModel):
    """Message template response."""

    id: str = Field(description="Template ID")
    account_id: str = Field(description="Account ID")
    user_id: str = Field(description="User ID")
    name: str = Field(description="Template name")
    message_type: str = Field(description="Message type")
    content: dict = Field(description="Content")
    variables: List[str] = Field(description="Variables")
    tags: List[str] = Field(description="Tags")
    usage_count: int = Field(description="Times used")
    created_at: str = Field(description="Created at")
    updated_at: str = Field(description="Updated at")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "tpl_123",
                "account_id": "acc_456",
                "user_id": "usr_789",
                "name": "Welcome",
                "message_type": "text",
                "content": {"text": "Hello {{first_name}}!"},
                "variables": ["first_name"],
                "usage_count": 10
            }
        }


class MessageTemplateListResponse(BaseModel):
    """List of templates."""

    templates: List[MessageTemplateResponse] = Field(description="Templates")
    total: int = Field(description="Total count")
    page: int = Field(description="Current page")
    page_size: int = Field(description="Page size")

    class Config:
        json_schema_extra = {
            "example": {
                "templates": [],
                "total": 0,
                "page": 1,
                "page_size": 25
            }
        }


class PreviewMessageRequest(BaseModel):
    """Preview rendered message."""

    template_id: Optional[str] = Field(default=None, description="Template ID to render")
    contact_id: str = Field(description="Contact ID for variables")

    class Config:
        json_schema_extra = {
            "example": {
                "template_id": "tpl_123",
                "contact_id": "con_456"
            }
        }


class PreviewMessageResponse(BaseModel):
    """Message preview response."""

    rendered_message: str = Field(description="Rendered message text")
    rendered_elements: List[dict] = Field(default_factory=list, description="Rendered elements")

    class Config:
        json_schema_extra = {
            "example": {
                "rendered_message": "Hello John!",
                "rendered_elements": []
            }
        }
