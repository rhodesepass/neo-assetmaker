from __future__ import annotations

import base64
import hashlib
import secrets


def _generate_code_verifier(length: int = 128) -> str:
    return secrets.token_urlsafe(length)[:length]


def _generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
