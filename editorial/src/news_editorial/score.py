"""The visible formula. Every term is written down so the editor can overrule it in a sentence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .policy import Policy

SCHEMA_VERSION = 1
EDITION_DECAY = [1.0, 0.45, 0.15]
FULL_BREADTH = 10


def breadth_norm(n: int) -> float:
    """Concave in the publisher count, so the second publisher is the largest step; ten is full."""
    if n <= 0:
        return 0.0
    if n >= FULL_BREADTH:
        return 1.0
    return round((n / (n + 1)) / (FULL_BREADTH / (FULL_BREADTH + 1)), 6)


def recency_for(published_at: str, previous_cutoffs: list[str]) -> float:
    """1.0 for anything since the previous cutoff, then one step per edition back."""
    for index, cutoff in enumerate(previous_cutoffs):
        if published_at >= cutoff:
            return EDITION_DECAY[min(index, len(EDITION_DECAY) - 1)]
    return EDITION_DECAY[-1]


def _decay(editions_since: int | None) -> float:
    if editions_since is None or editions_since < 1:
        return 0.0
    return EDITION_DECAY[min(editions_since - 1, len(EDITION_DECAY) - 1)]


def _candidate(
    cid: str,
    event: str | None,
    members: list[int],
    thread: Any,
    articles: dict[int, dict[str, Any]],
    memory: dict[str, Any],
    policy: Policy,
    previous_cutoffs: list[str],
    threads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = [articles[n] for n in members]
    scoring = [a for a in rows if a["status"] == "scoring"]
    scoring_publishers = sorted({a["source"] for a in scoring})
    linked_publishers = sorted({a["source"] for a in rows if a["status"] == "linked"})
    corroborating = sorted({a["source"] for a in rows if a["status"] == "corroborating"})
    breadth = len(scoring_publishers)
    covered_hits = [
        (a["n"], memory["covered"][f"{a['source']}:{a['source_id']}"])
        for a in rows
        if f"{a['source']}:{a['source_id']}" in memory["covered"]
    ]
    prominence_scores = [a["prominence"]["score"] for a in scoring if a["prominence"]]
    peak_prominence = max(prominence_scores) if prominence_scores else None
    latest = max((a["published_at"] for a in scoring), default=max(a["published_at"] for a in rows))
    recency = recency_for(latest, previous_cutoffs)
    thread_strength = 0.0
    thread_id = thread.get("id") if isinstance(thread, dict) else None
    if thread_id and thread_id in threads:
        known = threads[thread_id]
        thread_strength = round(breadth_norm(known.get("peak_breadth", 0)) * _decay(known.get("editions_since_published")), 6)
    sections = sorted({s for a in scoring for s in a["sections"]})
    if sections:
        section_weight = max(policy.section_weights.get(s, policy.unsectioned_weight) for s in sections)
    else:
        section_weight = policy.unsectioned_weight
    terms = {
        "breadth": breadth_norm(breadth),
        "peak_prominence": peak_prominence,
        "recency": recency,
        "thread_strength": thread_strength,
    }
    weights = policy.weights.model_dump()
    known_terms = {k: v for k, v in terms.items() if v is not None}
    base = sum(weights[k] * v for k, v in known_terms.items()) / sum(weights[k] for k in known_terms)
    score = round(base * section_weight, 6)
    if breadth == 0:
        decision = "not_in_danish_media"
    elif covered_hits:
        decision = "already_covered"
    else:
        decision = "eligible"
    covered_by = None
    if covered_hits:
        first = covered_hits[0][1]
        covered_by = {**first, "articles": sorted(n for n, _ in covered_hits)}
    return {
        "id": cid,
        "event": event,
        "members": sorted(members),
        "scoring_publishers": scoring_publishers,
        "linked_publishers": linked_publishers,
        "corroborating_publishers": corroborating,
        "breadth": breadth,
        "sections": sections,
        "opinion_only": bool(rows) and all(a["opinion"] for a in rows),
        "latest_published_at": latest,
        "newly_observed": any(a["newly_observed"] for a in rows),
        "terms": terms,
        "section_weight": section_weight,
        "base": round(base, 6),
        "score": score,
        "thread": thread,
        "eligible": decision == "eligible",
        "decision": decision,
        "covered_by": covered_by,
        "rank": None,
    }


def rank(checked: dict[str, Any], window: dict[str, Any], memory: dict[str, Any], policy: Policy) -> dict[str, Any]:
    articles = {a["n"]: a for a in window["articles"]}
    previous_cutoffs = [e["cutoff_at"] for e in memory["editions"]]
    if not previous_cutoffs:
        # No published edition yet: fall back to whole days before the cutoff.
        import datetime as dt

        cutoff = dt.datetime.fromisoformat(window["cutoff_at"].replace("Z", "+00:00"))
        previous_cutoffs = [
            (cutoff - dt.timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S.%fZ") for d in (1, 2)
        ]
    threads = {t["id"]: t for t in memory["threads"] + memory.get("dormant_threads", [])}
    candidates = []
    for cluster in checked["clusters"]:
        if not cluster["members"]:
            continue
        candidates.append(
            _candidate(cluster["id"], cluster["event"], cluster["members"], cluster.get("thread"), articles, memory, policy, previous_cutoffs, threads)
        )
    for n in checked["singletons"]:
        candidates.append(_candidate(f"s{n}", None, [n], None, articles, memory, policy, previous_cutoffs, threads))
    eligible = [c for c in candidates if c["eligible"]]
    # Highest score, then broadest, then the fresher story, then the id for determinism.
    eligible.sort(key=lambda c: c["id"])
    eligible.sort(key=lambda c: c["latest_published_at"], reverse=True)
    eligible.sort(key=lambda c: (-c["score"], -c["breadth"]))
    for position, candidate in enumerate(eligible, start=1):
        candidate["rank"] = position
        if position > policy.limits.stories_written:
            candidate["decision"] = "outside_budget"
    candidates.sort(key=lambda c: (c["rank"] is None, c["rank"] or 0, -c["score"], c["id"]))
    top = [c for c in eligible[: policy.limits.stories_written]]
    notes = []
    if top:
        section_counts: dict[str, int] = {}
        for c in top:
            for s in c["sections"] or ["unsectioned"]:
                section_counts[s] = section_counts.get(s, 0) + 1
        for section, count in sorted(section_counts.items()):
            if count * 2 > len(top):
                notes.append(f"section {section} holds {count} of the top {len(top)}; the handbook caps a section at half the page")
        sole: dict[str, int] = {}
        for c in top:
            if len(c["scoring_publishers"]) == 1:
                sole[c["scoring_publishers"][0]] = sole.get(c["scoring_publishers"][0], 0) + 1
        for publisher, count in sorted(sole.items()):
            if count * 2 > len(top):
                notes.append(f"{publisher} is the sole scoring publisher on {count} of the top {len(top)}")
    return {
        "schema_version": SCHEMA_VERSION,
        "formula": "base = (0.45 breadth + 0.10 peak_prominence + 0.30 recency + 0.15 thread_strength) / known weights; score = base x section_weight",
        "weights": policy.weights.model_dump(),
        "previous_cutoffs": previous_cutoffs,
        "limits": {"stories_written": policy.limits.stories_written},
        "diversity_notes": notes,
        "candidates": candidates,
    }


def write_ranking(ranking: dict[str, Any], run_dir: Path) -> Path:
    path = run_dir / "ranking.json"
    path.write_text(json.dumps(ranking, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    return path
