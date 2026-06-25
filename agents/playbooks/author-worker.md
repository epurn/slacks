# Author Worker Playbook

Use this when implementing or fixing one assigned Fatty story or PR.

## Contract

The author worker receives exactly one assignment from the story steward. It
does not select unrelated work.

An assignment must include:

- story ID or PR number,
- branch name,
- worktree path,
- target repo,
- lanes,
- required context,
- verification commands,
- approved dependencies.

## Startup

1. Confirm the current directory is the assigned worktree.
2. Read `AGENTS.md`, `agents/state/author-loop.md`, and the assigned story.
3. Read only required playbooks, contracts, and memory files.
4. Confirm the branch name matches the assignment.
5. Refuse to continue if the assignment requires `.env` or secret file access.

## Implementation Rules

- Keep changes inside the assignment scope.
- Use only dependencies already present or approved in story metadata.
- Update contracts, tests, docs, and migrations with the behavior they describe.
- Prefer local, reversible, testable fixes for blockers.
- Block only the affected assignment when real risk remains.
- Never review, approve, merge, or bypass branch protection.

## Output

The author runner should produce structured output with:

- summary,
- files changed,
- verification run,
- PR title/body or update note,
- blockers,
- memory updates suggested only when they save future work.

