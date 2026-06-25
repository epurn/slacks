.PHONY: verify governance

verify: governance

governance:
	python3 scripts/verify-governance.py
