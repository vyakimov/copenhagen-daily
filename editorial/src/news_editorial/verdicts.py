"""Apply the checker's verdicts: strike, decide whether the story still stands, never rewrite."""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .contract import schema_pointer
from .paths import VERDICTS_SCHEMA_PATH

_BOUNDARY = re.compile(r"[.!?…]['\"»)]?\s+(?=[A-ZÆØÅ«\"'(])")
_LOCATION = re.compile(r"^(extended|standard|short|callouts)\[(\d+)\]$")


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(VERDICTS_SCHEMA_PATH.read_text(encoding="utf8")))


def validate_verdicts(doc: Any) -> list[str]:
    return sorted(f"{schema_pointer(e)}: {e.message}" for e in _validator().iter_errors(doc))


def sentences_of(text: str) -> list[str]:
    """Split copy into sentences at terminal punctuation followed by a capital, quote, or bracket."""
    text = text.strip()
    if not text:
        return []
    parts, start = [], 0
    for match in _BOUNDARY.finditer(text):
        parts.append(text[start : match.end()].strip())
        start = match.end()
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def _words(text: str) -> int:
    return len(text.split())


def _story_words(story: dict[str, Any]) -> int:
    total = 0
    if story["copy"].get("lede"):
        total += _words(story["copy"]["lede"]["text"])
    for paragraphs in story["copy"]["body"].values():
        total += sum(_words(p["text"]) for p in paragraphs)
    return total


def _opening(story: dict[str, Any]) -> tuple[str, int] | None:
    """Where the story's opening sentence lives: the first paragraph of its fullest body, else the lede."""
    for variant in ("standard", "extended", "short"):
        if story["copy"]["body"].get(variant):
            return variant, 0
    if story["copy"].get("lede"):
        return "lede", 0
    return None


def _brief_capable(story: dict[str, Any]) -> bool:
    return story["role"] == "brief" or story.get("fallback_role") == "brief"


def _strike_text(text: str, indexes: set[int]) -> str:
    kept = [s for i, s in enumerate(sentences_of(text)) if i not in indexes]
    return " ".join(kept)


def _fall_to_headline(story: dict[str, Any], headline_struck: bool = False) -> None:
    primary = next((s["source"] for s in story["sources"] if s["primary"]), None)
    if headline_struck:
        # The one string the checker refused cannot be the whole story: the primary source's own title
        # is supported by construction and takes its place.
        source = next((s for s in story["sources"] if s["primary"]), story["sources"][0])
        story["copy"]["headline"] = source["original_title"]
        story["copy"].pop("headline_short", None)
    story["copy"]["body"] = {}
    story["copy"].pop("deck", None)
    story["callouts"] = []
    if _brief_capable(story):
        story["copy"]["lede"] = {"text": story["copy"]["headline"], "sources": [primary] if primary else []}
    else:
        story["copy"].pop("lede", None)
    if "headline_only" not in story["limitations"]:
        story["limitations"].append("headline_only")


def apply_verdicts(edition: dict[str, Any], verdicts: dict[str, Any], min_words: float, final: bool = False) -> dict[str, Any]:
    problems = validate_verdicts(verdicts)
    if problems:
        raise ValueError("verdicts do not match their schema: " + "; ".join(problems[:5]))
    edition = copy.deepcopy(edition)
    stories = {s["id"]: s for s in edition["stories"]}
    report: dict[str, dict[str, Any]] = {}
    struck_total = 0
    send_back: list[str] = []
    fallen: list[str] = []
    for entry in verdicts["stories"]:
        story = stories.get(entry["id"])
        if story is None:
            continue
        strikes = [s for s in entry["sentences"] if s["verdict"] == "unsupported"]
        words_before = _story_words(story)
        opening = _opening(story)
        headline_struck = False
        opening_struck = False
        by_location: dict[str, set[int]] = {}
        for strike in strikes:
            by_location.setdefault(strike["location"], set()).add(strike["sentence"])
        for location, indexes in by_location.items():
            struck_total += len(indexes)
            if location == "headline":
                headline_struck = True
                continue
            if location == "headline_short":
                story["copy"].pop("headline_short", None)
                continue
            if location == "deck":
                story["copy"].pop("deck", None)
                continue
            if location == "lede":
                if opening == ("lede", 0) and 0 in indexes:
                    opening_struck = True
                lede = story["copy"].get("lede")
                if lede:
                    text = _strike_text(lede["text"], indexes)
                    if text:
                        lede["text"] = text
                    else:
                        story["copy"].pop("lede")
                continue
            match = _LOCATION.match(location)
            if not match:
                continue
            kind, index = match.group(1), int(match.group(2))
            if kind == "callouts":
                if index < len(story["callouts"]):
                    story["callouts"][index] = None
                continue
            paragraphs = story["copy"]["body"].get(kind)
            if not paragraphs or index >= len(paragraphs):
                continue
            if opening == (kind, index) and 0 in indexes:
                opening_struck = True
            text = _strike_text(paragraphs[index]["text"], indexes)
            paragraphs[index] = {**paragraphs[index], "text": text} if text else None
        story["callouts"] = [c for c in story["callouts"] if c is not None]
        for variant in list(story["copy"]["body"]):
            kept = [p for p in story["copy"]["body"][variant] if p is not None]
            if kept:
                story["copy"]["body"][variant] = kept
            else:
                del story["copy"]["body"][variant]
        if _brief_capable(story) and "lede" not in story["copy"]:
            opening_struck = True
        words_after = _story_words(story)
        share = (words_after / words_before) if words_before else 1.0
        stands = not headline_struck and not opening_struck and share >= min_words
        report[story["id"]] = {
            "stands": stands,
            "strikes": len(strikes),
            "words_before": words_before,
            "words_after": words_after,
            "headline_struck": headline_struck,
            "opening_struck": opening_struck,
            "guideline_notes": entry.get("guideline_notes", []),
        }
        if not stands:
            if final:
                _fall_to_headline(story, headline_struck=headline_struck)
                fallen.append(story["id"])
            else:
                send_back.append(story["id"])
    return {"edition": edition, "struck": struck_total, "stories": report, "send_back": send_back, "fallen": fallen}


def _callout_text(callout: dict[str, Any]) -> str:
    kind = callout["kind"]
    if kind == "quote":
        return f"{callout['text']} ({callout['attribution']})"
    if kind == "figure":
        return f"{callout['value']}: {callout['label']}"
    if kind == "facts":
        return f"{callout['title']}: " + " | ".join(callout["items"])
    if kind == "box":
        return f"{callout['label']}: {callout['text']}"
    return f"{callout['title']}: " + " | ".join(f"{r['date']}: {r['text']}" for r in callout["rows"])


def addresses(check_input_doc: dict[str, Any]) -> set[tuple[str, str, int]]:
    """Every (story, location, sentence) the checker was handed."""
    return {(s["id"], x["location"], x["sentence"]) for s in check_input_doc["stories"] for x in s["sentences"]}


def coverage_problems(check_input_doc: dict[str, Any], verdicts: dict[str, Any]) -> dict[str, list[str]]:
    """Addresses the checker skipped or invented; empty when every sentence has exactly its verdict."""
    expected = addresses(check_input_doc)
    listed = [(s["id"], x["location"], x["sentence"]) for s in verdicts["stories"] for x in s["sentences"]]
    given = set(listed)
    fmt = lambda a: f"{a[0]}/{a[1]}#{a[2]}"  # noqa: E731
    # An address given twice would be struck against copy the first verdict already changed, so a
    # repeat is refused even when both verdicts agree; the same goes for a story listed twice.
    counts = Counter(listed)
    story_counts = Counter(s["id"] for s in verdicts["stories"])
    duplicate = sorted({fmt(a) for a, n in counts.items() if n > 1} | {sid for sid, n in story_counts.items() if n > 1})
    return {
        "missing": sorted(fmt(a) for a in expected - given),
        "unknown": sorted(fmt(a) for a in given - expected),
        "duplicate": duplicate,
    }


def check_input(edition: dict[str, Any], window: dict[str, Any]) -> dict[str, Any]:
    """What the checker reads: every sentence with its address, and the story's evidence. Nothing else."""
    articles = {(a["source"], a["source_id"]): a for a in window["articles"]}
    stories = []
    for story in edition["stories"]:
        copy_ = story["copy"]
        sentences: list[dict[str, Any]] = []

        def add(location: str, text: str, cites: list[str], split: bool = True) -> None:
            parts = sentences_of(text) if split else [text]
            for index, part in enumerate(parts):
                sentences.append({"location": location, "sentence": index, "text": part, "cites": cites})

        everyone = list(dict.fromkeys(s["source"] for s in story["sources"]))
        add("headline", copy_["headline"], everyone, split=False)
        if copy_.get("headline_short"):
            add("headline_short", copy_["headline_short"], everyone, split=False)
        if copy_.get("deck"):
            add("deck", copy_["deck"], everyone, split=False)
        if copy_.get("lede"):
            add("lede", copy_["lede"]["text"], copy_["lede"]["sources"])
        for variant in ("extended", "standard", "short"):
            for index, paragraph in enumerate(copy_["body"].get(variant, [])):
                add(f"{variant}[{index}]", paragraph["text"], paragraph["sources"])
        for index, callout in enumerate(story["callouts"]):
            cites = [callout["attribution_source"]] if callout["kind"] == "quote" else everyone
            add(f"callouts[{index}]", _callout_text(callout), cites, split=False)
        evidence = []
        for source in story["sources"]:
            article = articles.get((source["source"], source["source_id"]))
            if article is None:
                raise ValueError(f"{story['id']}: source {source['source']}/{source['source_id']} is not in the window")
            evidence.append(
                {
                    "source": source["source"],
                    "source_id": source["source_id"],
                    "title": article.get("title") or source["original_title"],
                    "description": article.get("description"),
                    "authors": article.get("authors", []),
                    "categories": article.get("categories", []),
                    "published_at": source["published_at"],
                    "url": source["url"],
                    "primary": source["primary"],
                    "wire": source.get("wire"),
                }
            )
        stories.append({"id": story["id"], "role": story["role"], "sentences": sentences, "evidence": evidence})
    return {"schema_version": 1, "edition_id": edition["edition"]["id"], "stories": stories}


def _strict(node: Any) -> Any:
    """OpenAI-style strict schema: every property typed, required, nullable when optional."""
    if isinstance(node, list):
        return [_strict(n) for n in node]
    if not isinstance(node, dict):
        return node
    node = dict(node)
    node.pop("$schema", None)
    node.pop("$id", None)
    if "const" in node and "type" not in node:
        value = node["const"]
        node["type"] = "integer" if isinstance(value, int) else "string"
    if "enum" in node and "type" not in node:
        node["type"] = "string"
    if node.get("type") == "object" and "properties" in node:
        required = set(node.get("required", []))
        properties = {}
        for key, child in node["properties"].items():
            child = _strict(child)
            if key not in required:
                child.pop("pattern", None)
                child.pop("minimum", None)
                if "enum" in child:
                    child["enum"] = child["enum"] + [None]
                kind = child.get("type")
                if isinstance(kind, list):
                    child["type"] = kind + ["null"] if "null" not in kind else kind
                elif kind is not None:
                    child["type"] = [kind, "null"]
            properties[key] = child
        node["properties"] = properties
        node["required"] = list(properties)
        node["additionalProperties"] = False
    if "items" in node:
        node["items"] = _strict(node["items"])
    return node


@lru_cache(maxsize=1)
def strict_verdicts_schema() -> dict[str, Any]:
    return _strict(json.loads(VERDICTS_SCHEMA_PATH.read_text(encoding="utf8")))


def without_nulls(node: Any) -> Any:
    """Drop null-valued keys a strict-schema checker had to emit for optional fields."""
    if isinstance(node, dict):
        return {k: without_nulls(v) for k, v in node.items() if v is not None}
    if isinstance(node, list):
        return [without_nulls(v) for v in node]
    return node
