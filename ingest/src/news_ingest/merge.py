from __future__ import annotations

from .feed import SightingCandidate
from .hashing import content_hash
from .models import ArticleSnapshot


class MergeAccumulator:
    """Retain field winners and aggregates, without retaining every historical sighting."""

    fields = (
        "title",
        "raw_url",
        "canonical_url",
        "description",
        "description_source",
        "image_url",
        "language",
        "timestamp_original",
        "published_at",
    )

    def __init__(self, feed_priorities: dict[str, tuple[int, int]]):
        self.priorities = feed_priorities
        self.winner: SightingCandidate | None = None
        self.chosen: dict[str, SightingCandidate] = {}
        self.categories: set[str] = set()
        self.keywords: set[str] = set()
        self.first_seen_at = self.last_seen_at = self.last_checked_at = None

    def rank(self, s):
        return (
            self.priorities[s.feed_id][0],
            s.article.last_seen_at,
            -self.priorities[s.feed_id][1],
            s.feed_id,
        )

    def add(self, sighting: SightingCandidate) -> None:
        rank = self.rank(sighting)
        # Strict comparisons preserve the first sighting when ranks tie, as max() did.
        if self.winner is None or rank > self.rank(self.winner):
            self.winner = sighting
        article = sighting.article
        for field in self.fields:
            previous = self.chosen.get(field)
            if getattr(article, field) not in (None, "") and (
                previous is None or rank > self.rank(previous)
            ):
                self.chosen[field] = sighting
        self.categories.update(article.categories)
        self.keywords.update(article.keywords)
        self.first_seen_at = (
            min(self.first_seen_at, article.first_seen_at)
            if self.first_seen_at is not None
            else article.first_seen_at
        )
        self.last_seen_at = (
            max(self.last_seen_at, article.last_seen_at)
            if self.last_seen_at is not None
            else article.last_seen_at
        )
        self.last_checked_at = (
            max(self.last_checked_at, article.last_checked_at)
            if self.last_checked_at is not None
            else article.last_checked_at
        )

    def snapshot(self) -> ArticleSnapshot:
        if self.winner is None:
            raise ValueError("no sightings")
        base = self.winner.article.model_copy(deep=True)
        for field in self.fields:
            chosen = self.chosen.get(field)
            if chosen is None:
                continue
            setattr(base, field, getattr(chosen.article, field))
            if field == "description":
                base.description_source = chosen.feed_id
        base.authors = list(dict.fromkeys(self.winner.article.authors))
        base.categories = sorted(self.categories)
        base.keywords = sorted(self.keywords)
        base.first_seen_at = self.first_seen_at
        base.last_seen_at = self.last_seen_at
        base.last_checked_at = self.last_checked_at
        base.content_hash = content_hash(base)
        return base


def merge_sightings(
    sightings: list[SightingCandidate], feed_priorities: dict[str, tuple[int, int]]
) -> ArticleSnapshot:
    state = MergeAccumulator(feed_priorities)
    for sighting in sightings:
        state.add(sighting)
    return state.snapshot()
