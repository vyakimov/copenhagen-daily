import json

from conftest import FIXTURES, read_json
from news_editorial.memory import build_memory, write_memory

PUBLISH_ROOT = FIXTURES / "publish-root"
CUTOFF = "2026-09-21T16:00:00.000000Z"


def _registry(tmp_path):
    path = tmp_path / "threads.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "threads": [
                    {
                        "id": "greenland-us-agreement",
                        "description": "Denmark, Greenland and the US negotiate a security agreement",
                        "opened_edition_id": "2026-09-16-morning",
                        "last_edition_id": "2026-09-19-evening",
                        "last_seen_date": "2026-09-19",
                        "peak_breadth": 9,
                        "story_ids": ["greenland-us-security-agreement"],
                    },
                    {
                        "id": "novo-rebrand",
                        "description": "Novo Nordisk's rebrand and its aftermath",
                        "opened_edition_id": "2026-09-14-midday",
                        "last_edition_id": "2026-09-14-midday",
                        "last_seen_date": "2026-09-01",
                        "peak_breadth": 4,
                        "story_ids": ["novo-rebrand"],
                    },
                ],
            }
        )
    )
    return path


def test_memory_lists_activated_editions_newest_first(policy, tmp_path):
    memory = build_memory(PUBLISH_ROOT, _registry(tmp_path), policy, cutoff=CUTOFF)
    assert [e["id"] for e in memory["editions"]] == ["2026-09-19-evening", "2026-09-18-afternoon"]
    assert memory["editions"][0]["number"] == 8
    assert memory["next_edition_number"] == 9
    assert memory["previous_cutoff_at"] == "2026-09-19T19:49:28.000000Z"


def test_memory_maps_published_articles_to_their_story(policy, tmp_path):
    memory = build_memory(PUBLISH_ROOT, _registry(tmp_path), policy, cutoff=CUTOFF)
    lead = next(s for s in memory["editions"][0]["stories"] if s["role"] == "lead")
    assert lead["id"] == "greenland-us-security-agreement"
    assert lead["thread"] == "greenland-us-agreement"
    key = f"{lead['sources'][0]['source']}:{lead['sources'][0]['source_id']}"
    assert memory["covered"][key] == {"edition_id": "2026-09-19-evening", "story_id": lead["id"]}


def test_memory_limits_to_policy_editions(policy, tmp_path):
    policy = policy.model_copy(deep=True)
    policy.schedule.memory_editions = 1
    memory = build_memory(PUBLISH_ROOT, _registry(tmp_path), policy, cutoff=CUTOFF)
    assert [e["id"] for e in memory["editions"]] == ["2026-09-19-evening"]


def test_threads_split_into_active_and_dormant(policy, tmp_path):
    memory = build_memory(PUBLISH_ROOT, _registry(tmp_path), policy, cutoff=CUTOFF)
    assert [t["id"] for t in memory["threads"]] == ["greenland-us-agreement"]
    assert [t["id"] for t in memory["dormant_threads"]] == ["novo-rebrand"]
    active = memory["threads"][0]
    assert active["editions_since_published"] == 1


def test_memory_without_registry_has_no_threads(policy, tmp_path):
    memory = build_memory(PUBLISH_ROOT, tmp_path / "missing.json", policy, cutoff=CUTOFF)
    assert memory["threads"] == [] and memory["dormant_threads"] == []


def test_write_memory(policy, tmp_path, run_dir):
    memory = build_memory(PUBLISH_ROOT, _registry(tmp_path), policy, cutoff=CUTOFF)
    write_memory(memory, run_dir)
    assert read_json(run_dir / "memory.json")["next_edition_number"] == 9


def test_memory_holds_only_editions_cut_off_before_this_run(policy, tmp_path):
    """A rerun or a second printing for an earlier cutoff must not see the editions that came after
    it, or everything in its window would count as already covered."""
    memory = build_memory(PUBLISH_ROOT, _registry(tmp_path), policy, cutoff="2026-09-19T19:49:28.000000Z")
    assert [e["id"] for e in memory["editions"]] == ["2026-09-18-afternoon"]
    assert memory["previous_cutoff_at"] == "2026-09-18T14:30:00.000000Z"
    assert memory["next_edition_number"] == 9
