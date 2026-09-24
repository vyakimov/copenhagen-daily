import json
import shutil
import subprocess

from conftest import BUNDLE, CUTOFF, FIXTURES, PREVIOUS_CUTOFF, read_json
from news_editorial.paths import EDITORIAL, REPO
from test_clusters import GEDSER, SUPREME

WRAPPER = REPO / "editorial" / "edit_news.sh"
FEEDS = EDITORIAL / "examples" / "2026-09-15-morning" / "feeds.json"


def run(*args):
    proc = subprocess.run([str(WRAPPER), *args], capture_output=True, text=True)
    return json.loads(proc.stdout)


def prepared_run(run_dir, tmp_path):
    assert run(
        "window", "--run", str(run_dir), "--cutoff", CUTOFF, "--previous-cutoff", PREVIOUS_CUTOFF,
        "--bundle", str(BUNDLE), "--feeds", str(FEEDS),
    )["ok"]
    registry = tmp_path / "threads.json"
    registry.write_text(json.dumps({"schema_version": 1, "threads": []}))
    assert run("memory", "--run", str(run_dir), "--publish-root", str(FIXTURES / "publish-root"), "--registry", str(registry))["ok"]
    (run_dir / "clusters.json").write_text(json.dumps({
        "schema_version": 1,
        "clusters": [
            {"id": "gedser", "event": "Russian frigate fires flares at a Danish helicopter", "members": GEDSER, "confidence": 0.95, "thread": None},
            {"id": "supreme", "event": "Supreme Court blocks Trump on mail ballots", "members": SUPREME, "confidence": 0.9, "thread": None},
        ],
    }))
    return run_dir


def test_check_clusters_then_score(run_dir, tmp_path):
    prepared_run(run_dir, tmp_path)
    checked = run("check-clusters", "--run", str(run_dir))
    assert checked["ok"], checked
    assert checked["result"]["clusters"] == 2 and checked["result"]["split"] == 0
    scored = run("score", "--run", str(run_dir))
    assert scored["ok"], scored
    ranking = read_json(run_dir / "ranking.json")
    assert ranking["candidates"][0]["id"] == "gedser"
    assert scored["result"]["eligible"] >= 2


def test_score_needs_checked_clusters(run_dir, tmp_path):
    prepared_run(run_dir, tmp_path)
    result = run("score", "--run", str(run_dir))
    assert result["ok"] is False and result["error"]["type"] == "resource_not_found"


def test_build_action_rebuilds_the_golden_example(tmp_path):
    golden = EDITORIAL / "examples" / "2026-09-15-morning"
    spec = read_json(golden / "spec.json")
    spec["bundle"] = str(BUNDLE)
    spec["feeds"] = str(golden / "feeds.json")
    spec["edition"]["generated_at"] = read_json(golden / "edition.json")["edition"]["generated_at"]
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    result = run("build", "--run", str(tmp_path), "--spec", str(spec_path))
    assert result["ok"], result
    built = read_json(tmp_path / "edition.json")
    archived = read_json(golden / "edition.json")
    built["inputs"] = archived["inputs"]
    assert built == archived
