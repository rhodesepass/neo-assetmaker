"""Cryptographic utility functions for the asset store.

Provides SHA-256 hashing for file integrity verification of downloaded
materials and data validation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 hex digest of a file.

    Parameters
    ----------
    path : str or Path
        Path to the file to hash.
    chunk_size : int
        Number of bytes to read per iteration. Default is 64 KB.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    PermissionError
        If the file cannot be read.
    """
    path = Path(path)
    hasher = hashlib.sha256()

    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)

    return hasher.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Compute the SHA-256 hex digest of a byte string.

    Parameters
    ----------
    data : bytes
        The data to hash.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(data).hexdigest()
