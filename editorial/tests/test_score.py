import json

from conftest import BUNDLE, CUTOFF, PREVIOUS_CUTOFF, read_json
from news_editorial.bundle import load_bundle
from news_editorial.clusters import check_clusters
from news_editorial.score import breadth_norm, rank, recency_for
from news_editorial.window import build_window
from test_clusters import GEDSER, SUPREME, _cluster, _clusters

LINKED_ONLY = [32, 50, 56, 57, 60]
AI = [89, 138, 95, 135, 155, 97, 137, 90, 86, 73, 61]


def _window(policy):
    return build_window(load_bundle(BUNDLE), policy, cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)


def _memory(window, covered=None, threads=None):
    return {
        "schema_version": 1,
        "cutoff_at": window["cutoff_at"],
        "previous_cutoff_at": PREVIOUS_CUTOFF,
        "editions": [
            {"id": "2026-09-14-midday", "cutoff_at": PREVIOUS_CUTOFF, "stories": []},
            {"id": "2026-09-13-morning", "cutoff_at": "2026-09-13T03:00:00.000000Z", "stories": []},
        ],
        "covered": covered or {},
        "threads": threads or [],
        "dormant_threads": [],
        "next_edition_number": 5,
    }


def _rank(policy, clusters, memory=None):
    window = _window(policy)
    checked = check_clusters(clusters, window)
    return rank(checked, window, memory or _memory(window), policy)


def test_breadth_norm_rewards_the_second_publisher_most():
    steps = [breadth_norm(n + 1) - breadth_norm(n) for n in range(1, 6)]
    assert breadth_norm(0) == 0
    assert steps == sorted(steps, reverse=True)
    assert breadth_norm(10) == 1.0


def test_recency_is_measured_in_editions():
    cutoffs = [PREVIOUS_CUTOFF, "2026-09-13T03:00:00.000000Z"]
    assert recency_for("2026-09-15T07:00:00.000000Z", cutoffs) == 1.0
    assert recency_for("2026-09-14T00:00:00.000000Z", cutoffs) == 0.45
    assert recency_for("2026-09-12T12:00:00.000000Z", cutoffs) == 0.15


def test_breadth_counts_scoring_publishers_only(policy):
    ranking = _rank(policy, _clusters(_cluster("supreme", SUPREME)))
    row = next(r for r in ranking["candidates"] if r["id"] == "supreme")
    assert row["breadth"] == 5
    assert sorted(row["scoring_publishers"]) == ["berlingske", "borsen", "dr", "kristeligt_dagblad", "politiken"]
    assert row["linked_publishers"] == ["bbc", "ft", "guardian", "nytimes", "wapo"]


def test_linked_only_cluster_is_not_in_danish_media(policy):
    ranking = _rank(policy, _clusters(_cluster("linked", LINKED_ONLY)))
    row = next(r for r in ranking["candidates"] if r["id"] == "linked")
    assert row["eligible"] is False and row["decision"] == "not_in_danish_media"
    assert row["rank"] is None


def test_covered_cluster_is_already_covered(policy):
    window = _window(policy)
    article = next(a for a in window["articles"] if a["n"] == 79)
    covered = {f"{article['source']}:{article['source_id']}": {"edition_id": "2026-09-14-midday", "story_id": "x"}}
    ranking = _rank(policy, _clusters(_cluster("gedser", GEDSER)), _memory(window, covered=covered))
    row = next(r for r in ranking["candidates"] if r["id"] == "gedser")
    assert row["decision"] == "already_covered"
    assert row["covered_by"] == {"edition_id": "2026-09-14-midday", "story_id": "x", "articles": [79]}


def test_the_lead_outranks_a_lesser_story(policy):
    ranking = _rank(policy, _clusters(_cluster("gedser", GEDSER), _cluster("ai", AI), _cluster("supreme", SUPREME)))
    by_id = {r["id"]: r for r in ranking["candidates"]}
    assert by_id["gedser"]["rank"] == 1
    assert by_id["gedser"]["score"] > by_id["supreme"]["score"] > 0
    assert by_id["gedser"]["terms"]["recency"] == 1.0
    assert by_id["gedser"]["terms"]["peak_prominence"] == 1.0
    assert by_id["gedser"]["section_weight"] == 1.0
    assert {"denmark", "politics"} <= set(by_id["gedser"]["sections"])


def test_prominence_unknown_is_excluded_not_zero(policy):
    ranking = _rank(policy, _clusters(_cluster("supreme", SUPREME)))
    row = next(r for r in ranking["candidates"] if r["id"] == "supreme")
    assert row["terms"]["peak_prominence"] is None
    weights = policy.weights
    expected = (weights.breadth * row["terms"]["breadth"] + weights.recency * row["terms"]["recency"]
                + weights.thread_strength * row["terms"]["thread_strength"]) / (
        weights.breadth + weights.recency + weights.thread_strength)
    assert abs(row["base"] - expected) < 1e-6


def test_thread_strength_needs_a_published_thread(policy):
    window = _window(policy)
    threads = [
        {"id": "russia-baltic", "description": "Russian pressure in the Baltic", "peak_breadth": 6,
         "editions_since_published": 1, "last_edition_id": "2026-09-14-midday", "story_ids": ["x"], "last_seen_date": "2026-09-14"},
        {"id": "never-run", "description": "n", "peak_breadth": 6, "editions_since_published": None,
         "last_edition_id": None, "story_ids": [], "last_seen_date": "2026-09-14"},
    ]
    memory = _memory(window, threads=threads)
    ranking = _rank(policy, _clusters(
        _cluster("gedser", GEDSER, thread={"id": "russia-baltic"}),
        _cluster("supreme", SUPREME, thread={"id": "never-run"}),
        _cluster("ai", AI, thread={"new": {"id": "ai-slowdown", "description": "AI slowdown calls"}}),
    ), memory)
    by_id = {r["id"]: r for r in ranking["candidates"]}
    assert by_id["gedser"]["terms"]["thread_strength"] == breadth_norm(6)
    assert by_id["supreme"]["terms"]["thread_strength"] == 0.0
    assert by_id["ai"]["terms"]["thread_strength"] == 0.0
    assert by_id["ai"]["thread"] == {"new": {"id": "ai-slowdown", "description": "AI slowdown calls"}}


def test_candidates_beyond_the_budget_are_outside_budget(policy):
    policy = policy.model_copy(deep=True)
    policy.limits.stories_written = 2
    ranking = _rank(policy, _clusters(_cluster("gedser", GEDSER), _cluster("ai", AI), _cluster("supreme", SUPREME)))
    decisions = {r["id"]: r["decision"] for r in ranking["candidates"] if r["id"] in {"gedser", "ai", "supreme"}}
    assert sorted(decisions.values()) == ["eligible", "eligible", "outside_budget"]
    assert ranking["limits"]["stories_written"] == 2


def test_singletons_rank_too(policy):
    ranking = _rank(policy, _clusters(_cluster("gedser", GEDSER)))
    single = next(r for r in ranking["candidates"] if r["id"] == "s14")  # BBC drone: linked only
    assert single["members"] == [14] and single["decision"] == "not_in_danish_media"
    assert any(r["id"].startswith("s") and r["eligible"] for r in ranking["candidates"])
