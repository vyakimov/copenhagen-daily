"""Strict, secret-free configuration loading."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class ConfigError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HttpConfig(StrictModel):
    timeout_seconds: int = Field(gt=0)
    attempts: int = Field(gt=0)
    max_connections_per_host: int = Field(gt=0)
    user_agent: str = Field(min_length=1)


class FeedConfig(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: HttpUrl
    surface: Literal["homepage_rss", "latest_rss", "section_rss"]
    order: int = Field(ge=0)
    description_priority: int = Field(ge=0)

    @model_validator(mode="after")
    def https_only(self):
        if self.url.scheme != "https":
            raise ValueError("feed URL must use HTTPS")
        return self


class HomepageConfig(StrictModel):
    id: str = Field(min_length=1)
    url: HttpUrl
    surface: Literal["homepage"]


class SourceConfig(StrictModel):
    enabled: bool
    identity: Literal["guid", "uuid_guid", "guid_or_url", "url_regex"]
    identity_pattern: str | None = None
    language: str | None = None
    merge_across_feeds: bool = True
    fetch_article_pages: bool = False
    fetch_public_body: bool = False
    capture_homepage_placement: bool = False
    homepage: HomepageConfig | None = None
    feeds: list[FeedConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def source_rules(self):
        if self.identity == "url_regex":
            if not self.identity_pattern:
                raise ValueError("url_regex identity needs identity_pattern")
            try:
                re.compile(self.identity_pattern)
            except re.error as exc:
                raise ValueError("identity_pattern does not compile") from exc
        elif self.identity_pattern:
            raise ValueError("identity_pattern is only valid for url_regex")
        if self.fetch_public_body and not self.fetch_article_pages:
            raise ValueError("fetch_public_body requires fetch_article_pages")
        if self.capture_homepage_placement and not self.homepage:
            raise ValueError("homepage capture requires homepage configuration")
        ids = [f.id for f in self.feeds]
        if len(ids) != len(set(ids)) or len({f.order for f in self.feeds}) != len(self.feeds):
            raise ValueError("duplicate feed IDs or feed orders")
        return self


class AppConfig(StrictModel):
    schema_version: Literal[1]
    database_path: str
    lock_path: str
    poll_interval_seconds: int = Field(gt=0)
    homepage_poll_interval_seconds: int = Field(gt=0)
    export_default_lookback_hours: int = Field(gt=0)
    raw_payload_retention_days: int | None = Field(default=None, gt=0)
    # compact-history leaves everything observed within this many days exactly as collected.
    compact_after_days: int = Field(default=7, gt=0)
    max_response_bytes: int = Field(gt=0)
    max_public_body_characters: int = Field(gt=0)
    failure_alert_threshold: int = Field(gt=0)
    # `health` reports the database as degraded when its seven-day growth exceeds this.
    database_growth_alert_mb_per_day: int = Field(default=250, gt=0)
    item_count_drop_warning_percent: int = Field(ge=0, le=100)
    http: HttpConfig
    sources: dict[str, SourceConfig]

    @model_validator(mode="after")
    def rules(self):
        if not self.sources:
            raise ValueError("at least one source is required")
        if self.sources.get("nytimes") and self.sources["nytimes"].fetch_article_pages:
            raise ValueError("NYT article page fetching is permanently disabled")
        urls = [str(f.url) for s in self.sources.values() for f in s.feeds]
        ids = [f.id for s in self.sources.values() for f in s.feeds]
        if len(urls) != len(set(urls)) or len(ids) != len(set(ids)):
            raise ValueError("duplicate feed URL or feed ID")
        return self

    def enabled_sources(self) -> dict[str, SourceConfig]:
        return {key: value for key, value in self.sources.items() if value.enabled}

    def enabled_feeds(
        self, source: str | None = None
    ) -> list[tuple[str, SourceConfig, FeedConfig]]:
        return [
            (sid, sc, feed)
            for sid, sc in self.enabled_sources().items()
            if source is None or sid == source
            for feed in sc.feeds
        ]


def config_hash(config: AppConfig) -> str:
    raw = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def load_config(path: str | Path = "config/sources.yaml") -> AppConfig:
    path = Path(path).resolve()
    try:
        data = yaml.safe_load(path.read_text())
        config = AppConfig.model_validate(data)
    except Exception as exc:
        raise ConfigError(str(exc)) from exc
    root = path.parent.parent.resolve()
    for configured in (config.database_path, config.lock_path):
        target = (
            (root / configured).resolve()
            if not Path(configured).is_absolute()
            else Path(configured).resolve()
        )
        if target != root and root not in target.parents:
            raise ConfigError(f"runtime path outside repository: {configured}")
    return config
