.DEFAULT_GOAL := check
# The Compose command of the engine that CONTAINER_ENGINE selects (.env or the
# environment). An invalid selection prints its error and runs `false`.
COMPOSE = $(shell python3 scripts/deployment.py compose-command || echo false)
.PHONY: init check build up down test
init:
	python3 scripts/init-config.py
check:
	python3 -m unittest discover -s tests -p 'test_*.py'
	python3 scripts/stack.py config
	$(COMPOSE) -f compose.yaml -f compose.funnel.yaml config --quiet
	$(COMPOSE) -f compose.yaml -f compose.podman.yaml config --quiet
	$(COMPOSE) -f compose.yaml -f compose.funnel.yaml -f compose.podman.yaml -f compose.podman.funnel.yaml config --quiet
	python3 -m compileall -q components scripts tests
build:
	python3 scripts/stack.py build
up: init
	python3 scripts/stack.py up

down:
	python3 scripts/stack.py down

test: check
	$(COMPOSE) -f compose.yaml build hermes executor
	python3 scripts/preflight.py private-hermes-test
	python3 -u tests/smoke.py

.PHONY: computer-use-test
computer-use-test: check
	COMPUTER_USE_ENABLED=true $(COMPOSE) -f compose.yaml build hermes executor
	COMPUTER_USE_ENABLED=true python3 scripts/preflight.py private-hermes-test
	COMPUTER_USE_ENABLED=true python3 -u tests/computer_use_smoke.py

.PHONY: browser-use-test
browser-use-test: check
	COMPUTER_USE_ENABLED=true $(COMPOSE) -f compose.yaml build hermes executor
	COMPUTER_USE_ENABLED=true python3 scripts/preflight.py private-hermes-test
	COMPUTER_USE_ENABLED=true python3 -u tests/browser_use_smoke.py

.PHONY: storage-test
storage-test: check
	python3 -u tests/storage_smoke.py

.PHONY: x402_treazury-init x402_treazury-status x402_treazury-prepare x402_treazury-config x402_treazury-config-diff
x402_treazury-config-diff:
	python3 scripts/x402_treazury.py config-diff
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
	$(COMPOSE) -f compose.yaml build x402_treazury
	python3 scripts/preflight.py private-hermes-x402-treazury-test
	python3 -u tests/x402_treazury_smoke.py

.PHONY: webapp-credentials webapp-rotate webapp-test webapp-live-test
webapp-credentials:
	python3 scripts/webapp-credentials.py
webapp-rotate:
	python3 scripts/webapp-credentials.py --rotate
webapp-test: check
	$(COMPOSE) -f compose.yaml build hermes executor webapp-proxy
	python3 scripts/preflight.py private-hermes-webapp-test --funnel
	python3 -u tests/webapp_smoke.py

# Explicit public-network Tor image/outage/recovery qualification.
webapp-live-test: check
	$(COMPOSE) -f compose.yaml build hermes executor webapp-proxy
	python3 scripts/preflight.py private-hermes-webapp-test --funnel
	python3 -u tests/webapp_smoke.py --live-egress

.PHONY: chat gateway
.PHONY: onion-address
onion-address:
	python3 scripts/onion_address.py

.PHONY: onion-test
onion-test: check
	$(COMPOSE) -f compose.yaml build tor hermes executor webapp-proxy
	python3 scripts/preflight.py private-hermes-onion-test --funnel
	python3 -u tests/onion_smoke.py

# Explicitly publishes a disposable authenticated onion service for qualification.
.PHONY: onion-live-test
onion-live-test: check
	$(COMPOSE) -f compose.yaml build tor hermes executor webapp-proxy
	python3 scripts/preflight.py private-hermes-onion-test --funnel
	python3 -u tests/onion_smoke.py --live

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
	$(COMPOSE) -f compose.yaml build hermes
	python3 -u tests/images_smoke.py

.PHONY: hermes-ui-test
hermes-ui-test: check
	python3 -u tests/hermes_ui.py

# Forbidden-path test of a running stack on Podman (make up first).
.PHONY: podman-paths-test
podman-paths-test:
	bash tests/podman_paths_smoke.sh
