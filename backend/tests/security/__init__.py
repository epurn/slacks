"""The FTY-073 cross-cutting adversarial security suite.

A consolidated, test-only suite that proves the untrusted-input trust boundary of
the as-built v1 surface holds: prompt-injection resistance (user text and every
untrusted evidence channel), SSRF / egress hardening, query sanitization / data
minimization, secret non-disclosure, and fail-closed object-level authorization.

It *extends* the per-feature negative suites (FTY-044/061/062 and the per-resource
``test_*_api.py`` authz tests) rather than duplicating them, filling the gaps a
cross-cutting pass surfaces. Every test uses fake/stubbed providers and a stubbed
fetcher: nothing here performs live network egress.
"""
