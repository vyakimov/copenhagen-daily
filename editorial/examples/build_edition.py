"""Assemble an edition contract from a compact editorial spec (reference implementation).

This is the hand-run tool used for the golden example. Block 2 proper replaces it; it is kept so the
example can be rebuilt and so the source-resolution rule is executable rather than described.

Sources are resolved from the block 1 export bundle by (publisher, id suffix), so
identity, URL, timestamp and content hash come from the evidence, never by hand.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

DANISH = {"dr", "politiken", "berlingske", "borsen", "tv2", "jp", "information", "altinget", "kristeligt_dagblad"}


def load_bundle(path: Path) -> list[dict]:
    return [json.loads(line) for line in (path / "articles.jsonl").open()]


def ts(value: str) -> str:
    return value if "." in value else value.replace("Z", ".000000Z")


class Builder:
    def __init__(self, bundle: Path, input_id: str):
        self.articles = load_bundle(bundle)
        self.input_id = input_id
        self.input_sha = "sha256:" + hashlib.sha256((bundle / "manifest.json").read_bytes()).hexdigest()

    def source(self, ref: str, primary: bool = False) -> dict:
        publisher, suffix = ref.split(":", 1)
        hits = [a for a in self.articles if a["source"] == publisher and a["source_id"].endswith(suffix)]
        if len(hits) != 1:
            raise SystemExit(f"{ref}: {len(hits)} hits")
        a = hits[0]
        return {
            "source": a["source"],
            "source_id": a["source_id"],
            "input_id": self.input_id,
            "original_title": a["title"],
            "url": a["canonical_url"],
            "published_at": ts(a["published_at"]),
            "content_hash": a["content_hash"],
            "primary": primary,
        }

    def story(self, spec: dict) -> dict:
        refs = spec["sources"]
        sources = [self.source(r, primary=(i == 0)) for i, r in enumerate(refs)]
        publishers = [s["source"] for s in sources]
        assert len(set(publishers)) == len(publishers) or True  # a publisher may contribute two articles
        cited = set(publishers)

        def para(p):
            text, cites = p
            for c in cites:
                assert c in cited, f"{spec['id']}: cites {c} not in sources"
            return {"text": text, "sources": list(dict.fromkeys(cites))}

        copy = {"headline": spec["headline"], "body": {}}
        for key in ("headline_short", "deck"):
            if key in spec:
                copy[key] = spec[key]
        if "lede" in spec:
            copy["lede"] = para(spec["lede"])
        for variant in ("extended", "standard", "short"):
            if variant in spec:
                copy["body"][variant] = [para(p) for p in spec[variant]]
        limitations = ["digest_of_rss_description"]
        if any(p in DANISH for p in publishers):
            limitations.append("translated_from_source_language")
        primary_desc = next(a for a in self.articles if a["source"] == sources[0]["source"] and a["source_id"] == sources[0]["source_id"]).get("description")
        if not primary_desc:
            limitations.append("headline_only")
        if not all(p in DANISH for p in publishers):
            limitations.append("partial_source_coverage") if spec.get("partial") else None
        story = {
            "id": spec["id"],
            "device_participation": spec.get("device", "required"),
            "role": spec["role"],
            "kicker": spec["kicker"],
            "copy": copy,
            "callouts": spec.get("callouts", []),
            "sources": sources,
            "limitations": limitations,
        }
        if spec["role"] == "secondary" and spec.get("fallback"):
            story["fallback_role"] = "brief"
        if "kicker_secondary" in spec:
            story["kicker_secondary"] = spec["kicker_secondary"]
        return story


def build(edition: dict, stories: list[dict], bundle: Path, feeds_path: Path, out: Path) -> None:
    b = Builder(bundle, edition["input_id"])
    built = [b.story(s) for s in stories]
    feeds = json.load(feeds_path.open())
    feeds.sort(key=lambda f: f["feed_id"])
    doc = {
        "schema_version": 1,
        "title": "copenhagen-daily",
        "edition": {
            "id": edition["id"],
            "number": edition["number"],
            "name": edition["name"],
            "date": edition["date"],
            "timezone": "Europe/Copenhagen",
            "language": "en",
            "cutoff_at": edition["cutoff_at"],
            "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        },
        "presentation": edition["presentation"],
        "coverage": {
            "status": "complete" if all(f["outcome"] == "checked" for f in feeds) else "partial",
            "checked_from": edition["checked_from"],
            "checked_until": edition["cutoff_at"],
            "feeds": feeds,
            "note": edition["note"],
        },
        "inputs": [{"id": edition["input_id"], "sha256": b.input_sha}],
        "stories": built,
        "fit_policy": {
            "allow_role_fallback": True,
            "allow_composition_substitution": True,
            "reserve_story_ids": [s["id"] for s in built if s["device_participation"] == "reserve"],
            "omittable_story_ids": [s["id"] for s in built if s["device_participation"] == "optional"],
        },
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    print(out, len(built), "stories", sum(len(s["sources"]) for s in built), "sources")


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    build(spec["edition"], spec["stories"], Path(spec["bundle"]), Path(spec["feeds"]), Path(sys.argv[2]))
