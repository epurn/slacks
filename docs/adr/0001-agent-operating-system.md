# ADR 0001: Agent Operating System

## Status

Accepted.

## Context

Fatty is intended to be built with heavy autonomous coding-agent assistance. The project also handles sensitive personal data and needs strong consistency, testing, security, privacy, and review discipline from the first commit.

Research and current practice suggest repository agent guidance is useful when it is concise and specific, but can become harmful when it bloats context, leaks irrelevant lint rules, or creates conflicting instructions.

## Decision

Use a lean root `AGENTS.md` plus focused playbooks and skill files under `agents/`.

The operating system includes:

- root agent guidance,
- product and development goals,
- focused playbooks,
- durable memory entry points,
- domain skills,
- deterministic story-steward routing,
- PR/review policy,
- governance CI,
- separate reviewer gate,
- story and PR templates,
- CODEOWNERS.

Agents should operate autonomously within a task, but implementation and review remain separate phases. Story stewardship is a coordination role invoked by deterministic events; it is not an always-on LLM requirement.

## Consequences

- Future agents get a predictable entry point.
- Detailed instructions stay available without loading every policy for every task.
- CI can verify the governance scaffold remains present.
- Empty automation checks can exit cheaply without waking a model.
- Branch protection and reviewer gate must be configured in GitHub before merges are allowed.
