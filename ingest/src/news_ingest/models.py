from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublisherProminence(Model):
    score: float = Field(ge=0.0, le=1.0)
    tier: Literal["high", "medium", "low"]
    evidence: str
    surface_id: str
    surface: Literal["homepage_rss", "latest_rss", "section_rss", "homepage"]
    position: int = Field(gt=0)
    snapshot_item_count: int = Field(gt=0)
    observed_at: datetime


class ArticleSnapshot(Model):
    schema_version: Literal[1] = 1
    source: str
    source_id: str
    content_type: str = "article"
    title: str
    raw_url: str
    canonical_url: str | None = None
    description: str | None = None
    description_source: str | None = None
    public_lead: str | None = None
    public_body: str | None = None
    public_body_truncated: bool = False
    language: str | None = None
    authors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    image_url: str | None = None
    image_credit: str | None = None
    image_description: str | None = None
    published_at: datetime
    modified_at: datetime | None = None
    timestamp_original: str
    timestamp_assumed_timezone: bool = False
    first_seen_at: datetime
    last_seen_at: datetime
    last_checked_at: datetime
    access_status: Literal["open", "partial", "metadata_only", "blocked", "unknown"] = "unknown"
    content_hash: str = ""
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    # Export-time summary of the strongest observed publisher-placement signal.
    # It is observational metadata and deliberately excluded from content_hash.
    publisher_prominence: PublisherProminence | None = None


class MergeRepresentative(Model):
    sighting_id: int = Field(gt=0)
    article: ArticleSnapshot


class FeedMergeState(Model):
    # Version 2 adds revised_at; a cached version-1 state fails validation and is rebuilt.
    schema_version: Literal[2] = 2
    source: str
    source_id: str
    feed_id: str
    representatives: list[MergeRepresentative] = Field(min_length=1, max_length=10)
    categories: list[str]
    keywords: list[str]
    first_seen_at: datetime
    last_seen_at: datetime
    last_checked_at: datetime
    # When each field's value last changed within this feed (key "snapshot" for the content of
    # the winning observation). Absent: the value has not changed since the feed introduced it.
    revised_at: dict[str, datetime] = Field(default_factory=dict)


class AppearanceRecord(Model):
    schema_version: Literal[1] = 1
    poll_id: int
    source: str
    source_id: str
    surface_id: str
    surface: Literal["homepage_rss", "latest_rss", "section_rss", "homepage"]
    surface_section: str | None = None
    position: int
    publisher_order: int | None = None
    is_super_article: bool | None = None
    observed_at: datetime
    snapshot_item_count: int = Field(gt=0)
    prominence_score: float = Field(ge=0.0, le=1.0)
    prominence_tier: Literal["high", "medium", "low"]
    prominence_evidence: str
