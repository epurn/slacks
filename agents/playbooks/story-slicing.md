# Story Slicing Playbook

Use this when choosing or shaping implementation work.

## Goal

Move Fatty toward v1 through thin, reviewable vertical slices. A slice should produce one observable behavior, one clear contract change, or one platform capability that unblocks the next slice.

## Slice Rules

- One story should fit in a single PR that a reviewer can inspect in one sitting.
- Prefer end-to-end skeletons over isolated framework setup when possible.
- Every story needs acceptance criteria and a verification plan.
- Every ready or ready-with-notes story needs YAML metadata and a readiness sanity pass.
- Every story needs explicit dependencies; implement only when dependencies are merged.
- Every story that adds packages needs planning-approved dependencies listed in story metadata.
- Stories that touch auth, personal data, LLMs, web fetches, files, or external providers need a security/privacy note.
- Do not bundle unrelated cleanup, dependency upgrades, and feature behavior.
- If a story grows, split it before coding instead of creating a large PR.

## Story States

- `candidate`: useful but not ready.
- `ready`: scoped, accepted, and implementable without user input.
- `ready_with_notes`: implementable with documented assumptions or non-blocking planning notes.
- `in_progress`: branch exists and work is underway.
- `in_review`: PR is open.
- `changes_requested`: reviewer or CI blocked it.
- `merged`: complete.

## Ready Story Metadata

`ready` and `ready_with_notes` story files must include the metadata header and
readiness sanity pass described in `agents/playbooks/story-steward.md`.

Implementation agents may install only dependencies listed in
`approved_dependencies` or dependencies already present in the repo. If a new
package is essential but unapproved, block that story and continue elsewhere.

## Author-Agent Loop

1. Pick the highest-priority `ready` or `ready_with_notes` story from `docs/stories/v1-roadmap.md`.
2. Create a branch named `story/<id>-<slug>`.
3. Read only the relevant playbooks, skills, contracts, and nearby code.
4. Implement the smallest complete slice.
5. Update tests, contracts, docs, and migrations in the same PR.
6. Run `make verify` and package-specific checks.
7. Open a PR with the project template.
8. Wait for CI and the separate reviewer.
9. If review requests changes, fix them on the same branch and push.
10. When approved and green, use GitHub native auto-merge when allowed.

If another PR is only waiting for review, continue with the next non-conflicting ready or ready-with-notes story from `origin/main`. Do not stack feature branches on top of unmerged feature branches.

## Parallel Slice Selection

Before picking a story:

- Check open PRs and changed files.
- Map each PR to a work lane.
- Skip candidate stories in lanes already touched by open PRs.
- Prefer stories that create stable contracts or independent package skeletons.

Recommended lane order for early v1 parallelism:

1. `governance`: author loop, roadmap, review policy.
2. `contracts`: shared API/job/domain contracts.
3. `backend-core`: FastAPI app skeleton.
4. `mobile-core`: Expo app skeleton.
5. `infra`: Docker Compose and service wiring.
6. `estimator`: provider config and calculators.
7. `security-privacy`: hardening and adversarial tests.

When many ready stories exist, choose work by:

1. rejected or failing PRs first,
2. stories that unblock the most downstream work,
3. lanes with no open PRs,
4. lower risk when value is similar,
5. roadmap order.

## Rejection Handling

When a PR is rejected:

- Read the reviewer comment before editing.
- Classify each item as blocking, non-blocking, or question.
- Implement blocking fixes first.
- Add or update tests that would have caught the issue.
- Reply in the PR with what changed.
- Do not argue with the reviewer by default; improve the code or clarify with evidence.
