.PHONY: verify governance steward-router

verify: governance

governance:
	python3 scripts/verify-governance.py

steward-router:
	python3 scripts/steward-router.py --json
