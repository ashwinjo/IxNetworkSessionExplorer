# Docker Modernisation Modifications
Portable reference for applying same fixes to any repo.

---

## 1. docker-compose.*.yml — Modern Compose Spec

### Remove version key
```yaml
# DELETE this line entirely
version: '3.8'
```
Compose Spec (2021+) ignores and warns on `version:`. Remove it.

### Remove explicit default drivers
```yaml
# BEFORE
networks:
  my-network:
    driver: bridge

volumes:
  my-data:
    driver: local

# AFTER
networks:
  my-network:

volumes:
  my-data:
```
`bridge` and `local` are defaults. Declaring them is noise.

### Remove `platforms` from build block
```yaml
# BEFORE
build:
  context: .
  dockerfile: Dockerfile
  platforms:
    - linux/amd64
    - linux/arm64

# AFTER
build:
  context: .
  dockerfile: Dockerfile
```
`platforms` in compose `build` requires `docker buildx bake`. Standard
`docker compose build` rejects it. Remove for local/CI use.

### Switch bind mounts to named volumes (WSL fix)
```yaml
# BEFORE — bind mount causes UID mismatch on WSL
volumes:
  - ./data:/app/data

# AFTER — Docker manages ownership, no host UID issues
volumes:
  - my-data:/app/data
```
Bind mounts inherit host UID/GID. On WSL the container user (uid 1000)
often mismatches the Windows-side host UID. Named volumes bypass this
entirely — Docker owns them, container user owns files inside.

### Add extra_hosts for Linux Docker Engine (no Docker Desktop)
```yaml
services:
  my-service:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```
`host.docker.internal` resolves automatically on macOS and WSL+Docker Desktop.
On bare Ubuntu Docker Engine it does not exist. `host-gateway` is a Docker
Engine special value (20.10+) that resolves to the host's gateway IP.

---

## 2. Dockerfiles — Modern Patterns

### Replace `pip install uv` with official uv image copy
```dockerfile
# BEFORE
RUN apt-get update && apt-get install -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv

# AFTER
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

RUN apt-get update && apt-get install -y \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/*
```
`pip install uv` bootstraps uv through pip — slow and fragile.
The `COPY --from` pattern grabs just the uv binary from the official image.
Deterministic, no network install, no pip involved.

### Update Node base image (18 is EOL)
```dockerfile
# BEFORE
FROM node:18-alpine

# AFTER
FROM node:22-alpine
```
Node 18 hit EOL April 2025. Node 22 is current LTS (supported until April 2028).

### Fix USER-switching dance for entrypoint chmod
```dockerfile
# BEFORE — messy USER switches
COPY --chown=appuser:appuser docker-entrypoint.sh /app/
USER root
RUN chmod +x /app/docker-entrypoint.sh
USER appuser

# AFTER — all root ops before final user handoff
COPY . .
RUN chmod +x /app/docker-entrypoint.sh

RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser
```
Do all root operations (chmod, mkdir, chown) in a single block before the
final `USER` switch. Avoids ping-ponging between root and non-root layers.

### Remove HEALTHCHECK from Dockerfile when compose defines it
```dockerfile
# REMOVE from Dockerfile when docker-compose healthcheck is present
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1
```
Compose healthcheck takes precedence and is more configurable. Defining both
is redundant. Keep one place — prefer compose so it's visible alongside the
service definition.

---

## 3. docker-rebuild.sh — Cross-Platform Script

### Use portable shebang
```bash
# BEFORE
#!/bin/bash

# AFTER
#!/usr/bin/env bash
```
`/bin/bash` on macOS is Bash 3.2 (Apple GPL3 lock). `env bash` picks up
Homebrew Bash 5.x if present. More portable across systems.

### ASCII-only — no em-dashes or smart quotes
```bash
# BEFORE — em-dash breaks on some WSL locales
# ── Section ──

# AFTER — plain ASCII
# ============= Section =============
```

### Replace legacy `docker-compose` with `docker compose` (plugin)
```bash
# BEFORE — standalone binary, deprecated
docker-compose -f docker-compose.separate.yml up -d

# AFTER — Compose V2 plugin
docker compose -f docker-compose.separate.yml up -d
```

### OS detection with WSL awareness
```bash
detect_os() {
    case "$(uname -s)" in
        Darwin) echo "macos" ;;
        Linux)
            if grep -qi microsoft /proc/version 2>/dev/null; then
                echo "wsl"
            else
                echo "linux"
            fi
            ;;
        *) echo "unknown" ;;
    esac
}
OS=$(detect_os)
```

### Detect systemd before using systemctl
```bash
is_systemd_running() {
    [[ "$(ps --no-headers -o comm 1 2>/dev/null)" == "systemd" ]]
}
```
WSL without `[boot] systemd=true` in `/etc/wsl.conf` does NOT run systemd.
Calling `systemctl` blindly errors. Always check first.

### Start Docker daemon with correct method per environment
```bash
start_docker_daemon() {
    if is_systemd_running; then
        sudo systemctl start docker
        return
    fi
    # WSL without systemd: SysV init wrapper
    if command -v service &>/dev/null; then
        sudo service docker start
        return
    fi
    echo "[ERROR] Cannot start Docker: neither systemd nor service found."
    echo "WSL: add to /etc/wsl.conf and restart WSL:"
    echo "  [boot]"
    echo "  systemd=true"
    exit 1
}
```

### Handle Docker installed but daemon not running (all platforms)
```bash
# Binary present but daemon dead
if command -v docker &>/dev/null; then
    if ! docker info &>/dev/null 2>&1; then
        case "$OS" in
            macos)
                # macOS: daemon = Docker Desktop, can't start programmatically
                echo "[ERROR] Start Docker Desktop and re-run."
                exit 1
                ;;
            linux|wsl)
                # WSL+Docker Desktop: socket exists, daemon is Windows-side
                if [[ -S /var/run/docker.sock ]]; then
                    echo "Docker socket found (Docker Desktop integration)."
                else
                    start_docker_daemon
                fi
                ;;
        esac
    fi
fi
```

### Fix fresh-install group membership not taking effect
```bash
# After: sudo usermod -aG docker "$USER"
# Group change does NOT affect current shell session.
# Set flag so all remaining docker calls use sudo.

DOCKER_SUDO=""   # global, set to "sudo" after fresh install

# Wrapper function used for ALL docker compose calls
dc() {
    if [[ -n "$DOCKER_SUDO" ]]; then
        sudo docker compose "$@"
    else
        docker compose "$@"
    fi
}

# After fresh install:
sudo usermod -aG docker "$USER"
DOCKER_SUDO="sudo"   # rest of script uses sudo automatically via dc()
```
Without this, all `docker compose` calls after a fresh install fail with
`permission denied on /var/run/docker.sock` until the user re-logins.

### Guard: apt-get not universal on Linux
```bash
require_apt() {
    if ! command -v apt-get &>/dev/null; then
        echo "[ERROR] apt-get not found. Debian/Ubuntu only for auto-install."
        echo "Install Docker manually: https://docs.docker.com/get-docker/"
        exit 1
    fi
}
```
Prevents silent failure on RHEL, Fedora, Arch, Alpine.

### Guard: must run from project root
```bash
check_project_root() {
    if [[ ! -f "docker-compose.separate.yml" || ! -f "docker-compose.combined.yml" ]]; then
        echo "[ERROR] Compose files not found in current directory."
        echo "Run this script from the project root."
        exit 1
    fi
}
```

### Use `${DOCKER_SUDO:+sudo}` for conditional sudo
```bash
# Parameter expansion: expands to "sudo" if DOCKER_SUDO is non-empty, else ""
if ${DOCKER_SUDO:+sudo} docker compose version &>/dev/null 2>&1; then
```

### Parse compose version portably (--short flag not universal)
```bash
# BEFORE — --short not available in all versions
docker compose version --short

# AFTER — works everywhere
docker compose version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1
```

### Never use `down -v` in rebuild scripts
```bash
# BEFORE — destroys named volumes = wipes database
docker compose down -v

# AFTER — stops containers, preserves volumes
docker compose down
```

### Enable BuildKit via env var, not build-arg
```bash
# BEFORE — inline cache arg, verbose
docker compose build --build-arg BUILDKIT_INLINE_CACHE=1

# AFTER — BuildKit is default since Docker 23.0; explicit env var for older
DOCKER_BUILDKIT=1 docker compose build
```

---

## Platform Compatibility Matrix

| Feature | macOS (Docker Desktop) | Ubuntu (Docker Engine) | WSL + Docker Desktop | WSL + Native Engine |
|---|---|---|---|---|
| `version:` removed | OK | OK | OK | OK |
| Named volumes | OK | OK | OK | OK |
| `host.docker.internal` | Native | Needs `extra_hosts` | Native | Needs `extra_hosts` |
| `systemctl` | N/A | OK (systemd) | Depends on wsl.conf | Depends on wsl.conf |
| `service docker start` | N/A | Fallback | Fallback | Fallback |
| `docker compose` plugin | Bundled | Install `docker-compose-plugin` | Bundled | Install `docker-compose-plugin` |
| Node 22 base image | OK | OK | OK | OK |
| uv from image copy | OK | OK | OK | OK |
