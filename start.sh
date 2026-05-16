#!/usr/bin/env bash
set -euo pipefail

# ── colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YLW='\033[0;33m'
GRN='\033[0;32m'
CYN='\033[0;36m'
BLD='\033[1m'
RST='\033[0m'

info()  { printf "${YLW}==>${RST} %s\n" "$*"; }
ok()    { printf "${GRN}  ✓${RST} %s\n" "$*"; }
err()   { printf "${RED}  ✗ ERROR:${RST} %s\n" "$*" >&2; }
fatal() { err "$*"; exit 1; }

# ── flags ─────────────────────────────────────────────────────────────────────
BUILD=false
for arg in "$@"; do
    case "$arg" in
        --build|-b) BUILD=true ;;
        --help|-h)
            echo "Usage: $0 [--build]"
            echo "  --build   Force rebuild of Docker images before starting"
            exit 0 ;;
        *) fatal "Unknown argument: $arg" ;;
    esac
done

# ── dependency bootstrap (Ubuntu only) ────────────────────────────────────────
is_ubuntu() { [[ -f /etc/os-release ]] && grep -qi "ubuntu" /etc/os-release; }

install_docker_ubuntu() {
    info "Docker not found — installing via official Docker repo (Ubuntu)..."
    command -v sudo >/dev/null 2>&1 || fatal "sudo not available; install Docker manually"

    sudo apt-get update -qq
    sudo apt-get install -y -qq ca-certificates curl gnupg lsb-release

    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    sudo systemctl enable --now docker
    ok "Docker installed and daemon started"

    if ! groups "$USER" | grep -q '\bdocker\b'; then
        sudo usermod -aG docker "$USER"
        ok "Added $USER to docker group — re-executing script in new group context..."
        exec sg docker "$0" "$@"
    fi
}

ensure_curl() {
    if ! command -v curl >/dev/null 2>&1; then
        if is_ubuntu; then
            info "curl not found — installing..."
            sudo apt-get update -qq
            sudo apt-get install -y -qq curl
            ok "curl installed"
        else
            fatal "curl not found in PATH"
        fi
    fi
}

# ── preflight ─────────────────────────────────────────────────────────────────
ensure_curl

if ! command -v docker >/dev/null 2>&1; then
    if is_ubuntu; then
        install_docker_ubuntu
    else
        fatal "docker not found in PATH — install Docker first"
    fi
fi

if ! docker info >/dev/null 2>&1; then
    if is_ubuntu && command -v systemctl >/dev/null 2>&1; then
        info "Docker daemon not running — starting..."
        sudo systemctl start docker
        sleep 2
        docker info >/dev/null 2>&1 || fatal "Docker daemon failed to start; check: sudo journalctl -u docker"
        ok "Docker daemon started"
    else
        fatal "Docker daemon is not running — start it first"
    fi
fi

if ! docker compose version >/dev/null 2>&1; then
    if is_ubuntu; then
        info "docker compose plugin missing — installing..."
        sudo apt-get update -qq
        sudo apt-get install -y -qq docker-compose-plugin
        ok "docker compose plugin installed"
    else
        fatal "'docker compose' plugin not available — install docker-compose-plugin"
    fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

[[ -f docker-compose.yml ]] || fatal "docker-compose.yml not found in $SCRIPT_DIR"

# ── build ─────────────────────────────────────────────────────────────────────
if $BUILD; then
    info "Building images..."
    mkdir -p backend/vendor
    docker compose build
    ok "Images built"
fi

# ── backend ───────────────────────────────────────────────────────────────────
info "Starting backend..."
docker compose up -d backend
ok "Backend container started"

# ── health poll ───────────────────────────────────────────────────────────────
HEALTH_URL="http://127.0.0.1:8080/health/"
TIMEOUT=60
INTERVAL=2
elapsed=0

info "Waiting for backend to be ready (timeout: ${TIMEOUT}s)..."
until curl --silent --fail --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; do
    if (( elapsed >= TIMEOUT )); then
        fatal "Backend did not become healthy within ${TIMEOUT}s. Check logs: docker compose logs backend"
    fi
    sleep "$INTERVAL"
    (( elapsed += INTERVAL )) || true
done
ok "Backend is healthy"

# ── frontend ──────────────────────────────────────────────────────────────────
info "Starting frontend..."
docker compose up -d frontend
ok "Frontend container started"

# ── URL summary ───────────────────────────────────────────────────────────────
printf "\n${BLD}${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}\n"
printf "${BLD}  IxNetwork Session Explorer — Services${RST}\n"
printf "${BLD}${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}\n"
printf "  ${GRN}%-20s${RST} %s\n" "Frontend UI"      "http://localhost:3000"
printf "  ${GRN}%-20s${RST} %s\n" "Backend API"      "http://localhost:8080"
printf "  ${GRN}%-20s${RST} %s\n" "API Docs"         "http://localhost:8080/docs"
printf "  ${GRN}%-20s${RST} %s\n" "Health Check"     "http://localhost:8080/health/"
printf "${BLD}${CYN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}\n\n"
