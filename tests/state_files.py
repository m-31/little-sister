"""A state file as a test reads and writes one by hand (ADR-0134): decoded by its
name — ``gzip -dc`` for a compressed one, as an operator reads it — and without the
generation every write of the layer stamps beside the file's tables."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from little_sister.state import BACKUP_SUFFIX, COMPRESSED_SUFFIX, GENERATION


def compressed(name: str) -> bool:
    """Whether a file of that name — a ``.bak`` beside one included — is compact
    JSON under gzip."""
    return name.removesuffix(BACKUP_SUFFIX).endswith(COMPRESSED_SUFFIX)


def encoded(name: str, payload: object) -> bytes:
    """``payload`` as a file of that name holds it, with no generation — what a
    test puts in a directory or a store by hand."""
    data = json.dumps(payload).encode("utf-8")
    return gzip.compress(data) if compressed(name) else data


def decoded(name: str, data: bytes) -> Any:
    """Everything a file of that name holds, its generation included."""
    return json.loads(gzip.decompress(data) if compressed(name) else data)


def tables(name: str, data: bytes) -> Any:
    """What a file of that name holds, without its generation: what its producer
    wrote."""
    payload = decoded(name, data)
    if isinstance(payload, dict):
        payload.pop(GENERATION, None)
    return payload


def on_disk(path: Path) -> Any:
    """What the file at ``path`` holds, without its generation."""
    return tables(path.name, path.read_bytes())
