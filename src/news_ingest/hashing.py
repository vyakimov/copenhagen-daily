from __future__ import annotations

import hashlib
import json

from .models import ArticleSnapshot

HASH_FIELDS = (
    "schema_version",
    "source",
    "source_id",
    "content_type",
    "title",
    "canonical_url",
    "description",
    "description_source",
    "public_lead",
    "public_body",
    "public_body_truncated",
    "language",
    "authors",
    "categories",
    "keywords",
    "image_url",
    "image_credit",
    "image_description",
    "published_at",
    "modified_at",
    "timestamp_original",
    "timestamp_assumed_timezone",
    "access_status",
)


def hashed_dict(article: ArticleSnapshot | dict) -> dict:
    value = (
        article.model_dump(mode="json") if isinstance(article, ArticleSnapshot) else dict(article)
    )
    out = {key: value.get(key) for key in HASH_FIELDS}
    for key in ("categories", "keywords"):
        out[key] = sorted(set(out[key] or []))
    return out


def content_hash(article: ArticleSnapshot | dict) -> str:
    payload = json.dumps(
        hashed_dict(article), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()
