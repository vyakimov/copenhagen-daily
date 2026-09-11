"""Deterministic publisher-prominence signals derived from feed placement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Surface = Literal["homepage_rss", "latest_rss", "section_rss", "homepage"]
ProminenceTier = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class Prominence:
    score: float
    tier: ProminenceTier
    evidence: str


# A rank in a publisher-controlled homepage snapshot is direct prominence
# evidence. Latest and section feeds remain useful discovery/order signals but
# have deliberately lower ceilings because they are not claims about a homepage.
SURFACE_CEILINGS: dict[Surface, float] = {
    "homepage": 1.0,
    "homepage_rss": 1.0,
    "latest_rss": 0.65,
    "section_rss": 0.50,
}


def derive_prominence(
    *,
    source: str,
    surface: Surface,
    position: int,
    snapshot_item_count: int,
    publisher_order: int | None = None,
) -> Prominence:
    """Return a source-local score; never compare raw rank across publishers.

    The score is the rank percentile within the observed surface, capped by the
    strength of that surface as prominence evidence. Politiken's explicit
    publisher order is preferred over XML position when present.
    """
    if position <= 0 or snapshot_item_count <= 0:
        raise ValueError("position and snapshot_item_count must be positive")

    rank = publisher_order if source == "politiken" and publisher_order else position
    rank = min(max(rank, 1), snapshot_item_count)
    percentile = (snapshot_item_count - rank + 1) / snapshot_item_count
    score = round(SURFACE_CEILINGS[surface] * percentile, 4)

    if score >= 0.75:
        tier: ProminenceTier = "high"
    elif score >= 0.40:
        tier = "medium"
    else:
        tier = "low"

    order_kind = "publisher_order" if source == "politiken" and publisher_order else "feed_position"
    evidence = f"{surface}:{order_kind}"
    return Prominence(score=score, tier=tier, evidence=evidence)
