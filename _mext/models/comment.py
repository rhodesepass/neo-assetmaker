"""Comment data model for material discussions.

Represents a user comment on a material, with metadata for
display and ownership tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Comment:
    """A user comment on a material.

    Attributes
    ----------
    id : str
        Unique server-side identifier.
    material_id : str
        ID of the material this comment belongs to.
    user_id : str
        ID of the commenter.
    username : str
        Display name of the commenter.
    user_avatar_url : str
        URL for the commenter's avatar image.
    content : str
        Comment text content.
    created_at : datetime
        When the comment was posted.
    updated_at : datetime, optional
        When the comment was last edited.
    is_own : bool
        Whether the current user authored this comment (controls delete button).
    """

    id: str
    material_id: str
    user_id: str
    username: str
    user_avatar_url: str = ""
    content: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    is_own: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Comment:
        """Create a Comment from a server response dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_at = datetime.now()
        elif not isinstance(created_at, datetime):
            created_at = datetime.now()

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                updated_at = None

        comment_id = data.get("id", "")
        if comment_id and not isinstance(comment_id, str):
            comment_id = str(comment_id)

        return cls(
            id=comment_id,
            material_id=data.get("material_id", ""),
            user_id=data.get("user_id", ""),
            username=data.get("username", ""),
            user_avatar_url=data.get("user_avatar_url", ""),
            content=data.get("content", ""),
            created_at=created_at,
            updated_at=updated_at,
            is_own=data.get("is_own", False),
        )

    def to_dict(self) -> dict:
        """Serialize to a dictionary suitable for JSON encoding."""
        return {
            "id": self.id,
            "material_id": self.material_id,
            "user_id": self.user_id,
            "username": self.username,
            "user_avatar_url": self.user_avatar_url,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_own": self.is_own,
        }
