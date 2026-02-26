"""Application configuration using platformdirs for cross-platform paths.

Handles config directory resolution, .env file loading, and runtime settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from platformdirs import user_cache_dir, user_config_dir, user_downloads_dir

from _mext.core.constants import (
    API_BASE_URL,
    API_STREAM_TIMEOUT_SECONDS,
    API_TIMEOUT_SECONDS,
    APP_AUTHOR,
    APP_NAME,
    FIDO2_ORIGIN,
    FIDO2_RP_ID,
    FIDO2_RP_NAME,
    MAX_CONCURRENT_DOWNLOADS,
    OAUTH_REDIRECT_PORT,
)


def _load_env_file(env_path: Path) -> dict[str, str]:
    """Load a .env file and return key-value pairs.

    Supports:
      - Lines with KEY=VALUE
      - Quoted values (single or double)
      - Comments starting with #
      - Blank lines
    """
    env_vars: dict[str, str] = {}
    if not env_path.is_file():
        return env_vars

    with open(env_path, "r", encoding="utf-8") as fh:
        for line_number, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]

            env_vars[key] = value

    return env_vars


@dataclass
class Config:
    """Central configuration object for the asset store client.

    Reads defaults from constants, overrides from .env file and environment
    variables. Ensures all required directories exist on creation.
    """

    # Directories
    config_dir: Path = field(default_factory=lambda: Path(user_config_dir(APP_NAME, APP_AUTHOR)))
    cache_dir: Path = field(default_factory=lambda: Path(user_cache_dir(APP_NAME, APP_AUTHOR)))
    download_dir: Path = field(default_factory=lambda: Path(user_downloads_dir()) / APP_NAME)

    # API
    api_base_url: str = API_BASE_URL
    api_timeout: int = API_TIMEOUT_SECONDS
    api_stream_timeout: int = API_STREAM_TIMEOUT_SECONDS

    # OAuth
    oauth_redirect_port: int = OAUTH_REDIRECT_PORT

    # FIDO2
    fido2_origin: str = FIDO2_ORIGIN
    fido2_rp_id: str = FIDO2_RP_ID
    fido2_rp_name: str = FIDO2_RP_NAME

    # Downloads
    max_concurrent_downloads: int = MAX_CONCURRENT_DOWNLOADS

    # Runtime state (not persisted)
    _env_loaded: bool = field(default=False, repr=False, init=False)

    def __post_init__(self) -> None:
        """Ensure required directories exist and load .env overrides."""
        self._ensure_directories()
        self._load_overrides()

    def _ensure_directories(self) -> None:
        """Create configuration, cache, and download directories if missing."""
        for directory in (self.config_dir, self.cache_dir, self.download_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def _load_overrides(self) -> None:
        """Load overrides from .env file and environment variables.

        Priority: environment variables > .env file > defaults.
        """
        env_path = self.config_dir / ".env"
        file_vars = _load_env_file(env_path)

        # Also check project-local .env
        local_env = Path.cwd() / ".env"
        local_vars = _load_env_file(local_env)

        # Merge: local .env < config .env < real env vars
        merged = {**local_vars, **file_vars}

        # Apply overrides
        self.api_base_url = os.environ.get(
            "MM_API_BASE_URL", merged.get("MM_API_BASE_URL", self.api_base_url)
        )
        self.api_timeout = int(
            os.environ.get("MM_API_TIMEOUT", merged.get("MM_API_TIMEOUT", str(self.api_timeout)))
        )
        self.api_stream_timeout = int(
            os.environ.get(
                "MM_API_STREAM_TIMEOUT",
                merged.get("MM_API_STREAM_TIMEOUT", str(self.api_stream_timeout)),
            )
        )
        self.oauth_redirect_port = int(
            os.environ.get(
                "MM_OAUTH_PORT",
                merged.get("MM_OAUTH_PORT", str(self.oauth_redirect_port)),
            )
        )
        self.fido2_origin = os.environ.get(
            "MM_FIDO2_ORIGIN", merged.get("MM_FIDO2_ORIGIN", self.fido2_origin)
        )
        self.fido2_rp_id = os.environ.get(
            "MM_FIDO2_RP_ID", merged.get("MM_FIDO2_RP_ID", self.fido2_rp_id)
        )
        self.max_concurrent_downloads = int(
            os.environ.get(
                "MM_MAX_DOWNLOADS",
                merged.get("MM_MAX_DOWNLOADS", str(self.max_concurrent_downloads)),
            )
        )

        download_override = os.environ.get("MM_DOWNLOAD_DIR", merged.get("MM_DOWNLOAD_DIR"))
        if download_override:
            self.download_dir = Path(download_override)
            self.download_dir.mkdir(parents=True, exist_ok=True)

        self._env_loaded = True

    @property
    def api_url(self) -> str:
        """Return the full API base URL including the ``/api/vN/`` prefix.

        The trailing slash is required so that httpx correctly resolves
        relative request paths (e.g. ``auth/login``).
        """
        from _mext.core.constants import API_VERSION

        return f"{self.api_base_url.rstrip('/')}/api/{API_VERSION}/"

    @property
    def oauth_redirect_uri(self) -> str:
        """Return the OAuth redirect URI built from configured port."""
        return f"http://127.0.0.1:{self.oauth_redirect_port}/callback"

    def get_temp_download_path(self, filename: str) -> Path:
        """Return a temporary download path for a file."""
        from _mext.core.constants import DOWNLOAD_TEMP_SUFFIX

        return self.download_dir / f"{filename}{DOWNLOAD_TEMP_SUFFIX}"

    def get_final_download_path(self, filename: str) -> Path:
        """Return the final download path for a file."""
        return self.download_dir / filename


# Module-level singleton (lazy)
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """Return the global Config singleton, creating it on first access."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def reset_config() -> None:
    """Reset the global Config singleton (primarily for testing)."""
    global _config_instance
    _config_instance = None
