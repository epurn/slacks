# Story Slicing Playbook

Use this when choosing or shaping implementation work.

## Goal

Move Fatty toward v1 through thin, reviewable vertical slices. A slice should produce one observable behavior, one clear contract change, or one platform capability that unblocks the next slice.

## Slice Rules

- One story should fit in a single PR that a reviewer can inspect in one sitting.
- Prefer end-to-end skeletons over isolated framework setup when possible.
- Every story needs acceptance criteria and a verification plan.
- Stories that touch auth, personal data, LLMs, web fetches, files, or external providers need a security/privacy note.
- Do not bundle unrelated cleanup, dependency upgrades, and feature behavior.
- If a story grows, split it before coding instead of creating a large PR.

## Story States

- `candidate`: useful but not ready.
- `ready`: scoped, accepted, and implementable without user input.
- `in_progress`: branch exists and work is underway.
- `in_review`: PR is open.
- `changes_requested`: reviewer or CI blocked it.
- `merged`: complete.

## Author-Agent Loop

1. Pick the highest-priority `ready` story from `docs/stories/v1-roadmap.md`.
2. Create a branch named `story/<id>-<slug>`.
3. Read only the relevant playbooks, skills, contracts, and nearby code.
4. Implement the smallest complete slice.
5. Update tests, contracts, docs, and migrations in the same PR.
6. Run `make verify` and package-specific checks.
7. Open a PR with the project template.
8. Wait for CI and the separate reviewer.
9. If review requests changes, fix them on the same branch and push.
10. When approved and green, use GitHub native auto-merge when allowed.

## Rejection Handling

When a PR is rejected:

- Read the reviewer comment before editing.
- Classify each item as blocking, non-blocking, or question.
- Implement blocking fixes first.
- Add or update tests that would have caught the issue.
- Reply in the PR with what changed.
- Do not argue with the reviewer by default; improve the code or clarify with evidence.

