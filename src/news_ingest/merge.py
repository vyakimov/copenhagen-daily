from __future__ import annotations

from .feed import SightingCandidate
from .hashing import content_hash
from .models import ArticleSnapshot


def merge_sightings(
    sightings: list[SightingCandidate], feed_priorities: dict[str, tuple[int, int]]
) -> ArticleSnapshot:
    if not sightings:
        raise ValueError("no sightings")

    # Highest priority, most recently seen, lower configured order, then ID.
    def rank(s):
        return (
            feed_priorities[s.feed_id][0],
            s.article.last_seen_at,
            -feed_priorities[s.feed_id][1],
            s.feed_id,
        )

    winner = max(sightings, key=rank)
    base = winner.article.model_copy(deep=True)
    for field in (
        "title",
        "raw_url",
        "canonical_url",
        "description",
        "description_source",
        "image_url",
        "language",
        "timestamp_original",
        "published_at",
    ):
        candidates = [s for s in sightings if getattr(s.article, field) not in (None, "")]
        if candidates:
            chosen = max(candidates, key=rank)
            setattr(base, field, getattr(chosen.article, field))
            if field == "description":
                base.description_source = chosen.feed_id
    base.authors = list(dict.fromkeys(max(sightings, key=rank).article.authors))
    base.categories = sorted({x for s in sightings for x in s.article.categories})
    base.keywords = sorted({x for s in sightings for x in s.article.keywords})
    base.first_seen_at = min(s.article.first_seen_at for s in sightings)
    base.last_seen_at = max(s.article.last_seen_at for s in sightings)
    base.last_checked_at = max(s.article.last_checked_at for s in sightings)
    base.raw_metadata = max(sightings, key=rank).article.raw_metadata
    base.content_hash = content_hash(base)
    return base
