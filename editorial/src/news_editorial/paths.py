from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONTRACTS = REPO / "publisher" / "contracts"
EXAMPLES = CONTRACTS / "examples"
SCHEMA_PATH = CONTRACTS / "edition-contract.v1.schema.json"
