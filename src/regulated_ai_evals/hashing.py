"""Canonical serialisation and content hashing.

Every identity in this framework is a content hash: golden sets, thresholds,
configurations, bundle files. Hashes only mean anything if two runs that agree
on content produce the same bytes, so serialisation is pinned here rather than
left to each caller's json.dumps defaults.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_ENCODING = "utf-8"


def canonical_bytes(obj: Any) -> bytes:
    """Serialise to the one byte sequence this framework considers canonical.

    sort_keys makes dict ordering irrelevant; the tight separators remove
    whitespace variation; ensure_ascii keeps the bytes stable across locales.
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode(_ENCODING)


def content_hash(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write_canonical(path: Path, obj: Any) -> str:
    """Write obj as canonical JSON and return its hash.

    Bundle files are written through here so that a bundle produced twice from
    the same run record is byte-identical, which is what makes `rae verify`
    a meaningful check rather than a formality.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(obj)
    path.write_bytes(payload)
    return "sha256:" + hashlib.sha256(payload).hexdigest()
