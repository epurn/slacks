#!/usr/bin/env python3
"""Validate Milestone 0 repository governance files.

This is intentionally dependency-free so the first CI gate works before app
toolchains are scaffolded.
"""

from __future__ import annotations

from pathlib import Path
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
    "docs/operations/github-setup.md",
    "docs/operations/main-branch-protection.json",
    "docs/review-policy.md",
    "docs/adr/0001-agent-operating-system.md",
    "docs/adr/0002-product-architecture.md",
]


def fail(message: str) -> None:
    print(f"governance check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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

    print("governance check passed")


if __name__ == "__main__":
    main()
