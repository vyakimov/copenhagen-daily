from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EDITORIAL = REPO / "editorial"
CONTRACTS = REPO / "publisher" / "contracts"
EXAMPLES = CONTRACTS / "examples"
SCHEMA_PATH = CONTRACTS / "edition-contract.v1.schema.json"
POLICY_PATH = EDITORIAL / "policy.yaml"
SPEC_SCHEMA_PATH = EDITORIAL / "contracts" / "spec.v1.schema.json"
VERDICTS_SCHEMA_PATH = EDITORIAL / "contracts" / "verdicts.v1.schema.json"
RUNS = EDITORIAL / "runs"
VAR = EDITORIAL / "var"
INGEST_WRAPPER = REPO / "ingest" / "gather_news.sh"
PUBLISHER_WRAPPER = REPO / "publisher" / "publish_news.sh"
