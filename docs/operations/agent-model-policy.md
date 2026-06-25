# Agent Model Policy

Fatty uses dynamic model and reasoning selection to preserve quality while
avoiding unnecessary token spend.

## Defaults

- Triage, routing, and no-op poll checks: no model call.
- Low-risk docs or story metadata: smaller model, medium reasoning.
- Normal implementation or review: strong everyday coding model, high
  reasoning.
- Security, privacy, auth, estimator, contracts, migrations, CI gates, branch
  protection, or broad cross-lane changes: strongest available model, xhigh
  reasoning.

When classification is uncertain, estimate big: choose the higher risk bucket
rather than trying to save tokens on work that could affect code quality,
security, privacy, or merge safety.

## Role Guidance

- Planner: use enough reasoning to produce ready stories; no implementation.
- Steward poller: deterministic routing first; model only for ambiguous story
  splitting, promotion, demotion, or blocker triage.
- Author: choose model based on story risk, touched lanes, and assignment size.
- Reviewer: choose model based on PR risk, changed files, and security/privacy
  impact.

## Quality Floor

Token savings must not weaken product safety. Escalate model or reasoning when
the task affects user data, auth, retention, estimator validation, public API
contracts, database migrations, or branch protection.
