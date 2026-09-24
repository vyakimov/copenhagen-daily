import json
import subprocess

from conftest import BUNDLE, CUTOFF, PREVIOUS_CUTOFF, read_json
from news_editorial.paths import EDITORIAL, REPO

WRAPPER = REPO / "editorial" / "edit_news.sh"
FEEDS = EDITORIAL / "examples" / "2026-09-15-morning" / "feeds.json"


def test_window_action_from_existing_bundle(run_dir):
    proc = subprocess.run(
        [str(WRAPPER), "window", "--run", str(run_dir), "--cutoff", CUTOFF, "--previous-cutoff", PREVIOUS_CUTOFF,
         "--bundle", str(BUNDLE), "--feeds", str(FEEDS)],
        capture_output=True, text=True,
    )
    envelope = json.loads(proc.stdout)
    assert envelope["ok"] is True, envelope
    assert envelope["result"]["article_count"] == 254
    assert (run_dir / "window.json").exists()
    assert read_json(run_dir / "feeds.json")[0]["feed_id"] == "altinget.arbejdsmarked"
