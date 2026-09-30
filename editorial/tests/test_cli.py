import json
import subprocess
import sys

from news_editorial.paths import REPO

WRAPPER = REPO / "editorial" / "edit_news.sh"


def run(*args: str) -> tuple[int, dict]:
    proc = subprocess.run([str(WRAPPER), *args], capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def test_list_actions_emits_envelope():
    code, envelope = run("list-actions")
    assert code == 0
    assert envelope["ok"] is True
    assert envelope["action"] == "list-actions"
    names = {a["name"] for a in envelope["result"]["actions"]}
    assert {"window", "memory", "check-clusters", "score", "build", "apply-verdicts", "run", "status"} <= names


def test_unknown_action_is_usage_error():
    code, envelope = run("nonsense")
    assert code == 2
    assert envelope["ok"] is False
    assert envelope["error"]["type"] == "invalid_arguments"


def test_module_entry_point_matches_wrapper():
    proc = subprocess.run([sys.executable, "-m", "news_editorial", "list-actions"], capture_output=True, text=True)
    assert json.loads(proc.stdout)["ok"] is True


def test_verify_live_is_listed_and_parses_its_flags():
    from news_editorial.cli import ACTIONS, build_parser

    assert ACTIONS["verify-live"]["mutates"] is False
    args = build_parser().parse_args(["verify-live", "--fix", "--notify", "--site-url", "https://example.test"])
    assert args.fix and args.notify and args.site_url == "https://example.test"
