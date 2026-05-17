# IxNetwork Session Explorer — build helpers
# ─────────────────────────────────────────────────────────────────────────────
# Problem context
# ───────────────
# Docker build containers sometimes cannot reach the internet (VPN, corporate
# proxy, Docker Desktop DNS quirks on macOS).  The `vendor` target downloads
# all Python wheels onto your host machine (where the internet works) into
# backend/vendor/.  The Dockerfile then installs from that local cache and
# never opens a network connection at build time.
#
# Quick start (no internet in Docker):
#   make vendor   ← run once; re-run when requirements.txt changes
#   make build
#   make up
#
# Quick start (Docker has internet access):
#   make build
#   make up

PYTHON      ?= python3
PIP         ?= $(PYTHON) -m pip
VENDOR_DIR  := backend/vendor
REQUIREMENTS := backend/requirements.txt

.PHONY: vendor build up down logs clean help

# ── vendor ────────────────────────────────────────────────────────────────────
# Download all wheels for linux/x86_64 + Python 3.11 into backend/vendor/.
# Using --platform / --python-version / --abi ensures the wheels work inside
# the python:3.11-slim Docker image even if your host is macOS arm64.
vendor:
	@echo "==> Downloading wheels into $(VENDOR_DIR)/ ..."
	$(PIP) download \
		--dest $(VENDOR_DIR) \
		--platform manylinux2014_x86_64 \
		--python-version 3.11 \
		--implementation cp \
		--abi cp311 \
		--only-binary=:all: \
		-r $(REQUIREMENTS)
	@echo "==> Done. $(VENDOR_DIR)/ now contains $$(ls $(VENDOR_DIR)/*.whl 2>/dev/null | wc -l | tr -d ' ') wheel(s)."
	@echo "    Run 'make build' to build the Docker image offline."

# ── build ─────────────────────────────────────────────────────────────────────
# Ensure backend/vendor/ exists before handing the build context to Docker.
# Docker's COPY instruction hard-fails if the source path is absent entirely
# (even when the Dockerfile logic would never use it).  mkdir -p is a no-op
# when the directory already exists.
build:
	@mkdir -p $(VENDOR_DIR)
	docker compose build

# ── up ────────────────────────────────────────────────────────────────────────
up:
	docker compose up -d

# ── down ──────────────────────────────────────────────────────────────────────
down:
	docker compose down

# ── logs ──────────────────────────────────────────────────────────────────────
logs:
	docker compose logs -f

# ── clean ─────────────────────────────────────────────────────────────────────
# Remove downloaded wheels (forces a fresh `make vendor` next time).
clean-vendor:
	@echo "==> Removing $(VENDOR_DIR)/*.whl ..."
	rm -f $(VENDOR_DIR)/*.whl
	@echo "==> Done."

# ── help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  make vendor        Download Python wheels for offline Docker build"
	@echo "  make build         Build Docker images (uses vendors if present)"
	@echo "  make up            Start the stack (docker compose up -d)"
	@echo "  make down          Stop the stack"
	@echo "  make logs          Tail container logs"
	@echo "  make clean-vendor  Delete downloaded wheels"
	@echo ""
