.PHONY: verify governance packages backend mobile contracts

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
