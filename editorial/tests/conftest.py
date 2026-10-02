import dataclasses
import json
from pathlib import Path

import pytest

from news_editorial.bundle import load_bundle
from news_editorial.paths import EDITORIAL, POLICY_PATH
from news_editorial.policy import load_policy

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLE = FIXTURES / "bundle-2026-09-15"
EDITORIAL_EXAMPLES = EDITORIAL / "examples"
CUTOFF = "2026-09-15T08:00:00.000000Z"
PREVIOUS_CUTOFF = "2026-09-14T10:00:00.000000Z"
# An unsigned Kristeligt Dagblad article the golden spec cites. The fixture's descriptions are cut short,
# so a test that needs wire copy restores the sign-off the feed carries.
WIRE_ARTICLE = "619f810d-b829-4429-a0ee-4f35dec742fa"


@pytest.fixture(scope="session")
def policy():
    return load_policy(POLICY_PATH)


@pytest.fixture
def run_dir(tmp_path):
    run = tmp_path / "2026-09-15-morning"
    run.mkdir()
    return run


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf8"))


def wired_bundle():
    """The fixture bundle with WIRE_ARTICLE signed off by Ritzau, as the live feed signs it."""
    bundle = load_bundle(BUNDLE)
    articles = [
        {**a, "description": a["description"] + "</p><p>RITZAU</p>"} if a["source_id"].endswith(WIRE_ARTICLE) else a
        for a in bundle.articles
    ]
    assert articles != bundle.articles
    return dataclasses.replace(bundle, articles=articles)
