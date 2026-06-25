#!/usr/bin/env python3
"""Validate public repository governance files.

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
    "docs/architecture/system-overview.md",
    "docs/standards/coding-standards.md",
    "docs/standards/testing-standards.md",
    "docs/security/security-baseline.md",
    "docs/security/threat-model.md",
    "docs/security/data-retention.md",
    "docs/contracts/README.md",
    "docs/operations/branching-and-prs.md",
    "docs/operations/github-setup.md",
    "docs/operations/main-branch-protection.json",
    "docs/review-policy.md",
    "docs/review-checklist.md",
    "docs/stories/README.md",
    "docs/stories/v1-roadmap.md",
    "docs/stories/FTY-010-monorepo-scaffold.md",
    "docs/adr/0002-product-architecture.md",
]

FORBIDDEN_PATHS = [
    "agents",
    "scripts/steward-router.py",
    "docs/operations/author-agent-loop.md",
    "docs/operations/story-steward-orchestrator.md",
    "docs/stories/FTY-001-author-agent-loop.md",
    "docs/adr/0001-agent-operating-system.md",
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


def validate_ready_story_metadata(path: str) -> None:
    required_terms = [
        "---",
        "id:",
        "state:",
        "primary_lane:",
        "touched_lanes:",
        "risk:",
        "tags:",
        "approved_dependencies:",
        "requires_context:",
        "review_focus:",
        "autonomous:",
        "## Readiness Sanity Pass",
    ]
    require_terms(path, required_terms)


def main() -> None:
    forbidden = [path for path in FORBIDDEN_PATHS if (ROOT / path).exists()]
    if forbidden:
        fail("private automation files must not be public: " + ", ".join(forbidden))

    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        fail("missing required files: " + ", ".join(missing))

    agents = read("AGENTS.md")
    if len(agents.splitlines()) > 120:
        fail("AGENTS.md is too large; move detail into public docs")

    for term in ["make verify", "security", "privacy", "reviewer phase", "Do not merge or self-approve"]:
        if term not in agents:
            fail(f"AGENTS.md must mention {term!r}")

    if "/Users/" in agents or "fatty-worktrees" in agents:
        fail("AGENTS.md must not include machine-specific automation paths")

    pr_template = read(".github/pull_request_template.md")
    pr_template_lower = pr_template.lower()
    for term in ["story", "security", "privacy", "reviewer phase", "tests"]:
        if term not in pr_template_lower:
            fail(f"PR template must include {term!r}")

    codeowners = read(".github/CODEOWNERS")
    for term in ["@epurn", "/.github/CODEOWNERS", "/docs/security/"]:
        if term not in codeowners:
            fail(f"CODEOWNERS must include {term!r}")
    if "/agents/" in codeowners:
        fail("CODEOWNERS must not reference private automation directories")

    review_policy = read("docs/review-policy.md")
    if "separate reviewer" not in review_policy.lower():
        fail("review policy must require a separate reviewer")
    if "current PR head SHA" not in review_policy:
        fail("review policy must require review on the current PR head SHA")

    review_checklist = read("docs/review-checklist.md").lower()
    for term in ["security/privacy", "missing tests", "no secrets", "mobile ui"]:
        if term not in review_checklist:
            fail(f"review checklist must include {term!r}")

    github_setup = read("docs/operations/github-setup.md").lower()
    for term in ["stale approval", "latest reviewable push", "native approving review", "separate-reviewer"]:
        if term not in github_setup:
            fail(f"github setup must document {term!r}")

    branching = read("docs/operations/branching-and-prs.md").lower()
    for term in ["native approving review", "stale approvals", "latest push", "separate-reviewer"]:
        if term not in branching:
            fail(f"branching docs must document {term!r}")

    roadmap = read("docs/stories/v1-roadmap.md")
    for term in ["FTY-010", "ready_with_notes", "Milestone 1", "Lane", "backend-core", "mobile-core", "estimator"]:
        if term not in roadmap:
            fail(f"v1 roadmap must include {term!r}")
    if "author-agent" in roadmap or "story steward" in roadmap.lower():
        fail("public roadmap must not include private agent operations")

    ready_rows = [line for line in roadmap.splitlines() if re.search(r"\|\s*FTY-\d+\s*\|\s*ready", line)]
    for row in ready_rows:
        match = re.search(r"\]\(([^)]+)\)", row)
        if not match:
            fail(f"ready roadmap row must link to a story file: {row}")
        story_path = ROOT / "docs" / "stories" / match.group(1)
        if not story_path.is_file():
            fail(f"ready roadmap row links to missing story file: {match.group(1)}")
        validate_ready_story_metadata(str(story_path.relative_to(ROOT)))

    reviewer_gate = read(".github/workflows/reviewer-gate.yml")
    for term in ["review.commit_id === pr.head.sha", "review.user.login !== pr.user.login"]:
        if term not in reviewer_gate:
            fail(f"reviewer gate must include {term!r}")

    protection = json.loads(read("docs/operations/main-branch-protection.json"))
    checks = protection.get("required_status_checks", {}).get("contexts", [])
    for check in ["governance", "separate-reviewer"]:
        if check not in checks:
            fail(f"branch protection template must require {check!r}")
    required_reviews = protection.get("required_pull_request_reviews")
    if not isinstance(required_reviews, dict):
        fail("branch protection template must require pull request reviews")
    if required_reviews.get("required_approving_review_count") != 1:
        fail("branch protection template must require one native approving review")
    if not required_reviews.get("dismiss_stale_reviews"):
        fail("branch protection template must dismiss stale reviews")
    if not required_reviews.get("require_last_push_approval"):
        fail("branch protection template must require latest-push approval")
    if not protection.get("required_conversation_resolution"):
        fail("branch protection template must require conversation resolution")

    validate_story("docs/stories/FTY-010-monorepo-scaffold.md")

    print("governance checks passed")


if __name__ == "__main__":
    main()
