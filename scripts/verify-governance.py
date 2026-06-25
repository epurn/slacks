#!/usr/bin/env python3
"""Validate Milestone 0 repository governance files.

This is intentionally dependency-free so the first CI gate works before app
toolchains are scaffolded.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "Makefile",
    ".gitignore",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/workflows/governance.yml",
    ".github/workflows/reviewer-gate.yml",
    ".github/dependabot.yml",
    "agents/goals/product-goal.md",
    "agents/goals/development-goal.md",
    "agents/playbooks/story-slicing.md",
    "agents/playbooks/feature-development.md",
    "agents/playbooks/security-privacy-review.md",
    "agents/playbooks/contract-first-change.md",
    "agents/playbooks/pr-authoring.md",
    "agents/reviewer/review-checklist.md",
    "docs/architecture/system-overview.md",
    "docs/standards/coding-standards.md",
    "docs/standards/testing-standards.md",
    "docs/security/security-baseline.md",
    "docs/security/threat-model.md",
    "docs/security/data-retention.md",
    "docs/contracts/README.md",
    "docs/operations/branching-and-prs.md",
    "docs/operations/author-agent-loop.md",
    "docs/operations/github-setup.md",
    "docs/operations/main-branch-protection.json",
    "docs/review-policy.md",
    "docs/stories/README.md",
    "docs/stories/v1-roadmap.md",
    "docs/stories/FTY-001-author-agent-loop.md",
    "docs/stories/FTY-010-monorepo-scaffold.md",
    "docs/adr/0001-agent-operating-system.md",
    "docs/adr/0002-product-architecture.md",
]


def fail(message: str) -> None:
    print(f"governance check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require_terms(path: str, terms: list[str]) -> None:
    content = read(path)
    for term in terms:
        if term not in content:
            fail(f"{path} must include {term!r}")


def validate_story(path: str) -> None:
    required_headings = [
        "## State",
        "## Lane",
        "## Dependencies",
        "## Outcome",
        "## Scope",
        "## Non-Goals",
        "## Contracts",
        "## Security / Privacy",
        "## Acceptance Criteria",
        "## Verification",
    ]
    require_terms(path, required_headings)


def main() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        fail("missing required files: " + ", ".join(missing))

    agents = read("AGENTS.md")
    if len(agents.splitlines()) > 140:
        fail("AGENTS.md is too large; move detail into focused playbooks")

    required_agents_terms = [
        "make verify",
        "security",
        "privacy",
        "reviewer phase",
        "Do not merge or self-approve",
    ]
    for term in required_agents_terms:
        if term not in agents:
            fail(f"AGENTS.md must mention {term!r}")

    pr_template = read(".github/pull_request_template.md")
    pr_template_lower = pr_template.lower()
    for term in ["story", "security", "privacy", "reviewer phase", "tests"]:
        if term not in pr_template_lower:
            fail(f"PR template must include {term!r}")

    codeowners = read(".github/CODEOWNERS")
    for term in ["@epurn", "/.github/CODEOWNERS", "/docs/security/"]:
        if term not in codeowners:
            fail(f"CODEOWNERS must include {term!r}")

    review_policy = read("docs/review-policy.md")
    if "separate reviewer" not in review_policy.lower():
        fail("review policy must require a separate reviewer")
    if "current PR head SHA" not in review_policy:
        fail("review policy must require review on the current PR head SHA")

    roadmap = read("docs/stories/v1-roadmap.md")
    for term in ["FTY-010", "ready_with_notes", "Milestone 1", "Lane", "backend-core", "mobile-core", "estimator"]:
        if term not in roadmap:
            fail(f"v1 roadmap must include {term!r}")
    ready_rows = [line for line in roadmap.splitlines() if re.search(r"\|\s*FTY-\d+\s*\|\s*ready", line)]
    for row in ready_rows:
        match = re.search(r"\]\(([^)]+)\)", row)
        if not match:
            fail(f"ready roadmap row must link to a story file: {row}")
        story_path = ROOT / "docs" / "stories" / match.group(1)
        if not story_path.is_file():
            fail(f"ready roadmap row links to missing story file: {match.group(1)}")

    author_loop = read("docs/operations/author-agent-loop.md").lower()
    for term in ["requested changes", "reviewer agent", "ready_with_notes", "parallel work lanes", "origin/main"]:
        if term not in author_loop:
            fail(f"author-agent loop must include {term!r}")

    reviewer_gate = read(".github/workflows/reviewer-gate.yml")
    for term in ["review.commit_id === pr.head.sha", "review.user.login !== pr.user.login", 'eligibleReviewers.has(review.user.login)']:
        if term not in reviewer_gate:
            fail(f"reviewer gate must include {term!r}")

    protection = json.loads(read("docs/operations/main-branch-protection.json"))
    if protection.get("required_pull_request_reviews") is not None:
        fail("branch protection template must rely on separate-reviewer check, not native required approvals")

    validate_story("docs/stories/FTY-001-author-agent-loop.md")
    validate_story("docs/stories/FTY-010-monorepo-scaffold.md")

    print("governance check passed")


if __name__ == "__main__":
    main()
