import json

from conftest import BUNDLE, CUTOFF, PREVIOUS_CUTOFF, read_json
from news_editorial.bundle import load_bundle
from news_editorial.clusters import check_clusters, write_checked
from news_editorial.window import build_window

GEDSER = [79, 3, 30, 21, 26, 19, 71, 78, 80, 7, 12, 81, 47, 25, 13, 36]
SUPREME = [64, 35, 63, 66, 52, 32, 50, 56, 57, 60]


def _window(policy):
    return build_window(load_bundle(BUNDLE), policy, cutoff=CUTOFF, previous_cutoff=PREVIOUS_CUTOFF)


def _clusters(*items):
    return {"schema_version": 1, "clusters": [dict(c) for c in items]}


def _cluster(cid, members, event="an event", confidence=0.9, thread=None):
    return {"id": cid, "event": event, "members": members, "confidence": confidence, "thread": thread}


def test_coherent_cluster_passes_with_all_members(policy):
    checked = check_clusters(_clusters(_cluster("gedser", GEDSER)), _window(policy))
    cluster = checked["clusters"][0]
    assert cluster["members"] == sorted(GEDSER)
    assert cluster["flags"] == [] and cluster["removed"] == []


def test_unknown_member_is_removed_and_flagged(policy):
    checked = check_clusters(_clusters(_cluster("gedser", GEDSER + [9999])), _window(policy))
    cluster = checked["clusters"][0]
    assert 9999 not in cluster["members"]
    assert {"n": 9999, "reason": "unknown_member"} in cluster["removed"]


def test_member_in_two_clusters_stays_in_the_first(policy):
    checked = check_clusters(
        _clusters(_cluster("gedser", GEDSER), _cluster("supreme", SUPREME + [3])), _window(policy)
    )
    second = checked["clusters"][1]
    assert 3 not in second["members"]
    assert {"n": 3, "reason": "duplicate_member"} in second["removed"]


def test_member_sharing_no_term_is_split_off(policy):
    stray = 22  # giant jellyfish
    checked = check_clusters(_clusters(_cluster("gedser", GEDSER + [stray])), _window(policy))
    cluster = checked["clusters"][0]
    assert stray not in cluster["members"]
    assert {"n": stray, "reason": "no_shared_term"} in cluster["removed"]
    assert stray in checked["singletons"]


def test_oversized_cluster_is_dissolved(policy):
    window = _window(policy)
    huge = list(range(1, 40))
    checked = check_clusters(_clusters(_cluster("all", huge)), window)
    assert checked["clusters"][0]["members"] == []
    assert "too_large" in checked["clusters"][0]["flags"]
    assert set(huge) <= set(checked["singletons"])


def test_low_confidence_is_flagged_not_split(policy):
    checked = check_clusters(_clusters(_cluster("gedser", GEDSER, confidence=0.3)), _window(policy))
    cluster = checked["clusters"][0]
    assert cluster["members"] == sorted(GEDSER)
    assert "low_confidence" in cluster["flags"]


def test_singletons_are_every_unclustered_article(policy):
    window = _window(policy)
    checked = check_clusters(_clusters(_cluster("gedser", GEDSER)), window)
    assert len(checked["singletons"]) == len(window["articles"]) - len(GEDSER)


def test_write_checked(policy, run_dir):
    checked = check_clusters(_clusters(_cluster("gedser", GEDSER)), _window(policy))
    write_checked(checked, run_dir)
    assert read_json(run_dir / "clusters-checked.json")["clusters"][0]["id"] == "gedser"
