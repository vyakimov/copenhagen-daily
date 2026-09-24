"""Read a block 1 export bundle and refuse one whose manifest does not verify."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {1}


class BundleError(Exception):
    pass


@dataclass(frozen=True)
class Bundle:
    path: Path
    manifest: dict[str, Any]
    manifest_sha256: str
    articles: list[dict[str, Any]]
    appearances: list[dict[str, Any]]

    @property
    def window(self) -> tuple[str, str]:
        return self.manifest["window"]["since"], self.manifest["window"]["until"]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_bundle(path: Path) -> Bundle:
    path = Path(path)
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise BundleError(f"{path}: manifest.json is missing")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise BundleError(f"{path}: unsupported bundle schema version {manifest.get('schema_version')!r}")
    for name, expected in manifest["files"].items():
        data = (path / name).read_bytes()
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if digest != expected["sha256"] or len(data) != expected["bytes"]:
            raise BundleError(f"{path}: {name} does not match its manifest hash")
    articles = _read_jsonl(path / "articles.jsonl")
    appearances = _read_jsonl(path / "appearances.jsonl")
    if len(articles) != manifest["article_count"]:
        raise BundleError(f"{path}: article_count {manifest['article_count']} but {len(articles)} rows")
    if len(appearances) != manifest["appearance_count"]:
        raise BundleError(
            f"{path}: appearance_count {manifest['appearance_count']} but {len(appearances)} rows"
        )
    return Bundle(
        path=path,
        manifest=manifest,
        manifest_sha256="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        articles=articles,
        appearances=appearances,
    )
