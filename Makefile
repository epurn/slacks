.PHONY: verify governance packages backend mobile contracts sim-smoke food-smoke tailscale-serve

# Root verification entry point. Runs repository governance plus any package
# checks that have opted in. `make verify` stays the single contract for CI and
# local checks as backend, mobile, and contract toolchains are added.
verify: governance packages

governance:
	python3 scripts/verify-governance.py

# Delegate to each package's verify hook. Packages without a hook are skipped
# cleanly, so the scaffold verifies from a fresh checkout.
packages: backend mobile contracts

backend:
	@scripts/package-verify.sh backend

mobile:
	@scripts/package-verify.sh mobile

contracts:
	@scripts/package-verify.sh contracts

# Local v1 simulator-readiness smoke (FTY-250). Run BEFORE testing Slacks in an
# iOS simulator: it verifies the running Compose stack is coherent (backend
# images from one checkout, Alembic at head, API/worker/source health green) and
# prints the exact simulator connect URL derived from `.env` `API_PORT`. It is
# read-only, prints no secrets, and is NOT part of `make verify`. Requires the
# stack to be up (`docker compose up -d`) and the backend uv env installed.
sim-smoke:
	cd backend && uv run python -m app.ops.sim_readiness

# Local v1 food dogfood smoke (FTY-256). Run AFTER the simulator-readiness smoke,
# against a healthy local stack with a REAL LLM provider configured (claude_code
# / codex / openai_compatible — the default `fake` provider cannot parse
# natural-language food). It logs in to a reused throwaway account (registering
# it only on the first run so it never trips the register rate limiter), submits
# a small set of representative food logs to the LIVE local API, waits for
# estimation, and
# prints a sanitized pass/fail summary (source/provenance + calories). It catches
# v1 dogfood regressions before a human opens the simulator. It prints no secrets
# and is NOT part of `make verify` (never a CI gate that depends on live external
# providers). This is live-local API smoke, not the hermetic E2E fixture mode.
food-smoke:
	cd backend && uv run python -m app.ops.food_dogfood_smoke

# Tailnet HTTPS ingress helper (FTY-367). Starts/re-applies `tailscale serve`
# so the local API is reachable at https://<host>.<tailnet-name>.ts.net —
# TLS on 443 with a valid tailnet cert, tailnet-only (serve, never funnel).
# Requires Tailscale installed + logged in with MagicDNS and HTTPS certificates
# enabled; see docs/operations/tailscale-https.md. Prints URLs/status only, no
# secrets, and is NOT part of `make verify`.
tailscale-serve:
	@scripts/tailscale-serve.sh
