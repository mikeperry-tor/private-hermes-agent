.DEFAULT_GOAL := check
.PHONY: init check build up down test
init:
	python3 scripts/init-config.py
check:
	python3 -m unittest discover -s tests -p 'test_*.py'
	python3 scripts/stack.py config
	docker compose -f compose.yaml -f compose.funnel.yaml config --quiet
	docker compose -f compose.yaml -f compose.podman.yaml config --quiet
	docker compose -f compose.yaml -f compose.funnel.yaml -f compose.podman.yaml -f compose.podman.funnel.yaml config --quiet
	python3 -m compileall -q components scripts tests
build:
	python3 scripts/stack.py build
up: init
	python3 scripts/stack.py up

down:
	python3 scripts/stack.py down

test: check
	docker compose -f compose.yaml build hermes executor
	python3 scripts/preflight.py private-hermes-test
	python3 -u tests/smoke.py

.PHONY: computer-use-test
computer-use-test: check
	COMPUTER_USE_ENABLED=true docker compose -f compose.yaml build hermes executor
	python3 scripts/preflight.py private-hermes-test
	COMPUTER_USE_ENABLED=true python3 -u tests/computer_use_smoke.py

.PHONY: browser-use-test
browser-use-test: check
	COMPUTER_USE_ENABLED=true docker compose -f compose.yaml build hermes executor
	python3 scripts/preflight.py private-hermes-test
	COMPUTER_USE_ENABLED=true python3 -u tests/browser_use_smoke.py

.PHONY: storage-test
storage-test: check
	python3 -u tests/storage_smoke.py

.PHONY: x402_treazury-init x402_treazury-status x402_treazury-prepare x402_treazury-config
x402_treazury-config:
	python3 scripts/x402_treazury.py config
x402_treazury-init:
	python3 scripts/x402_treazury.py init
x402_treazury-status:
	python3 scripts/x402_treazury.py status
x402_treazury-prepare:
	python3 scripts/x402_treazury.py prepare

.PHONY: x402_treazury-test
x402_treazury-test: check
	python3 scripts/preflight.py private-hermes-x402-treazury-test
	python3 -u tests/x402_treazury_smoke.py

.PHONY: webapp-credentials webapp-rotate webapp-test
webapp-credentials:
	python3 scripts/webapp-credentials.py
webapp-rotate:
	python3 scripts/webapp-credentials.py --rotate
webapp-test: check
	docker compose -f compose.yaml build hermes executor webapp-proxy
	python3 scripts/preflight.py private-hermes-webapp-test --funnel
	python3 -u tests/webapp_smoke.py

.PHONY: chat gateway
chat:
	python3 scripts/stack.py compose run --rm --no-deps hermes chat
gateway: up

.PHONY: check-updates plugins
check-updates:
	python3 scripts/check-updates.py
plugins:
	python3 scripts/plugins.py

.PHONY: plugins-test
plugins-test: check
	python3 scripts/preflight.py private-hermes-plugins-test
	python3 -u tests/plugins_smoke.py

.PHONY: images-test
images-test: check
	docker compose -f compose.yaml build hermes
	python3 -u tests/images_smoke.py

.PHONY: hermes-ui-test
hermes-ui-test: check
	python3 -u tests/hermes_ui.py
