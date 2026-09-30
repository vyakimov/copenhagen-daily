#!/usr/bin/env python3
"""Cut a small, deterministic test bundle from a real block 1 export.

Keeps every article a golden spec cites, plus every k-th other article, with all their appearances,
drops raw_metadata, and regenerates the manifest so hashes and counts verify. Usage:

    tools/make_bundle_fixture.py <bundle> <spec.json>... --output tests/fixtures/<name> [--every 12]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXCERPT_CHARS = 200


def excerpt(text: str | None) -> str | None:
    if not text or len(text) <= EXCERPT_CHARS:
        return text
    return text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("specs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--every", type=int, default=12)
    args = parser.parse_args()

    refs: set[tuple[str, str]] = set()
    for spec_path in args.specs:
        spec = json.loads(spec_path.read_text())
        for story in spec["stories"]:
            for ref in story["sources"]:
                publisher, suffix = ref.split(":", 1)
                refs.add((publisher, suffix))

    articles = [json.loads(line) for line in (args.bundle / "articles.jsonl").open(encoding="utf8")]
    articles.sort(key=lambda a: (a["source"], a["source_id"]))
    keep: list[dict] = []
    for index, article in enumerate(articles):
        cited = any(article["source"] == p and article["source_id"].endswith(s) for p, s in refs)
        if cited or index % args.every == 0:
            article = dict(article)
            article["raw_metadata"] = {}
            # A fixture carries no more of a publisher's text than a citation would.
            for field in ("description", "public_lead", "public_body"):
                article[field] = excerpt(article.get(field))
            keep.append(article)
    keys = {(a["source"], a["source_id"]) for a in keep}
    appearances = [
        json.loads(line)
        for line in (args.bundle / "appearances.jsonl").open(encoding="utf8")
        if (lambda d: (d["source"], d["source_id"]) in keys)(json.loads(line))
    ]
    appearances.sort(key=lambda a: (a["source"], a["source_id"], a["observed_at"], a["surface_id"]))

    args.output.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, rows in (("articles.jsonl", keep), ("appearances.jsonl", appearances)):
        text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for r in rows)
        data = text.encode("utf8")
        (args.output / name).write_bytes(data)
        files[name] = {"bytes": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
    manifest = json.loads((args.bundle / "manifest.json").read_text())
    manifest.update(
        {"article_count": len(keep), "appearance_count": len(appearances), "files": files}
    )
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf8"
    )
    print(args.output, len(keep), "articles", len(appearances), "appearances")


if __name__ == "__main__":
    main()
