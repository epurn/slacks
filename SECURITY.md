# Security Policy

Fatty handles personal food, body, goal, and profile data. Security and privacy issues should be treated as product bugs.

## Reporting

This repository is private while the project is early. For now, report security issues directly to the repository owner. A public security contact and disclosure process will be added before public launch.

## Baseline

- Minimize collection and retention of personal data.
- Encrypt sensitive data in transit and at rest where feasible.
- Keep secrets out of source control and logs.
- Use least privilege for app services, CI, agents, and external providers.
- Validate all LLM, OCR, web, and user-provided content before persistence or action.
- Require review for security-sensitive changes.

See `docs/security/security-baseline.md` and `docs/security/threat-model.md`.

