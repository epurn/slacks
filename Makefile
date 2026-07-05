.PHONY: verify governance packages backend mobile contracts sim-smoke

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

# Local v1 simulator-readiness smoke (FTY-250). Run BEFORE testing Fatty in an
# iOS simulator: it verifies the running Compose stack is coherent (backend
# images from one checkout, Alembic at head, API/worker/source health green) and
# prints the exact simulator connect URL derived from `.env` `API_PORT`. It is
# read-only, prints no secrets, and is NOT part of `make verify`. Requires the
# stack to be up (`docker compose up -d`) and the backend uv env installed.
sim-smoke:
	cd backend && uv run python -m app.ops.sim_readiness
