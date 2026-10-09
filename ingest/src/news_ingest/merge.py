from __future__ import annotations

from datetime import UTC, datetime

from .feed import SightingCandidate
from .hashing import content_hash
from .models import ArticleSnapshot, FeedMergeState, MergeRepresentative
from .urls import UrlError, normalize_url

# Fields taken individually from the best feed that carries a nonempty value.
FIELDS = (
    "title",
    "raw_url",
    "canonical_url",
    "description",
    "image_url",
    "language",
    "timestamp_original",
    "published_at",
)
# Revision key for the content the representative snapshot itself supplies.
SNAPSHOT = "snapshot"
SNAPSHOT_CONTENT = (
    "content_type",
    "public_lead",
    "public_body",
    "public_body_truncated",
    "authors",
    "image_credit",
    "image_description",
    "modified_at",
    "timestamp_assumed_timezone",
    "access_status",
)
_NEVER = datetime.min.replace(tzinfo=UTC)


class FeedAccumulator:
    """One feed's winners: the latest observation, and the latest nonempty value of each field."""

    def __init__(self):
        self.winner: MergeRepresentative | None = None
        self.chosen: dict[str, MergeRepresentative] = {}
        self.categories: set[str] = set()
        self.keywords: set[str] = set()
        self.first_seen_at = self.last_seen_at = self.last_checked_at = None

    def add(self, representative: MergeRepresentative) -> None:
        article = representative.article
        # Strict comparisons keep the earlier sighting when observation times tie.
        if self.winner is None or article.last_seen_at > self.winner.article.last_seen_at:
            self.winner = representative
        for field in FIELDS:
            previous = self.chosen.get(field)
            if getattr(article, field) not in (None, "") and (
                previous is None or article.last_seen_at > previous.article.last_seen_at
            ):
                self.chosen[field] = representative
        self.categories.update(article.categories)
        self.keywords.update(article.keywords)
        self.first_seen_at = min(filter(None, (self.first_seen_at, article.first_seen_at)))
        self.last_seen_at = max(filter(None, (self.last_seen_at, article.last_seen_at)))
        self.last_checked_at = max(filter(None, (self.last_checked_at, article.last_checked_at)))

    def representative(self, key: str) -> MergeRepresentative | None:
        return self.winner if key == SNAPSHOT else self.chosen.get(key)

    def value(self, key: str):
        representative = self.representative(key)
        if representative is None:
            return None
        if key == SNAPSHOT:
            return tuple(getattr(representative.article, field) for field in SNAPSHOT_CONTENT)
        return getattr(representative.article, key)


def absorb_feed_state(state: FeedMergeState) -> FeedAccumulator:
    accumulator = FeedAccumulator()
    for representative in sorted(state.representatives, key=lambda item: item.sighting_id):
        accumulator.add(representative)
    accumulator.categories.update(state.categories)
    accumulator.keywords.update(state.keywords)
    accumulator.first_seen_at = min(accumulator.first_seen_at, state.first_seen_at)
    accumulator.last_seen_at = max(accumulator.last_seen_at, state.last_seen_at)
    accumulator.last_checked_at = max(accumulator.last_checked_at, state.last_checked_at)
    return accumulator


def current_canonical(article: ArticleSnapshot) -> ArticleSnapshot:
    """Apply today's URL rules to a retained sighting, so a normalization fix reaches history
    the same way it reaches new polls and is not mistaken for a publisher revision."""
    if article.canonical_url is None:
        return article
    try:
        canonical = normalize_url(article.source, article.raw_url)
    except UrlError:
        return article
    if canonical == article.canonical_url:
        return article
    return article.model_copy(update={"canonical_url": canonical})


def update_feed_state(
    previous: FeedMergeState | None, feed_id: str, sighting_id: int, article: ArticleSnapshot
) -> FeedMergeState:
    article = current_canonical(article)
    # Within one feed, only observation time and stable sighting order select winners.
    # Keep original winner timestamps: synthesizing one "latest" row loses field provenance.
    accumulator = FeedAccumulator() if previous is None else absorb_feed_state(previous)
    before = {key: accumulator.value(key) for key in (*FIELDS, SNAPSHOT)}
    representatives = [] if previous is None else list(previous.representatives)
    representative = MergeRepresentative(sighting_id=sighting_id, article=article)
    representatives.append(representative)
    accumulator.add(representative)
    # A feed's first values introduce the article; only a later change within the feed is a
    # revision. Re-observing the same value keeps its revision time, so unchanged polls of
    # several feeds cannot take turns winning.
    revised_at = {} if previous is None else dict(previous.revised_at)
    if previous is not None:
        for key, value in before.items():
            if accumulator.value(key) != value:
                revised_at[key] = accumulator.representative(key).article.last_seen_at
    retained = {id(accumulator.winner)}
    retained.update(id(item) for item in accumulator.chosen.values())
    return FeedMergeState(
        source=article.source,
        source_id=article.source_id,
        feed_id=feed_id,
        representatives=[item for item in representatives if id(item) in retained],
        categories=sorted(accumulator.categories),
        keywords=sorted(accumulator.keywords),
        first_seen_at=accumulator.first_seen_at,
        last_seen_at=accumulator.last_seen_at,
        last_checked_at=accumulator.last_checked_at,
        revised_at=revised_at,
    )


def merge_feed_states(states: list[FeedMergeState], priorities) -> ArticleSnapshot:
    """Across feeds, the newest revision wins; unrevised values are ranked by feed priority."""
    feeds = [(state, absorb_feed_state(state)) for state in sorted(states, key=lambda s: s.feed_id)]
    if not feeds:
        raise ValueError("no sightings")

    def best(key):
        def rank(item):
            state = item[0]
            priority, order = priorities[state.feed_id]
            revised = state.revised_at.get(key)
            return (revised is not None, revised or _NEVER, priority, -order, state.feed_id)

        candidates = [item for item in feeds if item[1].representative(key) is not None]
        return max(candidates, key=rank, default=None)

    _, accumulator = best(SNAPSHOT)
    base = accumulator.winner.article.model_copy(deep=True)
    for field in FIELDS:
        chosen = best(field)
        if chosen is not None:
            setattr(base, field, chosen[1].value(field))
    described = best("description")
    base.description_source = None if described is None else described[0].feed_id
    base.authors = list(dict.fromkeys(base.authors))
    base.categories = sorted({value for _, item in feeds for value in item.categories})
    base.keywords = sorted({value for _, item in feeds for value in item.keywords})
    base.first_seen_at = min(item.first_seen_at for _, item in feeds)
    base.last_seen_at = max(item.last_seen_at for _, item in feeds)
    base.last_checked_at = max(item.last_checked_at for _, item in feeds)
    base.content_hash = content_hash(base)
    return base


def merge_sightings(
    sightings: list[SightingCandidate], feed_priorities: dict[str, tuple[int, int]]
) -> ArticleSnapshot:
    """Merge a complete history given in sighting order."""
    states: dict[str, FeedMergeState] = {}
    for index, sighting in enumerate(sightings, start=1):
        states[sighting.feed_id] = update_feed_state(
            states.get(sighting.feed_id), sighting.feed_id, index, sighting.article
        )
    return merge_feed_states(list(states.values()), feed_priorities)
