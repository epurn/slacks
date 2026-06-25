---
name: triage-prs
description: Triage open Fatty pull requests — check review decisions, required checks, and requested changes, and recommend what the steward or reviewer should do next. Use when the user asks to "triage PRs", "what's blocking merges", or "which PRs need attention". Read-only analysis; routes through the agents rather than merging directly.
---

# Triage PRs

Summarize what every open PR is waiting on and recommend the next move. This is
analysis only — never merge, approve, or push. Routing happens through the
steward and reviewer services.

## Gather

```sh
gh pr list --repo epurn/fatty --state open \
  --json number,title,author,headRefName,isDraft,reviewDecision,statusCheckRollup,mergeable

# For a specific PR's checks and review history:
gh pr view <n> --repo epurn/fatty --json statusCheckRollup,reviews,reviewDecision
```

## Classify each PR

- **Waiting on review** — `governance` passing, no current-head reviewer-approved
  status yet → the reviewer poller should pick it up.
- **Needs a fix** — failing non-reviewer check, or reviewer requested changes on
  the current head → the steward should launch a bounded `fix-pr` author
  assignment.
- **Ready to merge** — `governance` + `reviewer-approved` both green on the
  current head → auto-merge should complete; if not, flag it.
- **Draft / stale** — draft, or no commits since a prior review.

## Output

A short per-PR list: number, title, state classification, the single blocking
thing, and the recommended actor (steward fix, reviewer, or human). If the user
asks you to act, prefer the `agents-control` / `agents-status` skills and let the
steward/reviewer do the routing — do not merge or approve manually.
