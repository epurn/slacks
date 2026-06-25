.PHONY: verify governance steward steward-watch steward-poll steward-poll-dry-run reviewer reviewer-watch reviewer-watch-auto-merge reviewer-poll reviewer-poll-auto-merge agents-run agents-stop

FATTY_STEWARD_AGENT_ROOT ?= ../fatty-steward-agent
FATTY_REVIEWER_AGENT_ROOT ?= ../fatty-reviewer-agent

verify: governance

governance:
	python3 scripts/verify-governance.py

steward: steward-watch

steward-watch:
	$(MAKE) -C "$(FATTY_STEWARD_AGENT_ROOT)" watch

steward-poll:
	@echo "one-shot steward poll for debugging; use 'make steward' for the always-running code poller"
	$(MAKE) -C "$(FATTY_STEWARD_AGENT_ROOT)" poll

steward-poll-dry-run:
	@echo "one-shot steward dry run for debugging; use 'make steward' for the always-running code poller"
	$(MAKE) -C "$(FATTY_STEWARD_AGENT_ROOT)" once-dry-run

reviewer: reviewer-watch

reviewer-watch:
	$(MAKE) -C "$(FATTY_REVIEWER_AGENT_ROOT)" watch-auto-merge

reviewer-watch-auto-merge:
	$(MAKE) -C "$(FATTY_REVIEWER_AGENT_ROOT)" watch-auto-merge

reviewer-poll:
	@echo "one-shot reviewer poll for debugging; use 'make reviewer' for the always-running code poller"
	$(MAKE) -C "$(FATTY_REVIEWER_AGENT_ROOT)" poll

reviewer-poll-auto-merge:
	@echo "one-shot reviewer poll for debugging; use 'make reviewer' for the always-running code poller"
	$(MAKE) -C "$(FATTY_REVIEWER_AGENT_ROOT)" poll-auto-merge

agents-run:
	$(MAKE) -C "$(FATTY_STEWARD_AGENT_ROOT)" run-all-agents

agents-stop:
	$(MAKE) -C "$(FATTY_STEWARD_AGENT_ROOT)" stop-all-agents
