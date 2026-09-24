"""Apply the checker's verdicts: strike, decide whether the story still stands, never rewrite."""

from __future__ import annotations

import copy
import json
import re
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


def _fall_to_headline(story: dict[str, Any]) -> None:
    primary = next((s["source"] for s in story["sources"] if s["primary"]), None)
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
                _fall_to_headline(story)
                fallen.append(story["id"])
            else:
                send_back.append(story["id"])
    return {"edition": edition, "struck": struck_total, "stories": report, "send_back": send_back, "fallen": fallen}
