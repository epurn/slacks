# Branching and PRs

## Branches

Use:

- `story/<id>-<slug>`
- `fix/<id>-<slug>`
- `security/<id>-<slug>`
- `chore/<slug>`

Do not work directly on `main`.
Base feature branches on current `origin/main`.

## Coordination Flow

Fatty uses separate planner, steward, author, and reviewer phases.

1. The planner promotes stories only when they meet the story readiness rule.
2. The steward picks up ready stories and assigns implementation work when
   dependencies are complete and lanes are unoccupied.
3. Authors work on branches from current `origin/main`.
4. The author opens a PR with verification, security, privacy, and story
   context.
5. The steward routes the PR to a separate reviewer.
6. New commits after review require fresh current-head review before merge.
7. Private automation state and runner details remain outside the public repo.

Run the always-on code pollers from the CLI:

```sh
make steward
make reviewer
make agents-run
make agents-stop
```

Run one cheap poll cycle for debugging:

```sh
make steward-poll
make reviewer-poll
```

These targets call the local steward and reviewer agent repositories. The
pollers are ordinary code and should sleep or exit cheaply when nothing is
actionable. The poll step itself is not an LLM call. It may launch separate
bounded Codex tasks only after deterministic checks find actionable work.

See `docs/operations/agent-polling.md` and
`docs/operations/agent-model-policy.md`.

## Pull Requests

Every PR must include:

- story, contract, or ADR reference,
- summary of changes,
- tests and verification,
- security impact,
- privacy impact,
- reviewer phase checklist.

## Main Branch Protection

Configure GitHub `main` with:

- require pull request before merge,
- require at least one native approving review,
- dismiss stale approvals,
- require review on the latest push,
- require conversation resolution,
- require status checks:
  - `governance`,
  - `separate-reviewer`,
  - future backend/mobile/security checks,
- block force pushes,
- block deletions,
- apply rules to administrators where practical.

The `separate-reviewer` status check is the automated non-author review gate.
It must evaluate approval on the current PR head SHA. Native review protection
is still required so workflow and governance changes cannot weaken their own
merge gate.

## Merge Style

Use squash merge for a clean linear history unless a release branch needs a different strategy.

## Bootstrap

For the initial empty repository, push the governance scaffold to `main`, then enable branch protection immediately. After protection is enabled, all further work should use PRs.
