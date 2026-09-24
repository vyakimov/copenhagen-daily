"""Validate the editor's clusters: the cheap lexical checks sit after the model, not before it."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_CLUSTER_SIZE = 30
LOW_CONFIDENCE = 0.5
RARE_TERM_SHARE = 0.02
RARE_TERM_FLOOR = 3

_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
_CAPITALISED = re.compile(r"^[A-ZÆØÅ][\wæøåÆØÅ]{2,}$")
_SENTENCE = re.compile(r"[.!?:»«\"']+\s+")


def _terms(article: dict[str, Any]) -> set[str]:
    text = f"{article['title']} {article.get('description') or ''}"
    return {w.lower() for w in _WORD.findall(text)}


def _entities(article: dict[str, Any]) -> set[str]:
    """Capitalised words that do not open a sentence: names, places, institutions."""
    found: set[str] = set()
    for text in (article["title"], article.get("description") or ""):
        for sentence in _SENTENCE.split(text):
            for word in sentence.split()[1:]:
                word = word.strip("«»\"'(),;:.!?")
                if _CAPITALISED.match(word):
                    found.add(word.lower())
    return found


def _ties(article: dict[str, Any], rare_terms: set[str]) -> set[str]:
    """What can justify grouping two articles: a rare term, a named entity, or a section."""
    return rare_terms | _entities(article) | {f"section:{s}" for s in article["sections"]}


def _rare_term_threshold(article_count: int) -> int:
    return max(RARE_TERM_FLOOR, int(article_count * RARE_TERM_SHARE))


def _connected_to_core(members: list[int], ties: dict[int, set[str]]) -> tuple[list[int], list[int]]:
    """Members reachable from the largest component of the shared-term graph, and the rest."""
    if len(members) < 2:
        return members, []
    adjacency = {m: set() for m in members}
    for i, a in enumerate(members):
        for b in members[i + 1 :]:
            if ties[a] & ties[b]:
                adjacency[a].add(b)
                adjacency[b].add(a)
    seen: set[int] = set()
    components = []
    for m in members:
        if m in seen:
            continue
        stack, component = [m], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            component.append(x)
            stack.extend(adjacency[x] - seen)
        components.append(component)
    components.sort(key=lambda c: (-len(c), min(c)))
    core = set(components[0])
    return sorted(core), sorted(m for m in members if m not in core)


def check_clusters(clusters: dict[str, Any], window: dict[str, Any]) -> dict[str, Any]:
    articles = {a["n"]: a for a in window["articles"]}
    frequency: Counter[str] = Counter()
    terms = {n: _terms(a) for n, a in articles.items()}
    for words in terms.values():
        frequency.update(words)
    threshold = _rare_term_threshold(len(articles))
    ties = {n: _ties(articles[n], {w for w in words if frequency[w] <= threshold}) for n, words in terms.items()}

    assigned: set[int] = set()
    checked = []
    for cluster in clusters["clusters"]:
        members: list[int] = []
        removed: list[dict[str, Any]] = []
        flags: list[str] = []
        for n in cluster["members"]:
            if n not in articles:
                removed.append({"n": n, "reason": "unknown_member"})
            elif n in assigned or n in members:
                removed.append({"n": n, "reason": "duplicate_member"})
            else:
                members.append(n)
        if len(members) > MAX_CLUSTER_SIZE:
            flags.append("too_large")
            removed.extend({"n": n, "reason": "too_large"} for n in members)
            members = []
        core, stray = _connected_to_core(members, ties)
        if stray:
            flags.append("split")
            removed.extend({"n": n, "reason": "no_shared_term"} for n in stray)
            members = core
        if cluster.get("confidence", 1.0) < LOW_CONFIDENCE:
            flags.append("low_confidence")
        assigned.update(members)
        checked.append(
            {
                "id": cluster["id"],
                "event": cluster["event"],
                "members": sorted(members),
                "removed": removed,
                "flags": flags,
                "confidence": cluster.get("confidence"),
                "thread": cluster.get("thread"),
            }
        )
    singletons = sorted(n for n in articles if n not in assigned)
    return {
        "schema_version": SCHEMA_VERSION,
        "rare_term_threshold": threshold,
        "clusters": checked,
        "singletons": singletons,
    }


def write_checked(checked: dict[str, Any], run_dir: Path) -> Path:
    path = run_dir / "clusters-checked.json"
    path.write_text(json.dumps(checked, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    return path
