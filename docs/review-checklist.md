# Review Checklist

Use this as the separate reviewer phase before merge.

## Review Stance

Prioritize bugs, regressions, security/privacy risks, missing tests, contract
drift, and maintainability problems. Style comments are secondary unless they
affect consistency or readability.

## Required Checks

- The PR matches the linked story, contract, or ADR.
- The change is scoped and does not include unrelated churn.
- Tests cover meaningful behavior and edge cases.
- CI and `make verify` pass or failures are explained and acceptable.
- API, data, job, and estimator contracts are updated when boundaries changed.
- Security and privacy impact sections are accurate.
- No secrets, real user data, or unnecessary personal data are introduced.
- LLM/tool changes validate untrusted input and output.
- Migrations are reversible or have a documented rollback plan.
- Logging avoids sensitive values.
- Mobile UI remains accessible and iOS-first.

## Approval Rule

Do not approve until blocking issues are resolved. Approval means the reviewer
believes the change is safe to merge under current project standards.
