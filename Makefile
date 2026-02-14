.PHONY: run-action clean-restart nuke-rebuild test

run-action:
	./scripts/run_action_verify.sh

clean-restart:
	./scripts/clean_and_restart.sh

nuke-rebuild:
	./scripts/nuke_and_rebuild.sh

test:
	pytest -q
