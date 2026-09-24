import json
from news_editorial.paths import REPO
from news_editorial.contract import validate_edition

EXAMPLES = REPO / "publisher" / "contracts" / "examples"


def test_minimal_example_is_accepted():
    document = json.loads((EXAMPLES / "minimal.json").read_text())
    errors = validate_edition(document)
    assert errors == []


def test_every_example_is_accepted():
    for path in sorted(EXAMPLES.glob("*.json")):
        assert validate_edition(json.loads(path.read_text())) == [], path.name


def _apply(doc, ops):
    import copy

    doc = copy.deepcopy(doc)
    for op in ops:
        parts = op["path"].lstrip("/").split("/")
        target = doc
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        key = parts[-1]
        if isinstance(target, list):
            index = int(key)
            if op["op"] == "add":
                target.insert(index, op["value"])
            elif op["op"] == "replace":
                target[index] = op["value"]
            else:
                del target[index]
        elif op["op"] == "remove":
            del target[key]
        else:
            target[key] = op["value"]
    return doc


def test_rejection_corpus_fails_at_the_expected_pointer():
    corpus = json.loads((EXAMPLES / "rejections" / "cases.json").read_text())
    base = json.loads((EXAMPLES / corpus["base"]).read_text())
    assert validate_edition(base) == []
    for case in corpus["cases"]:
        errors = validate_edition(_apply(base, case["ops"]))
        assert errors, case["name"]
        assert any(e.startswith(case["expected_pointer"] + ":") for e in errors), (case["name"], errors)
