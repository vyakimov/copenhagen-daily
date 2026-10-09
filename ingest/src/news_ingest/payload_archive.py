"""Pure packing of raw feed bodies into one xz archive, verified body by body."""

from __future__ import annotations

import hashlib
import lzma


def body_hash(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def pack(bodies: list[tuple[str, bytes]]) -> tuple[bytes, list[tuple[str, int, int]]]:
    """Concatenate bodies in the given order. Returns the archive and (hash, offset, length)."""
    members = []
    offset = 0
    for content_hash, body in bodies:
        if body_hash(body) != content_hash:
            raise ValueError("raw payload does not match its content hash")
        members.append((content_hash, offset, len(body)))
        offset += len(body)
    archive = lzma.compress(b"".join(body for _, body in bodies), format=lzma.FORMAT_XZ)
    verify(archive, members)
    return archive, members


def unpack(archive: bytes) -> bytes:
    return lzma.decompress(archive, format=lzma.FORMAT_XZ)


def verify(archive: bytes, members: list[tuple[str, int, int]]) -> None:
    """Every member must reproduce its own hash from the archive, and the archive holds no more."""
    data = unpack(archive)
    end = 0
    for content_hash, offset, length in sorted(members, key=lambda member: member[1]):
        if offset != end or body_hash(data[offset : offset + length]) != content_hash:
            raise ValueError("raw payload archive does not reproduce its members")
        end = offset + length
    if end != len(data):
        raise ValueError("raw payload archive holds unindexed bytes")


def extract(archive: bytes, offset: int, length: int, content_hash: str) -> bytes:
    body = unpack(archive)[offset : offset + length]
    if body_hash(body) != content_hash:
        raise ValueError("archived raw payload does not match its content hash")
    return body
