from __future__ import annotations

import re
from collections.abc import Mapping
from uuid import UUID

from .config import SourceConfig
from .urls import normalize_url


class IdentityError(ValueError):
    pass


def _value(entry: Mapping, *keys: str) -> str | None:
    for key in keys:
        value = entry.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def resolve_source_id(source: str | SourceConfig, entry: Mapping, raw_url: str) -> str:
    policy = (
        source.identity
        if isinstance(source, SourceConfig)
        else {
            "nytimes": "guid",
            "ft": "uuid_guid",
            "borsen": "guid_or_url",
            "politiken": "url_regex",
            "berlingske": "guid",
            "dr": "guid",
        }[source]
    )
    guid = _value(entry, "id", "guid")
    if policy == "guid":
        if not guid:
            raise IdentityError("missing GUID")
        return guid
    if policy == "uuid_guid":
        if not guid:
            raise IdentityError("missing UUID GUID")
        try:
            return str(UUID(guid))
        except ValueError as exc:
            raise IdentityError("invalid UUID GUID") from exc
    if policy == "guid_or_url":
        return guid or normalize_url("borsen", raw_url)
    pattern = source.identity_pattern if isinstance(source, SourceConfig) else r"art([0-9]+)"
    match = re.search(pattern or "", raw_url)
    if match:
        return match.group(1) if match.groups() else match.group(0)
    if guid:
        return guid
    raise IdentityError("no URL identity or GUID")
