"""Validate an edition the way block 3 does: its JSON Schema, then the same semantic checks.

Block 3's `validate` is still the final preflight; this exists so a malformed edition fails here,
with the same pointers, before a subprocess is spawned.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from .paths import REPO, SCHEMA_PATHS

TITLE_CONFIG = REPO / "publisher" / "config" / "title.yaml"


@lru_cache(maxsize=None)
def _validator(version: int) -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATHS[version].read_text(encoding="utf8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


@lru_cache(maxsize=1)
def _title() -> dict[str, Any]:
    with TITLE_CONFIG.open(encoding="utf8") as handle:
        return yaml.safe_load(handle)


def _pointer(parts: list[Any]) -> str:
    return "/" + "/".join(str(p) for p in parts) if parts else "/"


def schema_pointer(error: Any) -> str:
    """Block 3 points an unknown-field error at the field itself, not at its parent."""
    parts = list(error.absolute_path)
    if error.validator == "additionalProperties":
        match = re.search(r"'([^']+)' (?:was|were) unexpected", error.message)
        if match:
            parts.append(match.group(1))
    elif error.validator == "required":
        match = re.search(r"'([^']+)' is a required property", error.message)
        if match:
            parts.append(match.group(1))
    elif error.validator == "oneOf" and isinstance(error.instance, dict) and "kind" in error.instance:
        # A callout is one of five kinds; point at the missing field of the kind it claims to be.
        branches = error.schema["oneOf"]
        for index, branch in enumerate(branches):
            if branch.get("properties", {}).get("kind", {}).get("const") != error.instance["kind"]:
                continue
            for sub in error.context:
                if list(sub.relative_schema_path)[:1] == [index] and sub.validator == "required":
                    match = re.search(r"'([^']+)' is a required property", sub.message)
                    if match:
                        parts.append(match.group(1))
                        return _pointer(parts)
    return _pointer(parts)


def _https_without_userinfo(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname) and not parts.username and not parts.password


def _semantic(doc: dict[str, Any], title: dict[str, Any]) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    publishers = title["publishers"]
    agencies = title.get("agencies") or {}
    if doc["title"] != title["id"]:
        issues.append(("/title", f"title must equal the configured title id {title['id']}"))
    try:
        dt.date.fromisoformat(doc["edition"]["date"])
    except ValueError:
        issues.append(("/edition/date", "date must be a real calendar date"))
    input_ids: set[str] = set()
    for i, item in enumerate(doc["inputs"]):
        if item["id"] in input_ids:
            issues.append((f"/inputs/{i}/id", "input id must be unique"))
        input_ids.add(item["id"])
    stories = doc["stories"]
    if sum(1 for s in stories if s["role"] == "lead") != 1:
        issues.append(("/stories", "exactly one lead is required"))
    ids: set[str] = set()
    for i, story in enumerate(stories):
        p = f"/stories/{i}"
        if story["id"] in ids:
            issues.append((f"{p}/id", "story id must be unique"))
        ids.add(story["id"])
        if story["role"] == "lead" and (
            i != 0 or story["device_participation"] != "required" or "fallback_role" in story
        ):
            issues.append((f"{p}/role", "the lead must be first, required, and have no fallback"))
        if "fallback_role" in story and story["role"] != "secondary":
            issues.append((f"{p}/fallback_role", "only a secondary may fall back to brief"))
        if (story["role"] == "brief" or story.get("fallback_role") == "brief") and not story["copy"].get("lede"):
            issues.append((f"{p}/copy/lede", "a story that can be a brief requires a lede"))
        sources = story["sources"]
        if sources and sum(1 for s in sources if s["primary"]) != 1:
            issues.append((f"{p}/sources", "sources require exactly one primary"))
        for j, source in enumerate(sources):
            if source["source"] not in publishers:
                issues.append((f"{p}/sources/{j}/source", "publisher mapping is unknown"))
            if "wire" in source and source["wire"] not in agencies:
                issues.append((f"{p}/sources/{j}/wire", "agency mapping is unknown"))
            if source["input_id"] not in input_ids:
                issues.append((f"{p}/sources/{j}/input_id", "input reference does not exist"))
            if not _https_without_userinfo(source["url"]):
                issues.append((f"{p}/sources/{j}/url", "URL must be absolute HTTPS without userinfo"))
        cited = {s["source"] for s in sources}

        def check(pointer: str, value: dict[str, Any] | None) -> None:
            if not value:
                return
            if sources and not value["sources"]:
                issues.append((f"{pointer}/sources", "a sourced story must cite at least one publisher per paragraph"))
            for k, cite in enumerate(value["sources"]):
                if cite not in cited:
                    issues.append((f"{pointer}/sources/{k}", "cited publisher is not among the story's sources"))

        check(f"{p}/copy/lede", story["copy"].get("lede"))
        for variant, paragraphs in story["copy"]["body"].items():
            for k, paragraph in enumerate(paragraphs):
                check(f"{p}/copy/body/{variant}/{k}", paragraph)
        for k, callout in enumerate(story["callouts"]):
            if callout["kind"] == "quote" and callout["attribution_source"] not in cited:
                issues.append(
                    (f"{p}/callouts/{k}/attribution_source", "quote attribution names a publisher not among the story's sources")
                )
    reserve = sorted(s["id"] for s in stories if s["device_participation"] == "reserve")
    optional = sorted(s["id"] for s in stories if s["device_participation"] == "optional")
    policy = doc["fit_policy"]
    if sorted(policy["reserve_story_ids"]) != reserve or len(set(policy["reserve_story_ids"])) != len(policy["reserve_story_ids"]):
        issues.append(("/fit_policy/reserve_story_ids", "list must contain every and only reserve story id"))
    if sorted(policy["omittable_story_ids"]) != optional or len(set(policy["omittable_story_ids"])) != len(policy["omittable_story_ids"]):
        issues.append(("/fit_policy/omittable_story_ids", "list must contain every and only optional story id"))
    feeds = doc["coverage"]["feeds"]
    status = doc["coverage"]["status"]
    if not feeds and status != "unknown":
        issues.append(("/coverage/status", "an empty inventory requires unknown coverage"))
    if any(f["outcome"] != "checked" for f in feeds) and status != "partial":
        issues.append(("/coverage/status", "failed or unchecked feeds require partial coverage"))
    if feeds and all(f["outcome"] == "checked" for f in feeds) and status != "complete":
        issues.append(("/coverage/status", "all checked feeds require complete coverage"))
    for i, feed in enumerate(feeds):
        if feed["outcome"] == "not_checked" and feed["last_checked_at"] is not None:
            issues.append((f"/coverage/feeds/{i}/last_checked_at", "not_checked requires null"))
        if feed["outcome"] != "not_checked" and feed["last_checked_at"] is None:
            issues.append((f"/coverage/feeds/{i}/last_checked_at", "a checked or failed feed requires a timestamp"))
    return issues


def validate_edition(document: Any) -> list[str]:
    """Return `pointer: message` strings; an empty list means block 3 will accept the document."""
    version = document.get("schema_version") if isinstance(document, dict) else None
    if isinstance(version, bool) or version not in SCHEMA_PATHS:
        return ["/schema_version: supported edition schema versions are 1 and 2"]
    schema_errors = sorted(
        (schema_pointer(e), e.message) for e in _validator(version).iter_errors(document)
    )
    if schema_errors:
        return [f"{p}: {m}" for p, m in schema_errors]
    return [f"{p}: {m}" for p, m in _semantic(document, _title())]
