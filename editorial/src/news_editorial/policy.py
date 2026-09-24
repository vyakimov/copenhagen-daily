"""The masthead's standing line, read from policy.yaml at every run."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edition: str
    cutoff_local: str
    candidate_window_hours: int
    memory_editions: int
    thread_dormant_days: int


class Weights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    breadth: float
    peak_prominence: float
    recency: float
    thread_strength: float


class DeviceCapacity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secondary: int
    brief: int


class Budgets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_words: list[int]
    secondary_words: list[int]
    brief_words: int
    device_capacity: DeviceCapacity


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stories_written: int
    fit_rounds_with_editor: int
    check_send_backs: int
    story_stands_min_words: float
    editor_minutes: int
    editor_turns: int
    checker_minutes: int
    checker_turns: int
    run_minutes: int


class Sources(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_per_story: int
    one_article_per_publisher: bool
    exclude_unless_sole_coverage: list[str]


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    masthead: str
    language: str
    timezone: str
    schedule: Schedule
    scoring_publishers: list[str]
    corroborating_publishers: list[str]
    weights: Weights
    section_weights: dict[str, float]
    unsectioned_weight: float
    kickers: dict[str, list[str]]
    budgets: Budgets
    limits: Limits
    sources: Sources
    feed_sections: dict[str, list[str]]
    ranked_feeds: list[str]

    def publisher_status(self, publisher: str) -> Literal["scoring", "corroborating", "linked"]:
        if publisher in self.scoring_publishers:
            return "scoring"
        if publisher in self.corroborating_publishers:
            return "corroborating"
        return "linked"


def load_policy(path: Path) -> Policy:
    with path.open(encoding="utf8") as handle:
        data = yaml.safe_load(handle)
    return Policy.model_validate(data)
