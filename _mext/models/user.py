"""User data model for the asset store client.

Represents the authenticated user with role, FIDO2 credential state,
and profile information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class UserRole(str, Enum):
    """User roles in the asset store system.

    Values must match the ``role`` column values on the server User model.
    """

    USER = "user"
    CREATOR = "creator"
    ADMIN = "admin"

    @classmethod
    def from_string(cls, value: str) -> UserRole:
        """Convert a string to a UserRole, defaulting to USER."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.USER

    @property
    def display_name(self) -> str:
        """Return a human-readable display name."""
        return self.value.title()

    @property
    def can_upload(self) -> bool:
        """Return True if this role allows uploading materials."""
        return self in (UserRole.CREATOR, UserRole.ADMIN)

    @property
    def can_manage_users(self) -> bool:
        """Return True if this role allows user management."""
        return self == UserRole.ADMIN


class Fido2Mode(str, Enum):
    """FIDO2 usage mode for authentication.

    Values must match the ``fido2_mode`` column values on the server
    User model: ``"2fa"`` or ``"passwordless"``.
    """

    DISABLED = "disabled"
    SECOND_FACTOR = "2fa"
    PASSWORDLESS = "passwordless"

    @classmethod
    def from_string(cls, value: str) -> Fido2Mode:
        """Convert a string to a Fido2Mode, defaulting to DISABLED."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.DISABLED


@dataclass
class Fido2Credential:
    """Represents a registered FIDO2 credential for a user.

    Field names are aligned with the server's ``Fido2CredentialResponse``
    schema which returns ``id``, ``name``, ``created_at``, ``last_used_at``,
    ``transports``, and ``is_discoverable``.
    """

    credential_id: str
    name: str = "Security Key"
    created_at: datetime = field(default_factory=datetime.now)
    last_used: Optional[datetime] = None
    transports: list = field(default_factory=list)
    is_discoverable: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Fido2Credential:
        """Create from a server response dictionary.

        Handles both ``id`` (from Fido2CredentialResponse) and
        ``credential_id`` as fallback for the credential identifier.
        Handles both ``last_used_at`` (server) and ``last_used`` as
        fallback for the last-used timestamp.
        """
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_at = datetime.now()
        elif not isinstance(created_at, datetime):
            created_at = datetime.now()

        # Server schema uses "last_used_at"
        last_used = data.get("last_used_at") or data.get("last_used")
        if isinstance(last_used, str):
            try:
                last_used = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                last_used = None

        # Server schema returns "id" (UUID), not "credential_id"
        credential_id = str(data.get("id", data.get("credential_id", "")))

        return cls(
            credential_id=credential_id,
            name=data.get("name", "Security Key"),
            created_at=created_at,
            last_used=last_used,
            transports=data.get("transports", []),
            is_discoverable=data.get("is_discoverable", False),
        )


@dataclass
class User:
    """Represents an authenticated user.

    Attributes
    ----------
    id : str
        Unique server-side identifier.
    username : str
        The user's login name.
    email : str
        The user's email address.
    role : UserRole
        The user's role/permission level.
    fido2_enabled : bool
        Whether the user has any FIDO2 credentials registered.
    fido2_mode : Fido2Mode
        How FIDO2 is used for this user's authentication.
    fido2_credentials : list[Fido2Credential]
        List of registered FIDO2 credentials.
    display_name : str
        Optional display name.
    avatar_url : str
        URL for the user's avatar image.
    created_at : datetime
        When the account was created.
    """

    id: str
    username: str
    email: str = ""
    role: UserRole = UserRole.USER
    fido2_enabled: bool = False
    fido2_mode: Fido2Mode = Fido2Mode.DISABLED
    fido2_credentials: list[Fido2Credential] = field(default_factory=list)
    display_name: str = ""
    avatar_url: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_dict(cls, data: dict) -> User:
        """Create a User from a server response dictionary."""
        role = data.get("role", "user")
        if isinstance(role, str):
            role = UserRole.from_string(role)

        fido2_mode = data.get("fido2_mode", "disabled")
        if isinstance(fido2_mode, str):
            fido2_mode = Fido2Mode.from_string(fido2_mode)

        credentials = [Fido2Credential.from_dict(c) for c in data.get("fido2_credentials", [])]

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                created_at = datetime.now()
        elif not isinstance(created_at, datetime):
            created_at = datetime.now()

        return cls(
            id=data.get("id", ""),
            username=data.get("username", ""),
            email=data.get("email", ""),
            role=role,
            fido2_enabled=data.get("fido2_enabled", False),
            fido2_mode=fido2_mode,
            fido2_credentials=credentials,
            display_name=data.get("display_name", ""),
            avatar_url=data.get("avatar_url", ""),
            created_at=created_at,
        )

    def to_dict(self) -> dict:
        """Serialize to a dictionary."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role.value,
            "fido2_enabled": self.fido2_enabled,
            "fido2_mode": self.fido2_mode.value,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "created_at": self.created_at.isoformat(),
        }

    @property
    def initials(self) -> str:
        """Return initials from display_name or username for avatar fallback."""
        name = self.display_name or self.username
        parts = name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return name[:2].upper() if name else "??"
