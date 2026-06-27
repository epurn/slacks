#!/usr/bin/env python3
"""Drift check for the agent prompt preloads.

The author/reviewer prompts and the planner skill hardcode facts about the fatty
repo (package layout, the exact per-package verify commands) and the lane
vocabulary. The agents themselves evolve fatty, so those facts can silently go
stale and start misleading every run. This asserts they still match reality:

  - the package dirs the prompts reference exist in fatty
  - the verify commands the prompts tell agents to run match each package's
    verify.sh (so a changed hook doesn't leave the prompt pointing at dead tools)
  - the planner's documented lane vocabulary matches the steward's lane_for_path
    (and the non-serializing set)

Exits non-zero with specific findings on drift. Run it after fatty changes
(manually, in CI, or the steward runs it at startup and warns on drift).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

CC = Path(__file__).resolve().parents[1]  # command-centre root (fatty-suite)
FATTY = Path(os.environ.get("FATTY_STEWARD_FATTY_REPO_PATH", str(CC / "fatty")))
AUTHOR_PROMPT = CC / "fatty-author-agent" / "prompts" / "implement-story.md"
REVIEWER_PROMPT = CC / "fatty-reviewer-agent" / "prompts" / "review.md"
SKILL = CC / ".claude" / "skills" / "plan-stories" / "SKILL.md"

drift: list[str] = []

if not FATTY.is_dir():
    print(f"check-preloads: skipped — fatty checkout not present at {FATTY}")
    sys.exit(0)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


# 1. Package dirs the prompt map names must exist in the author's worktree.
for d in ("backend", "mobile", "contracts"):
    if not (FATTY / d).is_dir():
        drift.append(f"prompt map names fatty/{d}/ but it does not exist in {FATTY}")

# 2. The verify tools the author prompt tells the agent to run must match the
#    package verify.sh hooks (so the prompt never points at a dead command).
author = read(AUTHOR_PROMPT)
checks = [
    ("backend/verify.sh", ["ruff", "mypy", "pytest"]),
    ("mobile/verify.sh", ["typecheck", "lint", "test"]),
]
for hook, tools in checks:
    hook_text = read(FATTY / hook)
    if not hook_text:
        drift.append(f"{hook} is missing — the prompt map assumes it exists")
        continue
    for tool in tools:
        if tool in author and tool not in hook_text:
            drift.append(f"author prompt tells agents to run '{tool}' but {hook} no longer uses it")

# 3. Planner lane vocabulary must match the steward's lane_for_path return set.
sys.path.insert(0, str(CC / "fatty-steward-agent" / "steward_agent"))
try:
    import runner  # noqa: E402

    steward_lanes = set()
    for sample in ("backend/x.py", "mobile/x.tsx", "contracts/x.py", "infra/x",
                   ".github/x", "docs/security/x.md", "backend/estimator/x.py", "docs/x.md"):
        lane = runner.lane_for_path(sample)
        if lane:
            steward_lanes.add(lane)
    skill = read(SKILL)
    for lane in steward_lanes:
        if lane not in skill:
            drift.append(f"steward lane '{lane}' is not documented in the plan-stories lane vocabulary")
    for lane in runner.NON_SERIALIZING_LANES:
        if lane not in skill:
            drift.append(f"non-serializing lane '{lane}' is not documented in plan-stories")
except Exception as exc:  # never let an import issue masquerade as drift
    print(f"(skipped lane check: {exc})", file=sys.stderr)

if drift:
    print("PRELOAD DRIFT:")
    for d in drift:
        print(f"  - {d}")
    sys.exit(1)
print("check-preloads: ok — agent prompt preloads match the fatty repo")
