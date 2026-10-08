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
    decisions = [r["decision"] for r in ranking["candidates"]]
    assert decisions.count("eligible") == 2
    assert ranking["candidates"][0]["id"] == "gedser" and ranking["candidates"][0]["decision"] == "eligible"
    assert {r["decision"] for r in ranking["candidates"] if r["id"] in {"ai", "supreme"}} <= {"eligible", "outside_budget"}
    assert ranking["limits"]["stories_written"] == 2


def test_singletons_rank_too(policy):
    ranking = _rank(policy, _clusters(_cluster("gedser", GEDSER)))
    single = next(r for r in ranking["candidates"] if r["id"] == "s14")  # BBC drone: linked only
    assert single["decision"] == "not_in_danish_media"
    assert any(r["id"].startswith("s") and r["eligible"] for r in ranking["candidates"])


def test_ties_break_towards_the_fresher_story(policy):
    window = _window(policy)
    memory = _memory(window)
    checked = check_clusters(_clusters(), window)
    ranking = rank(checked, window, memory, policy)
    ranked = [c for c in ranking["candidates"] if c["rank"] is not None and "terms" in c]
    assert len(ranked) > policy.limits.stories_written
    for earlier, later in zip(ranked, ranked[1:]):
        if earlier["score"] == later["score"] and earlier["breadth"] == later["breadth"]:
            assert earlier["latest_published_at"] >= later["latest_published_at"], (earlier["id"], later["id"])


def test_the_ranking_is_capped_to_what_the_desk_can_use(policy):
    """Eligible rows, a short tail past the budget, and covered rows carry their terms; the rest is a line."""
    from news_editorial.score import RANKING_TAIL

    policy = policy.model_copy(deep=True)
    policy.limits.stories_written = 1
    window = _window(policy)
    article = next(a for a in window["articles"] if a["n"] == 79)
    covered = {f"{article['source']}:{article['source_id']}": {"edition_id": "2026-09-14-midday", "story_id": "x"}}
    ranking = _rank(policy, _clusters(_cluster("gedser", GEDSER), _cluster("ai", AI), _cluster("supreme", SUPREME)), _memory(window, covered=covered))
    rows = ranking["candidates"]
    full = [r for r in rows if "terms" in r]
    compact = [r for r in rows if "terms" not in r]
    assert ranking["written_in_full"] == {"eligible": True, "outside_budget_tail": RANKING_TAIL, "already_covered": True}
    assert ranking["decisions"]["not_in_danish_media"] >= 1 and ranking["decisions"]["eligible"] == 1
    # Everything eligible, the tail, and the covered cluster keep every term.
    assert all(r["decision"] in {"eligible", "outside_budget", "already_covered"} for r in full)
    assert sum(1 for r in full if r["decision"] == "outside_budget") == min(RANKING_TAIL, ranking["decisions"]["outside_budget"])
    assert next(r for r in full if r["id"] == "gedser")["covered_by"]["edition_id"] == "2026-09-14-midday"
    # Everything else is one line: enough to look it up, nothing to read.
    assert compact and all(r["decision"] in {"outside_budget", "not_in_danish_media"} for r in compact)
    assert all(set(r) == {"id", "breadth", "score", "rank", "eligible", "decision"} for r in compact if r["decision"] == "outside_budget")
    assert next(r for r in compact if r["id"] == "s14") == {"id": "s14", "rank": None, "eligible": False, "decision": "not_in_danish_media"}  # BBC drone
    # The order and the ranks are unchanged by the cap.
    assert [r["rank"] for r in rows if r["rank"] is not None] == list(range(1, 1 + ranking["decisions"]["eligible"] + ranking["decisions"]["outside_budget"]))


def test_the_tail_is_cut_by_rank_not_by_cluster_size(policy):
    from news_editorial import score as score_module

    policy = policy.model_copy(deep=True)
    policy.limits.stories_written = 1
    original = score_module.RANKING_TAIL
    score_module.RANKING_TAIL = 2
    try:
        ranking = _rank(policy, _clusters())
    finally:
        score_module.RANKING_TAIL = original
    tail = [r for r in ranking["candidates"] if r["decision"] == "outside_budget" and "terms" in r]
    assert [r["rank"] for r in tail] == [2, 3]
    assert ranking["written_in_full"]["outside_budget_tail"] == 2


def test_the_written_ranking_reads_back_and_keeps_compact_rows_on_one_line(policy, tmp_path):
    from news_editorial.score import write_ranking

    ranking = _rank(policy, _clusters(_cluster("gedser", GEDSER)))
    path = write_ranking(ranking, tmp_path)
    assert read_json(path) == ranking
    lines = path.read_text(encoding="utf8").splitlines()
    assert any(line.startswith('  {"id": "s14"') and line.rstrip(",").endswith("}") for line in lines)
    assert any(line == '   "terms": {' for line in lines)
