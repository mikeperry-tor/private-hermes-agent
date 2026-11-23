.DEFAULT_GOAL := help
# The Compose command of the engine that CONTAINER_ENGINE selects (.env or the
# environment). An invalid selection prints its error and runs `false`.
COMPOSE = $(shell python3 scripts/deployment.py compose-command || echo false)

.PHONY: help \
	init build up down chat gateway \
	webapp-credentials webapp-rotate onion-address \
	x402_treazury-init x402_treazury-prepare x402_treazury-status x402_treazury-config x402_treazury-config-diff \
	check-updates plugins \
	check test webapp-test webapp-live-test onion-test onion-live-test \
	computer-use-test browser-use-test storage-test x402_treazury-test \
	plugins-test images-test hermes-ui-test podman-paths-test

# User-facing command index plus primary baseline checks. Keep component-scoped,
# specialized, and live-network test targets in docs/development.md instead.
help:
	@echo "Stack lifecycle:"
	@echo "  make init                       # Create missing .env, webapp credentials, and local config"
	@echo "  make build                      # Build container images without initializing or starting the stack"
	@echo "  make up                         # Initialize missing config, build enabled images, and start the stack"
	@echo "  make down                       # Stop and remove stack containers while preserving persistent data"
	@echo "  make chat                       # Open the Hermes terminal client against the running stack"
	@echo ""
	@echo "WebApp and optional Tor onion ingress:"
	@echo "  make webapp-credentials         # Create missing webapp login credentials without rotating existing ones"
	@echo "  make webapp-rotate              # Rotate webapp password and signing key (apply with make up)"
	@echo "  make onion-address              # Create an offline onion identity or print its saved .onion URL"
	@echo ""
	@echo "Optional paid research APIs (x402_treazury):"
	@echo "  make x402_treazury-init         # Create the Zcash treasury wallet and print its shielded receive address"
	@echo "  make x402_treazury-prepare      # Fund the initial bootstrap wallet, warm catalogs, and connect MCP tools"
	@echo "  make x402_treazury-status       # Show treasury funding status and shielded receive address"
	@echo "  make x402_treazury-config-diff  # Compare saved research_desk.toml against the packaged image default"
	@echo ""
	@echo "Updates and plugins:"
	@echo "  make check-updates              # Check upstream image and source versions over Tor without changing pins"
	@echo "  make plugins                    # Inspect or manage persistent Hermes plugins inside the running container"
	@echo ""
	@echo "Development and qualification:"
	@echo "  make check                      # Run unit tests, validate Docker and Podman Compose models, and compile Python"
	@echo "  make test                       # Run the core isolated live-stack smoke suite (stop running stack first)"
	@echo "  make webapp-test                # Run WebApp auth, terminal, and content-policy smoke tests"
	@echo "  See docs/development.md for component-scoped and live-network test targets."
	@echo ""
	@echo "Configuration:"
	@echo "  Engine override: CONTAINER_ENGINE=podman make <target> (or set CONTAINER_ENGINE in .env)"
	@echo "  Settings file:   edit .env (created from .env.example by make init), then run make down && make up"
	@echo "  Key toggles:     TEEP_ENABLED, COMPUTER_USE_ENABLED, WEBAPP_EXTERNAL_CONTENT,"
	@echo "                   WEBAPP_TERMINAL_ENVIRONMENT, TOR_ONION_ENABLED, TAILSCALE_FUNNEL_ENABLED"
	@echo "  Docs:            README.md (operator guide) and docs/development.md (full test suites)"

# Stack lifecycle

init:
	python3 scripts/init-config.py

build:
	python3 scripts/stack.py build

up: init
	python3 scripts/stack.py up

down:
	python3 scripts/stack.py down

chat:
	python3 scripts/stack.py compose run --rm --no-deps hermes chat

gateway: up

# WebApp and optional Tor onion ingress

webapp-credentials:
	python3 scripts/webapp-credentials.py

webapp-rotate:
	python3 scripts/webapp-credentials.py --rotate

onion-address:
	python3 scripts/onion_address.py

# Optional paid research APIs (x402_treazury)

x402_treazury-init:
	python3 scripts/x402_treazury.py init

x402_treazury-prepare:
	python3 scripts/x402_treazury.py prepare

x402_treazury-status:
	python3 scripts/x402_treazury.py status

x402_treazury-config:
	python3 scripts/x402_treazury.py config

x402_treazury-config-diff:
	python3 scripts/x402_treazury.py config-diff

# Updates and plugins

check-updates:
	python3 scripts/check-updates.py

plugins:
	python3 scripts/plugins.py

# Development and qualification

check:
	python3 -m unittest discover -s tests -p 'test_*.py'
	python3 scripts/stack.py config
	$(COMPOSE) -f compose.yaml -f compose.funnel.yaml config --quiet
	$(COMPOSE) -f compose.yaml -f compose.podman.yaml config --quiet
	$(COMPOSE) -f compose.yaml -f compose.funnel.yaml -f compose.podman.yaml -f compose.podman.funnel.yaml config --quiet
	python3 -m compileall -q components scripts tests

test: check
	$(COMPOSE) -f compose.yaml build hermes executor
	python3 scripts/preflight.py private-hermes-test --skip-ports
	python3 -u tests/smoke.py

webapp-test: check
	$(COMPOSE) -f compose.yaml build hermes executor webapp-proxy
	python3 scripts/preflight.py private-hermes-webapp-test --funnel --skip-ports
	python3 -u tests/webapp_smoke.py

# Explicit public-network Tor image, outage, and recovery qualification.
webapp-live-test: check
	$(COMPOSE) -f compose.yaml build hermes executor webapp-proxy
	python3 scripts/preflight.py private-hermes-webapp-test --funnel --skip-ports
	python3 -u tests/webapp_smoke.py --live-egress

onion-test: check
	$(COMPOSE) -f compose.yaml build tor hermes executor webapp-proxy
	python3 scripts/preflight.py private-hermes-onion-test --funnel --skip-ports
	python3 -u tests/onion_smoke.py

# Explicitly publishes a temporary authenticated onion service for qualification.
onion-live-test: check
	$(COMPOSE) -f compose.yaml build tor hermes executor webapp-proxy
	python3 scripts/preflight.py private-hermes-onion-test --funnel --skip-ports
	python3 -u tests/onion_smoke.py --live

computer-use-test: check
	COMPUTER_USE_ENABLED=true $(COMPOSE) -f compose.yaml build hermes executor
	COMPUTER_USE_ENABLED=true python3 scripts/preflight.py private-hermes-test --skip-ports
	COMPUTER_USE_ENABLED=true python3 -u tests/computer_use_smoke.py

browser-use-test: check
	COMPUTER_USE_ENABLED=true $(COMPOSE) -f compose.yaml build hermes executor
	COMPUTER_USE_ENABLED=true python3 scripts/preflight.py private-hermes-test --skip-ports
	COMPUTER_USE_ENABLED=true python3 -u tests/browser_use_smoke.py

storage-test: check
	python3 -u tests/storage_smoke.py

x402_treazury-test: check
	$(COMPOSE) -f compose.yaml build x402_treazury
	python3 scripts/preflight.py private-hermes-x402-treazury-test --skip-ports
	python3 -u tests/x402_treazury_smoke.py

plugins-test: check
	python3 scripts/preflight.py private-hermes-plugins-test --skip-ports
	python3 -u tests/plugins_smoke.py

images-test: check
	$(COMPOSE) -f compose.yaml build hermes
	python3 -u tests/images_smoke.py

hermes-ui-test: check
	python3 -u tests/hermes_ui.py

# Forbidden-path test of a running stack on Podman (make up first).
podman-paths-test:
	bash tests/podman_paths_smoke.sh
