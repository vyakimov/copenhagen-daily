import json
from news_editorial.paths import REPO
from news_editorial.contract import validate_edition

EXAMPLES = REPO / "publisher" / "contracts" / "examples"


def test_minimal_example_is_accepted():
    document = json.loads((EXAMPLES / "minimal.json").read_text())
    errors = validate_edition(document)
    assert errors == []
