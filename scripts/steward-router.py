#!/usr/bin/env python3
"""Deterministic story steward router for cheap no-action decisions."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Iterable


ROADMAP_ROW = re.compile(
    r"^\|\s*(FTY-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$"
)
READY_STATES = {"ready", "ready_with_notes"}
BLOCKED_STATES = {"changes_requested"}


@dataclass(frozen=True)
class Story:
    story_id: str
    state: str
    lane: str
    lanes: tuple[str, ...]
    title: str
    acceptance: str


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    story_id: str | None = None
    lane: str | None = None
    invoke_steward: bool = False


def normalize_cell(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).strip().strip("`")


def title_text(value: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", normalize_cell(value))


def linked_story_path(value: str, roadmap_path: Path) -> Path | None:
    match = re.search(r"\]\(([^)]+)\)", value)
    if not match:
        return None
    return roadmap_path.parent / match.group(1)


def metadata_lanes(path: Path, fallback_lane: str) -> tuple[str, ...]:
    if not path.is_file():
        return (fallback_lane,)
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return (fallback_lane,)
    end = content.find("\n---", 3)
    if end == -1:
        return (fallback_lane,)
    header = content[3:end]
    lanes: list[str] = []
    primary = re.search(r"^primary_lane:\s*(.+)$", header, re.MULTILINE)
    if primary:
        lanes.append(primary.group(1).strip())
    touched = re.search(r"^touched_lanes:\s*\n((?:\s+-\s+.+\n?)*)", header, re.MULTILINE)
    if touched:
        lanes.extend(line.split("-", 1)[1].strip() for line in touched.group(1).splitlines() if "-" in line)
    if fallback_lane not in lanes:
        lanes.insert(0, fallback_lane)
    return tuple(dict.fromkeys(lanes))


def parse_roadmap(path: Path) -> list[Story]:
    stories: list[Story] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ROADMAP_ROW.match(line)
        if not match:
            continue
        raw_story_id, raw_state, raw_lane, raw_title, raw_acceptance = match.groups()
        story_id, state, lane, acceptance = (normalize_cell(part) for part in [raw_story_id, raw_state, raw_lane, raw_acceptance])
        if story_id == "ID":
            continue
        story_path = linked_story_path(raw_title, path)
        stories.append(Story(story_id, state, lane, metadata_lanes(story_path, lane) if story_path else (lane,), title_text(raw_title), acceptance))
    return stories


def parse_lanes(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def lanes_available(story_lanes: Iterable[str], open_pr_lanes: set[str]) -> bool:
    return set(story_lanes).isdisjoint(open_pr_lanes)


def choose_decision(
    stories: list[Story],
    open_pr_lanes: set[str],
    ready_threshold: int,
    event: str,
    active_authors: int,
    max_authors: int,
) -> Decision:
    if active_authors >= max_authors:
        return Decision("no_action", f"active author limit reached: {active_authors}/{max_authors}.")

    blocked = [story for story in stories if story.state in BLOCKED_STATES]
    if blocked:
        story = blocked[0]
        return Decision("fix_blocked_pr", f"{story.story_id} is {story.state}.", story.story_id, story.lane)

    if event in {"planning_notes", "story_blocked_twice"}:
        return Decision("invoke_steward", f"{event} requires steward judgment.", invoke_steward=True)

    ready = [story for story in stories if story.state in READY_STATES]
    if len(ready) < ready_threshold:
        return Decision(
            "invoke_steward",
            f"ready queue has {len(ready)} stories; threshold is {ready_threshold}.",
            invoke_steward=True,
        )

    available = [story for story in ready if lanes_available(story.lanes, open_pr_lanes)]
    if not available:
        return Decision("no_action", "no ready story has an available lane.")

    story = available[0]
    return Decision("assign_story", f"{story.story_id} is ready and lane {story.lane} is available.", story.story_id, story.lane)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roadmap", default="docs/stories/v1-roadmap.md")
    parser.add_argument("--open-pr-lanes", default="")
    parser.add_argument("--ready-threshold", type=int, default=1)
    parser.add_argument("--active-authors", type=int, default=0)
    parser.add_argument("--max-authors", type=int, default=2)
    parser.add_argument(
        "--event",
        choices=["queue_check", "pr_merged", "planning_notes", "story_blocked_twice"],
        default="queue_check",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    decision = choose_decision(
        parse_roadmap(Path(args.roadmap)),
        parse_lanes(args.open_pr_lanes),
        args.ready_threshold,
        args.event,
        args.active_authors,
        args.max_authors,
    )
    if args.json:
        print(json.dumps(asdict(decision), sort_keys=True))
        return
    target = f" story={decision.story_id}" if decision.story_id else ""
    lane = f" lane={decision.lane}" if decision.lane else ""
    print(f"{decision.action}:{target}{lane} {decision.reason}")


if __name__ == "__main__":
    main()
