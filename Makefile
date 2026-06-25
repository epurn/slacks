PACKAGE_DIRS := apps/backend apps/mobile packages/contracts

.PHONY: verify governance scaffold packages

verify: governance scaffold packages

governance:
	python3 scripts/verify-governance.py

scaffold:
	python3 scripts/verify-monorepo-scaffold.py

packages:
	@set -eu; \
	for package in $(PACKAGE_DIRS); do \
		if [ -f "$$package/Makefile" ]; then \
			$(MAKE) -C "$$package" verify; \
		else \
			printf '%s\n' "package $$package has no Makefile; skipping package-specific verify"; \
		fi; \
	done
