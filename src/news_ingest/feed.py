from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import feedparser
from selectolax.parser import HTMLParser

from .config import FeedConfig, SourceConfig
from .identity import resolve_source_id
from .models import ArticleSnapshot
from .time import parse_feed_timestamp
from .urls import normalize_url


class ItemError(ValueError):
    pass


@dataclass
class EntryContext:
    source: str
    source_config: SourceConfig
    feed_config: FeedConfig
    observed_at: datetime
    position: int


@dataclass
class SightingCandidate:
    article: ArticleSnapshot
    feed_id: str
    position: int
    publisher_order: int | None
    raw_item: dict


@dataclass
class ParsedFeed:
    entries: list[SightingCandidate]
    invalid: list[tuple[int, str, dict]]
    raw_item_count: int
    parsed_item_count: int
    warnings: list[str]
    feed_last_build_date: str | None


def clean_text(value: Any, *, required: bool = False) -> str | None:
    if value is None:
        result = None
    else:
        fragment = HTMLParser(str(value))
        result = fragment.text(separator=" ") if fragment else str(value)
        result = (
            " ".join(
                unicodedata.normalize("NFC", html.unescape(result)).replace("\xa0", " ").split()
            )
            or None
        )
    if required and not result:
        raise ItemError("required text missing")
    return result


def json_safe_feedparser_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): json_safe_feedparser_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_feedparser_value(v) for v in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _entry_value(entry: Mapping, *keys: str) -> Any:
    for key in keys:
        if entry.get(key) is not None:
            return entry[key]
    return None


def _strings(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [text for item in values if (text := clean_text(item))]


def normalize_entry(entry: Mapping[str, Any], context: EntryContext) -> SightingCandidate:
    title = clean_text(_entry_value(entry, "title"), required=True)
    raw_url = str(_entry_value(entry, "link") or "").strip()
    canonical = normalize_url(context.source, raw_url)
    source_id = resolve_source_id(context.source_config, entry, raw_url)
    original = clean_text(_entry_value(entry, "published", "pubDate"), required=True)
    published = parse_feed_timestamp(original)
    tags = entry.get("tags") or []
    categories = sorted(
        {
            clean_text(tag.get("term"))
            for tag in tags
            if isinstance(tag, Mapping) and clean_text(tag.get("term"))
        }
    )
    authors = []
    for item in entry.get("authors") or []:
        if isinstance(item, Mapping) and (name := clean_text(item.get("name"))):
            authors.append(name)
    authors += _strings(_entry_value(entry, "author", "dc_creator"))
    authors = list(dict.fromkeys(authors))
    image = None
    for key in ("media_thumbnail", "media_content", "enclosures"):
        values = entry.get(key) or []
        if isinstance(values, Mapping):
            values = [values]
        for value in values:
            if isinstance(value, Mapping) and value.get("url"):
                try:
                    image = normalize_url(context.source, str(value["url"]))
                    break
                except ValueError:
                    pass
        if image:
            break
    po = entry.get("pol_order") or entry.get("order")
    try:
        publisher_order = int(po) if po is not None else None
    except (TypeError, ValueError):
        publisher_order = None
    access = "metadata_only" if context.source in {"nytimes", "ft"} else "unknown"
    article = ArticleSnapshot(
        source=context.source,
        source_id=source_id,
        title=title,
        raw_url=raw_url,
        canonical_url=canonical,
        description=clean_text(_entry_value(entry, "summary", "description")),
        description_source=context.feed_config.id,
        language=context.source_config.language,
        authors=authors,
        categories=categories,
        keywords=[],
        image_url=image,
        published_at=published,
        timestamp_original=original,
        first_seen_at=context.observed_at,
        last_seen_at=context.observed_at,
        last_checked_at=context.observed_at,
        access_status=access,
        raw_metadata=json_safe_feedparser_value(entry),
    )
    return SightingCandidate(
        article,
        context.feed_config.id,
        context.position,
        publisher_order,
        json_safe_feedparser_value(entry),
    )


def parse_feed(
    payload: bytes,
    feed_config: FeedConfig,
    observed_at: datetime,
    source: str = "",
    source_config: SourceConfig | None = None,
) -> ParsedFeed:
    raw_count = len(re.findall(rb"<item(?:\s|>)", payload, re.IGNORECASE))
    parsed = feedparser.parse(payload)
    warnings = ["bozo:" + str(parsed.bozo_exception)] if getattr(parsed, "bozo", False) else []
    if not getattr(parsed, "entries", []) and raw_count:
        raise ItemError("raw items found but no parsed entries")
    if not getattr(parsed, "feed", None) and not getattr(parsed, "entries", None):
        raise ItemError("unrecognized RSS")
    entries = []
    invalid = []
    if source_config is None:
        raise ItemError("source configuration required")
    for pos, entry in enumerate(parsed.entries, 1):
        raw = json_safe_feedparser_value(entry)
        try:
            entries.append(
                normalize_entry(
                    entry, EntryContext(source, source_config, feed_config, observed_at, pos)
                )
            )
        except Exception as exc:  # noqa: BLE001 -- malformed siblings are quarantined independently.
            invalid.append((pos, str(exc), raw))
    return ParsedFeed(
        entries,
        invalid,
        raw_count,
        len(parsed.entries),
        warnings,
        parsed.feed.get("updated") or parsed.feed.get("published"),
    )
