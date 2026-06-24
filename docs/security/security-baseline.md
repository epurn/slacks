# Security Baseline

Fatty handles sensitive personal data. The baseline is privacy by design, least privilege, and explicit trust boundaries.

## Standards

This project uses the following as design references:

- NIST Secure Software Development Framework SP 800-218.
- OWASP Application Security Verification Standard.
- OWASP Software Assurance Maturity Model.
- OWASP AI Agent Security Cheat Sheet.
- OWASP LLM Prompt Injection guidance.
- NIST Privacy Framework.
- OpenSSF Scorecard and SLSA for supply-chain direction.

## Data Minimization

- Collect only data needed for logging, estimation, targets, exercise burn, correction learning, and account operation.
- Do not store raw fetched pages, raw OCR, raw prompts, or attachments longer than needed unless there is a product reason.
- Store source facts separately from user-specific habits.
- Keep personal memories inspectable, editable, and deletable.

## Encryption and Secrets

- Require TLS in hosted and production-like deployments.
- Use database and object-storage encryption where supported by the deployment.
- Consider application-level encryption for highly sensitive fields once the data model is finalized.
- Store provider keys and app secrets in environment variables or secret managers.
- Never expose LLM/search/nutrition provider keys to clients.
- Never commit `.env`, tokens, private keys, or production credentials.

## Authentication and Authorization

- Keep authentication identities separate from users.
- Prefer Sign in with Apple for iOS hosted auth when available.
- Self-hosted auth must support a secure local path.
- Enforce object-level authorization on every user-owned record.
- Add negative authorization tests for new data access paths.

## LLM and Agent Safety

- Treat the LLM as an untrusted analyst.
- Use structured outputs and schema validation.
- Keep tools allowlisted and parameter-validated.
- Sanitize search queries so personal context is not sent to search providers.
- Use a hardened fetcher with SSRF protections.
- Do not allow open-ended code execution, shell, filesystem, email, calendar, or broad personal tools in the estimator.
- Memory writes require validation and user isolation.

## Logging and Telemetry

- Logs must not contain secrets, auth tokens, raw sensitive prompts, full food histories, or unnecessary body data.
- Use request IDs and event IDs instead of personal values where possible.
- Redact sensitive fields in errors and provider traces.
- Telemetry must be opt-in or clearly documented before public launch.

## Supply Chain

- Use pinned or locked dependencies.
- Enable dependency update automation.
- Use GitHub branch protection and required checks.
- Add SBOM/provenance work before public releases.

