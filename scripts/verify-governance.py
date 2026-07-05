#!/usr/bin/env python3
"""Validate public repository governance files.

This is intentionally dependency-free so the first CI gate works before app
toolchains are scaffolded.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "Makefile",
    ".gitignore",
    "scripts/code-shape-baseline.json",
    "scripts/verify-code-shape.py",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/workflows/governance.yml",
    ".github/workflows/mobile.yml",
    ".github/workflows/mobile-e2e.yml",
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
    "docs/adr/0002-product-architecture.md",
]

# Stories live in the private command-centre repo, not here — the steward embeds
# each spec into the author assignment. Forbid the directory so they never leak
# back into the public app repo.
FORBIDDEN_PATHS = [
    "agents",
    "scripts/steward-router.py",
    "docs/operations/author-agent-loop.md",
    "docs/operations/story-steward-orchestrator.md",
    "docs/stories",
    "docs/adr/0001-agent-operating-system.md",
]

REQUIRED_STATUS_CHECKS = [
    "governance",
    "reviewer-approved",
    "mobile",
]

STALE_REQUIRED_MOBILE_E2E_TEXT = [
    "Require `mobile-e2e`",
    "require the `mobile-e2e` status check",
    "`mobile-e2e` (mobile end-to-end Maestro smoke gate",
    "rely on the `mobile-e2e` CI job to enforce",
]


def fail(message: str) -> None:
    print(f"governance check failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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

    github_setup_text = read("docs/operations/github-setup.md")
    github_setup = github_setup_text.lower()
    for term in ["required native approving reviews to zero", "app-reviewer flow", "reviewer-approved"]:
        if term not in github_setup:
            fail(f"github setup must document {term!r}")
    for check in REQUIRED_STATUS_CHECKS:
        if f"`{check}`" not in github_setup_text:
            fail(f"github setup must document required status check {check!r}")
    if "`mobile-e2e`" not in github_setup_text or "remove the historical required status" not in github_setup:
        fail("github setup must document removing the historical required 'mobile-e2e' status check")
    for stale in STALE_REQUIRED_MOBILE_E2E_TEXT:
        if stale in github_setup_text:
            fail(f"github setup still describes mobile-e2e as required: {stale!r}")

    branching_text = read("docs/operations/branching-and-prs.md")
    branching = branching_text.lower()
    for term in ["native required approving review count at zero", "app-reviewer flow", "reviewer-approved"]:
        if term not in branching:
            fail(f"branching docs must document {term!r}")
    for check in REQUIRED_STATUS_CHECKS:
        if f"`{check}`" not in branching_text:
            fail(f"branching docs must document required status check {check!r}")
    if "`mobile-e2e`" not in branching_text or "remove the historical required status" not in branching:
        fail("branching docs must document removing the historical required 'mobile-e2e' status check")
    for stale in STALE_REQUIRED_MOBILE_E2E_TEXT:
        if stale in branching_text:
            fail(f"branching docs still describes mobile-e2e as required: {stale!r}")

    testing_standards = read("docs/standards/testing-standards.md")
    for term in [
        "running-app flow-completion evidence",
        "The required every-PR mobile gate is the fast `mobile` job",
        "does not build native code, boot an emulator, or enforce the whole `.maestro/` suite",
    ]:
        if term not in testing_standards:
            fail(f"testing standards must document new mobile E2E policy term {term!r}")
    for stale in STALE_REQUIRED_MOBILE_E2E_TEXT:
        if stale in testing_standards:
            fail(f"testing standards still describes mobile-e2e as required: {stale!r}")

    review_policy = read("docs/review-policy.md")
    for term in ["reviewer-approved", "current PR head SHA", "other than the PR author"]:
        if term not in review_policy:
            fail(f"review policy must document reviewer status gate term {term!r}")

    mobile_workflow = read(".github/workflows/mobile.yml")
    if "\n  pull_request:" not in mobile_workflow:
        fail("mobile workflow must run the fast mobile job on pull requests")
    if "\n  mobile:\n" not in f"\n{mobile_workflow}":
        fail("mobile workflow must define the fast 'mobile' job")
    if "make mobile" not in mobile_workflow:
        fail("mobile workflow must run the fast mobile verification")
    for forbidden in [
        "PLATFORM=android ./verify-e2e.sh",
        "reactivecircus/android-emulator-runner",
        "Install Maestro",
        "Enable KVM",
    ]:
        if forbidden in mobile_workflow:
            fail(f"mobile pull-request workflow must not run native E2E: {forbidden!r}")
    if "\n  mobile-e2e:\n" in f"\n{mobile_workflow}":
        for term in [
            "does not run E2E",
            "Repository admins must remove required status check 'mobile-e2e' and require 'mobile'",
            "workflow_dispatch/schedule path",
        ]:
            if term not in mobile_workflow:
                fail(f"mobile-e2e compatibility job must log transition term {term!r}")

    e2e_workflow = read(".github/workflows/mobile-e2e.yml")
    for term in ["workflow_dispatch:", "schedule:", "PLATFORM=android ./verify-e2e.sh", "actions/upload-artifact@v4"]:
        if term not in e2e_workflow:
            fail(f"mobile-e2e workflow must retain full-suite evidence term {term!r}")
    if "pull_request" in e2e_workflow:
        fail("full mobile-e2e workflow must not run as a pull_request gate")

    protection = json.loads(read("docs/operations/main-branch-protection.json"))
    checks = protection.get("required_status_checks", {}).get("contexts", [])
    if checks != REQUIRED_STATUS_CHECKS:
        fail(
            "branch protection template must require exactly "
            + ", ".join(REQUIRED_STATUS_CHECKS)
        )
    required_reviews = protection.get("required_pull_request_reviews")
    if not isinstance(required_reviews, dict):
        fail("branch protection template must configure pull request reviews")
    if required_reviews.get("required_approving_review_count") != 0:
        fail("branch protection template must not require native approving reviews for app-reviewer flow")
    if required_reviews.get("dismiss_stale_reviews"):
        fail("branch protection template must not depend on native stale-review dismissal")
    if required_reviews.get("require_last_push_approval"):
        fail("branch protection template must not require native latest-push approval")
    if not protection.get("required_conversation_resolution"):
        fail("branch protection template must require conversation resolution")

    code_shape = ROOT / "scripts" / "verify-code-shape.py"
    for args in ([], ["--self-test"]):
        result = subprocess.run([sys.executable, str(code_shape), *args], cwd=ROOT)
        if result.returncode != 0:
            raise SystemExit(result.returncode)

    print("governance checks passed")


if __name__ == "__main__":
    main()
