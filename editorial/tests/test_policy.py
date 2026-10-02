from news_editorial.policy import load_policy
from news_editorial.paths import POLICY_PATH


def test_policy_loads_scoring_publishers_and_limits():
    policy = load_policy(POLICY_PATH)
    assert "dr" in policy.scoring_publishers
    assert "via_ritzau" in policy.corroborating_publishers
    assert policy.limits.stories_written == 24
    assert policy.section_weights["denmark"] == 1.0
    assert policy.feed_sections["dr.kultur"] == ["culture"]
    assert policy.feed_sections["borsen.breaking"] == []


def test_policy_publisher_status():
    policy = load_policy(POLICY_PATH)
    assert policy.publisher_status("dr") == "scoring"
    assert policy.publisher_status("via_ritzau") == "corroborating"
    assert policy.publisher_status("ft") == "linked"


def test_policy_bounds_the_sessions_by_turns(policy):
    assert policy.limits.editor_turns > 0 and policy.limits.checker_turns > 0


def test_policy_carries_no_device_decisions(policy):
    assert not hasattr(policy.limits, "fit_rounds_with_editor")
    assert not hasattr(policy.budgets, "device_capacity")


def test_policy_names_the_wire_agencies_and_their_sign_offs(policy):
    assert policy.wire_agencies == {"ritzau": "RITZAU"}
