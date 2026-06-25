# Agent Model Policy

Fatty uses dynamic Claude model selection to preserve quality while avoiding
unnecessary token spend. Model choice is a launch-time cost-control decision.
Thinking depth is **not** forced — Claude scales its own reasoning to the task,
so there is no separate reasoning-effort setting (Claude Code has no such flag).

## Tiers

Risk maps to a model. `haiku` is reserved for the genuinely low-risk bucket.

- Triage, routing, and no-op poll checks: no model call.
- Low-risk docs or story metadata: `haiku` (`FATTY_*_CLAUDE_MODEL_LOW`).
- Normal implementation or review: `sonnet` (`FATTY_*_CLAUDE_MODEL_MEDIUM`).
- Security, privacy, auth, estimator, contracts, migrations, CI gates, branch
  protection, or broad cross-lane changes: `opus`
  (`FATTY_*_CLAUDE_MODEL_HIGH`).

When classification is uncertain, estimate big: choose the higher risk bucket
rather than trying to save tokens on work that could affect code quality,
security, privacy, or merge safety.

## Role Guidance

- **Planner**: enough capability to produce ready stories; no implementation.
- **Steward poller**: deterministic routing first; a model only for ambiguous
  story splitting, promotion, demotion, or blocker triage.
- **Author**: model chosen from story risk, touched lanes, and assignment size.
- **Reviewer**: model chosen from PR risk, changed files, and security/privacy
  impact.

## Quality Floor

Token savings must not weaken product safety. Escalate the model when the task
affects user data, auth, retention, estimator validation, public API contracts,
database migrations, or branch protection.

## Overrides

Set `FATTY_<AGENT>_CLAUDE_MODEL` in an agent's `.env` to pin a single model and
bypass the dynamic policy for a run. Per-tier defaults are overridable via
`FATTY_<AGENT>_CLAUDE_MODEL_LOW|MEDIUM|HIGH`.
