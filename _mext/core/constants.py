"""Application-wide constants for the asset store."""

import base64 as _b64

# Application identity
APP_NAME: str = "AssetStore"
APP_ID: str = "com.assetstore.app"
APP_DISPLAY_NAME: str = "Asset Store"
APP_AUTHOR: str = "AssetStore"

# API configuration
API_VERSION: str = "v1"
_p = ["aHR0cHM6Ly9hcGk", "ubWF0ZXJpYWwtbW", "Fya2V0LmV4YW1w", "bGUuY29t"]
API_BASE_URL: str = _b64.b64decode("".join(_p)).decode()
API_TIMEOUT_SECONDS: int = 30
API_STREAM_TIMEOUT_SECONDS: int = 300

# OAuth / DRM login
OAUTH_REDIRECT_PORT: int = 23456
OAUTH_REDIRECT_HOST: str = "127.0.0.1"
OAUTH_REDIRECT_URI: str = f"http://{OAUTH_REDIRECT_HOST}:{OAUTH_REDIRECT_PORT}/callback"
OAUTH_STATE_LENGTH: int = 32
OAUTH_CODE_VERIFIER_LENGTH: int = 64

# FIDO2 / WebAuthn
_r = ["bWF0ZXJpYWwtbW", "Fya2V0LmV4YW1w", "bGUuY29t"]
FIDO2_RP_ID: str = _b64.b64decode("".join(_r)).decode()
FIDO2_RP_NAME: str = "Asset Store"
FIDO2_ORIGIN: str = "https://" + FIDO2_RP_ID

# Downloads
MAX_CONCURRENT_DOWNLOADS: int = 3
DOWNLOAD_CHUNK_SIZE: int = 1024 * 64  # 64 KB
DOWNLOAD_TEMP_SUFFIX: str = ".tmp"

# USB / MTP
USB_POLL_INTERVAL_MS: int = 2000
MTP_SESSION_ID: int = 1
MTP_CONTAINER_HEADER_SIZE: int = 12

# Electric Pass MTP storage IDs
ELECTRIC_PASS_STORAGE_IDS: dict[str, int] = {
    "slot_1": 0xFFFF0001,
    "slot_2": 0xFFFF0002,
    "slot_3": 0xFFFF0003,
    "slot_4": 0xFFFF0004,
    "slot_5": 0xFFFF0005,
    "slot_6": 0xFFFF0006,
}

# Keyring
KEYRING_SERVICE_NAME: str = "AssetStore"
KEYRING_REFRESH_TOKEN_KEY: str = "refresh_token"
KEYRING_ACCESS_TOKEN_KEY: str = "access_token"

# UI
DEFAULT_WINDOW_WIDTH: int = 1200
DEFAULT_WINDOW_HEIGHT: int = 800
SEARCH_DEBOUNCE_MS: int = 350
MATERIAL_CARD_WIDTH: int = 220
MATERIAL_CARD_HEIGHT: int = 280
