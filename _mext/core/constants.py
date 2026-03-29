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

# Gallery / Waterfall
GALLERY_CARD_COLUMN_WIDTH: int = 260    # 瀑布流默认列宽
THUMBNAIL_CACHE_SIZE: int = 200         # LRU 缓存最大条目
THUMBNAIL_CONCURRENT_LOADS: int = 6     # 并发缩略图加载数
MATERIALS_PER_PAGE: int = 20            # 每页素材数量
