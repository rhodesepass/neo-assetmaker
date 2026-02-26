"""Material asset data model.

Represents a downloadable material in the marketplace with metadata,
preview information, and download details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MaterialCategory(str, Enum):
    """Categories for material assets."""

    TEXTURE = "texture"
    MODEL_3D = "model_3d"
    SHADER = "shader"
    HDRI = "hdri"
    BRUSH = "brush"
    PRESET = "preset"
    PLUGIN = "plugin"
    OTHER = "other"

    @classmethod
    def from_string(cls, value: str) -> MaterialCategory:
        """Convert a string to a MaterialCategory, defaulting to OTHER."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.OTHER

    @property
    def display_name(self) -> str:
        """Return a human-readable display name."""
        names = {
            "texture": "Texture",
            "model_3d": "3D Model",
            "shader": "Shader",
            "hdri": "HDRI",
            "brush": "Brush",
            "preset": "Preset",
            "plugin": "Plugin",
            "other": "Other",
        }
        return names.get(self.value, self.value.title())


@dataclass
class Material:
    """Represents a material asset available in the marketplace.

    Attributes
    ----------
    id : str
        Unique server-side identifier (UUID string).
    name : str
        Display name of the material.
    operator_name : str
        Name of the operator/creator who uploaded the material.
    category : MaterialCategory
        Classification category.
    tags : list[str]
        Searchable tags associated with this material.
    file_hash : str
        SHA-256 hash of the file for integrity verification.
    file_size : int
        Size of the file in bytes.
    preview_image_path : str
        Server-side path for the thumbnail/preview image.
    created_at : datetime
        Timestamp when the material was uploaded.
    updated_at : datetime, optional
        Timestamp of the last update.
    description : str
        Optional description text.
    download_count : int
        Number of times this material has been downloaded.
    is_active : bool
        Whether the material is active (not soft-deleted).
    is_favorited : bool
        Client-side tracking of whether the current user has favorited this.
    """

    id: str
    name: str
    operator_name: str = ""
    category: MaterialCategory = MaterialCategory.OTHER
    tags: list[str] = field(default_factory=list)
    file_hash: str = ""
    file_size: int = 0
    preview_image_path: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    description: str = ""
    download_count: int = 0
    is_active: bool = True
    is_favorited: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Material:
        """Create a Material from a server response dictionary.

        Handles both the full ``MaterialResponse`` schema and partial
        dictionaries (e.g. from local cache).
        """
        category = data.get("category", "other")
        if isinstance(category, str):
            category = MaterialCategory.from_string(category)

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

        # Server returns UUID objects serialised as strings
        material_id = data.get("id", "")
        if material_id and not isinstance(material_id, str):
            material_id = str(material_id)

        return cls(
            id=material_id,
            name=data.get("name", ""),
            operator_name=data.get("operator_name", ""),
            category=category,
            tags=data.get("tags", []),
            file_hash=data.get("file_hash", ""),
            file_size=data.get("file_size", 0),
            preview_image_path=data.get("preview_image_path", ""),
            created_at=created_at,
            updated_at=updated_at,
            description=data.get("description", "") or "",
            download_count=data.get("download_count", 0),
            is_active=data.get("is_active", True),
            is_favorited=data.get("is_favorited", False),
        )

    def to_dict(self) -> dict:
        """Serialize to a dictionary suitable for JSON encoding."""
        return {
            "id": self.id,
            "name": self.name,
            "operator_name": self.operator_name,
            "category": self.category.value,
            "tags": self.tags,
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "preview_image_path": self.preview_image_path,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "description": self.description,
            "download_count": self.download_count,
            "is_active": self.is_active,
            "is_favorited": self.is_favorited,
        }

    @property
    def file_size_display(self) -> str:
        """Return a human-readable file size string."""
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        elif self.file_size < 1024 * 1024 * 1024:
            return f"{self.file_size / (1024 * 1024):.1f} MB"
        else:
            return f"{self.file_size / (1024 * 1024 * 1024):.2f} GB"
