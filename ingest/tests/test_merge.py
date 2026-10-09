from datetime import UTC, datetime, timedelta
from random import Random

from news_ingest.feed import SightingCandidate
from news_ingest.hashing import HASH_FIELDS, content_hash
from news_ingest.merge import (
    FIELDS,
    SNAPSHOT_CONTENT,
    current_canonical,
    merge_feed_states,
    merge_sightings,
    update_feed_state,
)
from news_ingest.models import ArticleSnapshot, FeedMergeState

BASE = datetime(2026, 9, 29, tzinfo=UTC)


def historical_reference(sightings, priorities):
    """Recompute the merge from complete history, without representatives or cached state."""

    def current(articles, field):
        best = None
        for article in articles:
            if field is not None and getattr(article, field) in (None, ""):
                continue
            if best is None or article.last_seen_at > best.last_seen_at:
                best = article
        return best

    def content(article, field):
        if article is None:
            return None
        if field is None:
            return tuple(getattr(article, name) for name in SNAPSHOT_CONTENT)
        return getattr(article, field)

    by_feed = {}
    for sighting in sightings:
        by_feed.setdefault(sighting.feed_id, []).append(current_canonical(sighting.article))

    def best(field):
        ranked = []
        for feed, articles in by_feed.items():
            chosen = current(articles, field)
            if chosen is None:
                continue
            revised = None
            for count in range(2, len(articles) + 1):
                old, new = current(articles[: count - 1], field), current(articles[:count], field)
                if content(old, field) != content(new, field):
                    revised = new.last_seen_at
            priority, order = priorities[feed]
            key = (revised is not None, revised or BASE.min.replace(tzinfo=UTC))
            ranked.append(((*key, priority, -order, feed), feed, chosen))
        return max(ranked, key=lambda item: item[0], default=None)

    _, _, winner = best(None)
    base = winner.model_copy(deep=True)
    for field in FIELDS:
        chosen = best(field)
        if chosen:
            setattr(base, field, getattr(chosen[2], field))
    described = best("description")
    base.description_source = described[1] if described else None
    base.authors = list(dict.fromkeys(winner.authors))
    base.categories = sorted({value for s in sightings for value in s.article.categories})
    base.keywords = sorted({value for s in sightings for value in s.article.keywords})
    base.first_seen_at = min(s.article.first_seen_at for s in sightings)
    base.last_seen_at = max(s.article.last_seen_at for s in sightings)
    base.last_checked_at = max(s.article.last_checked_at for s in sightings)
    base.content_hash = content_hash(base)
    return base


def test_persisted_merge_matches_full_history_at_every_prefix():
    random = Random(1927)
    priorities = {"latest": (10, 0), "section-a": (20, 1), "section-b": (20, 2)}
    history = []
    persisted = {}
    for index in range(80):
        feed = random.choice(list(priorities))
        observed = BASE + timedelta(minutes=random.randrange(12))
        article = ArticleSnapshot(
            source="test",
            source_id="example",
            title=random.choice(["", "A", "B"]),
            raw_url=f"https://example.com/{index % 3}",
            canonical_url=random.choice([None, "https://example.com/a"]),
            description=random.choice([None, "", "long description", "short"]),
            description_source=feed,
            authors=random.choice([[], ["B", "A", "B"]]),
            categories=random.choice([[], ["old"], ["new", "old"]]),
            keywords=random.choice([[], ["one"], ["two"]]),
            raw_metadata={"observation": index},
            published_at=BASE,
            timestamp_original=BASE.isoformat(),
            first_seen_at=observed,
            last_seen_at=observed,
            last_checked_at=observed + timedelta(minutes=1),
        )
        history.append(SightingCandidate(article, feed, index + 1, None, {}))
        expected = historical_reference(history, priorities)
        assert merge_sightings(history, priorities) == expected
        state = update_feed_state(persisted.get(feed), feed, index + 1, article)
        # Every observation crosses the real JSON boundary, as it does between polls.
        persisted[feed] = FeedMergeState.model_validate_json(state.model_dump_json())
        assert merge_feed_states(list(persisted.values()), priorities) == expected
        changed_priorities = {"latest": (30, 2), "section-a": (10, 0), "section-b": (10, 1)}
        assert merge_feed_states(
            list(persisted.values()), changed_priorities
        ) == historical_reference(history, changed_priorities)
        assert all(len(state.representatives) <= 10 for state in persisted.values())


PRIORITIES = {"latest": (10, 0), "world": (20, 10), "business": (20, 30), "health": (20, 60)}


def sighting(feed, minute, title="Headline", description="Description", **values):
    observed = BASE + timedelta(minutes=minute)
    article = ArticleSnapshot(
        source="nytimes",
        source_id="example",
        title=title,
        raw_url="https://example.com/a",
        canonical_url="https://example.com/a",
        description=description,
        description_source=feed,
        published_at=BASE,
        timestamp_original=BASE.isoformat(),
        first_seen_at=observed,
        last_seen_at=observed,
        last_checked_at=observed,
        **values,
    )
    return SightingCandidate(article, feed, 1, None, {})


def hashes(sightings):
    return [
        merge_sightings(sightings[:n], PRIORITIES).content_hash
        for n in range(1, len(sightings) + 1)
    ]


def test_every_hashed_field_is_merged_by_some_rule():
    unions = {"categories", "keywords"}
    identity = {"schema_version", "source", "source_id"}
    merged = set(FIELDS) | set(SNAPSHOT_CONTENT) | unions | identity
    # The exact publisher link is merged for provenance but is not content.
    assert merged - set(HASH_FIELDS) == {"raw_url"}
    assert set(HASH_FIELDS) <= merged


def test_unchanged_polls_of_equal_priority_feeds_do_not_rotate():
    # Each feed carries its own variant and is committed a few seconds after the other, as
    # in a real run, so "latest observation wins" would change the article on every poll.
    polls = []
    for minute in range(0, 150, 15):
        polls.append(sighting("business", minute, title="Business variant", description="B"))
        polls.append(sighting("health", minute + 0.05, title="Health variant", description="H"))
    assert len(set(hashes(polls))) == 1
    for prefix in (polls, polls[:-1]):
        merged = merge_sightings(prefix, PRIORITIES)
        # Unrevised variants fall to configured order, whichever feed was polled last.
        assert (merged.title, merged.description_source) == ("Business variant", "business")


def test_edit_in_a_lower_ranked_feed_wins_after_the_preferred_feed_drops_the_article():
    polls = [sighting("business", 0), sighting("health", 0), sighting("business", 15)]
    polls += [sighting("health", 30), sighting("health", 45, title="Edited headline")]
    merged = merge_sightings(polls, PRIORITIES)
    assert merged.title == "Edited headline"
    # The preferred feed showing the edit later keeps it, now as its own newer revision.
    polls.append(sighting("business", 60, title="Edited headline"))
    assert merge_sightings(polls, PRIORITIES).title == "Edited headline"


def test_unrevised_values_follow_priority_whichever_feed_is_seen_first():
    latest = sighting("latest", 0, description="Short latest description")
    section = sighting("world", 15, description="Section description")
    for order in ([latest, section], [section, latest]):
        merged = merge_sightings(order, PRIORITIES)
        assert merged.description == "Section description"
        assert merged.description_source == "world"


def test_a_feed_seen_later_does_not_replace_a_different_introduced_variant():
    opinion = sighting("world", 0, title="Opinion | The AI Luddites Won't Win")
    plain = sighting("business", 15, title="The AI Luddites Won't Win")
    assert merge_sightings([opinion, plain], PRIORITIES).title.startswith("Opinion |")
    assert merge_sightings([plain, opinion], PRIORITIES).title.startswith("Opinion |")


def test_same_feed_a_b_a_creates_three_ordered_versions():
    polls = [sighting("world", 0, title="A"), sighting("world", 15, title="B")]
    polls += [sighting("world", 30, title="A"), sighting("world", 45, title="A")]
    first, second, third, fourth = hashes(polls)
    assert first != second != third
    assert first == third == fourth


def test_newest_revision_wins_across_feeds_and_a_revert_is_a_revision():
    polls = [sighting("world", 0, title="A"), sighting("business", 0, title="A")]
    polls.append(sighting("business", 15, title="B"))
    assert merge_sightings(polls, PRIORITIES).title == "B"
    polls.append(sighting("world", 30, title="C"))
    assert merge_sightings(polls, PRIORITIES).title == "C"
    polls.append(sighting("business", 45, title="A"))
    assert merge_sightings(polls, PRIORITIES).title == "A"


def test_description_source_names_the_feed_that_supplied_the_description():
    polls = [sighting("world", 0, description=None), sighting("latest", 15)]
    merged = merge_sightings(polls, PRIORITIES)
    assert (merged.description, merged.description_source) == ("Description", "latest")
    merged = merge_sightings([sighting("world", 0, description=None)], PRIORITIES)
    assert (merged.description, merged.description_source) == (None, None)


def test_snapshot_attributes_follow_their_own_revision():
    polls = [sighting("world", 0, authors=["A"]), sighting("business", 1, authors=["A"])]
    assert merge_sightings(polls, PRIORITIES).authors == ["A"]
    polls.append(sighting("business", 15, authors=["A", "B"]))
    assert merge_sightings(polls, PRIORITIES).authors == ["A", "B"]
    polls.append(sighting("world", 30, authors=["A"]))
    assert merge_sightings(polls, PRIORITIES).authors == ["A", "B"]


def test_url_rule_changes_reach_history_without_a_revision():
    def wsj(minute, canonical):
        article = sighting("world", minute).article.model_copy(
            update={
                "source": "wsj",
                "raw_url": "https://www.wsj.com/a?mod=rss_opinion",
                "canonical_url": canonical,
            }
        )
        return SightingCandidate(article, "world", 1, None, {})

    # A sighting stored before WSJ `mod` was dropped, then the same item normalized today.
    history = [wsj(0, "https://www.wsj.com/a?mod=rss_opinion"), wsj(15, "https://www.wsj.com/a")]
    first, second = hashes(history)
    assert first == second
    assert merge_sightings(history, PRIORITIES).canonical_url == "https://www.wsj.com/a"
    assert merge_sightings(history, PRIORITIES).raw_url.endswith("?mod=rss_opinion")


def test_description_source_is_not_content():
    one = merge_sightings([sighting("world", 0)], PRIORITIES)
    other = merge_sightings([sighting("business", 0)], PRIORITIES)
    assert one.description_source != other.description_source
    assert one.content_hash == other.content_hash


def test_version_one_cache_state_is_rejected():
    state = update_feed_state(None, "world", 1, sighting("world", 0).article)
    legacy = state.model_dump(mode="json") | {"schema_version": 1}
    legacy.pop("revised_at")
    try:
        FeedMergeState.model_validate(legacy)
    except ValueError:
        return
    raise AssertionError("a version-1 merge state must not validate")
