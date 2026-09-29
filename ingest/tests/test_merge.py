from datetime import UTC, datetime, timedelta
from random import Random

from news_ingest.feed import SightingCandidate
from news_ingest.hashing import content_hash
from news_ingest.merge import MergeAccumulator, merge_sightings
from news_ingest.models import ArticleSnapshot


def historical_reference(sightings, priorities):
    """The pre-accumulator merge algorithm, retained as an independent equivalence oracle."""

    def rank(s):
        return (
            priorities[s.feed_id][0],
            s.article.last_seen_at,
            -priorities[s.feed_id][1],
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
    base.authors = list(dict.fromkeys(winner.article.authors))
    base.categories = sorted({value for s in sightings for value in s.article.categories})
    base.keywords = sorted({value for s in sightings for value in s.article.keywords})
    base.first_seen_at = min(s.article.first_seen_at for s in sightings)
    base.last_seen_at = max(s.article.last_seen_at for s in sightings)
    base.last_checked_at = max(s.article.last_checked_at for s in sightings)
    base.content_hash = content_hash(base)
    return base


def test_streaming_merge_matches_historical_algorithm_at_every_prefix():
    random = Random(1927)
    priorities = {"latest": (10, 0), "section-a": (20, 1), "section-b": (20, 1)}
    base = datetime(2026, 9, 29, tzinfo=UTC)
    history = []
    accumulator = MergeAccumulator(priorities)
    for index in range(100):
        feed = random.choice(list(priorities))
        observed = base + timedelta(minutes=random.randrange(12))
        article = ArticleSnapshot(
            source="test",
            source_id="example",
            title=random.choice(["", "A", "B"]),
            raw_url=f"https://example.com/{index}",
            canonical_url=random.choice([None, "https://example.com/a"]),
            description=random.choice([None, "", "long description", "short"]),
            description_source=random.choice([None, feed]),
            authors=random.choice([[], ["B", "A", "B"]]),
            categories=random.choice([[], ["old"], ["new", "old"]]),
            keywords=random.choice([[], ["one"], ["two"]]),
            raw_metadata={"observation": index},
            published_at=base,
            timestamp_original=base.isoformat(),
            first_seen_at=observed,
            last_seen_at=observed,
            last_checked_at=observed + timedelta(minutes=1),
        )
        candidate = SightingCandidate(article, feed, index + 1, None, {})
        history.append(candidate)
        accumulator.add(candidate)
        expected = historical_reference(history, priorities)
        assert accumulator.snapshot() == expected
        assert merge_sightings(history, priorities) == expected
