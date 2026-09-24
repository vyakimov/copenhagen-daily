"""Resolve a spec into an edition contract. Sources come from evidence, never from the editor's hand."""

from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .bundle import Bundle
from .contract import schema_pointer, validate_edition
from .paths import SPEC_SCHEMA_PATH

TITLE = "copenhagen-daily"
TIMEZONE = "Europe/Copenhagen"
LANGUAGE = "en"


class BuildError(Exception):
    pass


@lru_cache(maxsize=1)
def _spec_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SPEC_SCHEMA_PATH.read_text(encoding="utf8")), format_checker=FormatChecker())


def validate_spec(spec: Any) -> list[str]:
    return sorted(f"{schema_pointer(e)}: {e.message}" for e in _spec_validator().iter_errors(spec))


def _ts(value: str) -> str:
    return value if "." in value else value.replace("Z", ".000000Z")


class Resolver:
    def __init__(self, bundle: Bundle, window: dict[str, Any] | None):
        self.articles = bundle.articles
        self.by_key = {(a["source"], a["source_id"]): a for a in bundle.articles}
        self.by_number = {}
        if window:
            for row in window["articles"]:
                self.by_number[row["n"]] = (row["source"], row["source_id"])

    def resolve(self, ref: Any, story_id: str) -> dict[str, Any]:
        if isinstance(ref, int):
            key = self.by_number.get(ref)
            if key is None or key not in self.by_key:
                raise BuildError(f"{story_id}: source [{ref}] is not in the window")
            return self.by_key[key]
        publisher, suffix = ref.split(":", 1)
        hits = [a for a in self.articles if a["source"] == publisher and suffix and a["source_id"].endswith(suffix)]
        if len(hits) != 1:
            raise BuildError(f"{story_id}: source {ref!r} resolves to {len(hits)} articles, not one")
        return hits[0]


def _source(article: dict[str, Any], input_id: str, primary: bool) -> dict[str, Any]:
    return {
        "source": article["source"],
        "source_id": article["source_id"],
        "input_id": input_id,
        "original_title": article["title"],
        "url": article["canonical_url"],
        "published_at": _ts(article["published_at"]),
        "content_hash": article["content_hash"],
        "primary": primary,
    }


def _story(spec: dict[str, Any], resolver: Resolver, input_id: str, scoring: set[str], corroborating: set[str]) -> dict[str, Any]:
    story_id = spec["id"]
    articles = [resolver.resolve(ref, story_id) for ref in spec["sources"]]
    seen: set[tuple[str, str]] = set()
    for a in articles:
        key = (a["source"], a["source_id"])
        if key in seen:
            raise BuildError(f"{story_id}: source {key[0]}:{key[1]} listed twice")
        seen.add(key)
    sources = [_source(a, input_id, primary=(i == 0)) for i, a in enumerate(articles)]
    publishers = [s["source"] for s in sources]
    cited = set(publishers)
    danish = scoring | corroborating
    if sources[0]["source"] not in scoring:
        raise BuildError(f"{story_id}: the primary source must be a scoring publisher, not {sources[0]['source']}")

    def para(item: list[Any], where: str) -> dict[str, Any]:
        text, cites = item
        for c in cites:
            if c not in cited:
                raise BuildError(f"{story_id}: {where} cites {c}, which is not among the story's sources")
        return {"text": text, "sources": list(dict.fromkeys(cites))}

    copy: dict[str, Any] = {"headline": spec["headline"], "body": {}}
    for key in ("headline_short", "deck"):
        if key in spec:
            copy[key] = spec[key]
    if "lede" in spec:
        copy["lede"] = para(spec["lede"], "lede")
    for variant in ("extended", "standard", "short"):
        if variant in spec:
            copy["body"][variant] = [para(p, f"{variant}[{i}]") for i, p in enumerate(spec[variant])]
    for k, callout in enumerate(spec.get("callouts", [])):
        if callout["kind"] == "quote" and callout["attribution_source"] not in cited:
            raise BuildError(f"{story_id}: callouts[{k}] attributes a quote to {callout['attribution_source']}, not a source")
    limitations = ["digest_of_rss_description"]
    if any(p in danish for p in publishers):
        limitations.append("translated_from_source_language")
    if not articles[0].get("description"):
        limitations.append("headline_only")
    if spec.get("partial"):
        limitations.append("partial_source_coverage")
    story = {
        "id": story_id,
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


def build_edition(
    spec: dict[str, Any],
    bundle: Bundle,
    feeds: list[dict[str, Any]],
    window: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    scoring: set[str] | None = None,
    corroborating: set[str] | None = None,
) -> dict[str, Any]:
    errors = validate_spec(spec)
    if errors:
        raise BuildError("spec does not match its schema: " + "; ".join(errors[:5]))
    if memory:
        published = {s["id"]: e["id"] for e in memory["editions"] for s in e["stories"]}
        for story in spec["stories"]:
            if story["id"] in published:
                raise BuildError(f"{story['id']}: already published in {published[story['id']]}; a story id is minted once")
    from .paths import POLICY_PATH
    from .policy import load_policy

    if scoring is None or corroborating is None:
        policy = load_policy(POLICY_PATH)
        scoring = set(policy.scoring_publishers)
        corroborating = set(policy.corroborating_publishers)
    edition = spec["edition"]
    resolver = Resolver(bundle, window)
    stories = [_story(s, resolver, edition["input_id"], scoring, corroborating) for s in spec["stories"]]
    feeds = sorted(feeds, key=lambda f: f["feed_id"])
    generated_at = edition.get("generated_at") or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    doc = {
        "schema_version": 1,
        "title": TITLE,
        "edition": {
            "id": edition["id"],
            "number": edition["number"],
            "name": edition["name"],
            "date": edition["date"],
            "timezone": TIMEZONE,
            "language": LANGUAGE,
            "cutoff_at": _ts(edition["cutoff_at"]),
            "generated_at": generated_at,
        },
        "presentation": edition["presentation"],
        "coverage": {
            "status": "complete" if feeds and all(f["outcome"] == "checked" for f in feeds) else ("partial" if feeds else "unknown"),
            "checked_from": _ts(edition["checked_from"]),
            "checked_until": _ts(edition["cutoff_at"]),
            "feeds": feeds,
            "note": edition["note"],
        },
        "inputs": [{"id": edition["input_id"], "sha256": bundle.manifest_sha256}],
        "stories": stories,
        "fit_policy": {
            "allow_role_fallback": True,
            "allow_composition_substitution": True,
            "reserve_story_ids": [s["id"] for s in stories if s["device_participation"] == "reserve"],
            "omittable_story_ids": [s["id"] for s in stories if s["device_participation"] == "optional"],
        },
    }
    problems = validate_edition(doc)
    if problems:
        raise BuildError("the built edition fails the contract: " + "; ".join(problems[:5]))
    return doc


def write_edition(edition: dict[str, Any], path: Path) -> Path:
    path.write_text(json.dumps(edition, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return path
