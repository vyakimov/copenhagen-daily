import json
from pathlib import Path

import pytest

from news_editorial.paths import EDITORIAL, POLICY_PATH
from news_editorial.policy import load_policy

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLE = FIXTURES / "bundle-2026-09-15"
EDITORIAL_EXAMPLES = EDITORIAL / "examples"
CUTOFF = "2026-09-15T08:00:00.000000Z"
PREVIOUS_CUTOFF = "2026-09-14T10:00:00.000000Z"


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
