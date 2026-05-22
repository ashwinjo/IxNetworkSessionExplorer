#!/usr/bin/env bash
set -euo pipefail

# ============= colors =============================================================
RED='\033[0;31m'
YLW='\033[0;33m'
GRN='\033[0;32m'
CYN='\033[0;36m'
BLD='\033[1m'
RST='\033[0m'

info()  { printf "${YLW}==>${RST} %s\n" "$*"; }
ok()    { printf "${GRN}  v${RST} %s\n" "$*"; }
err()   { printf "${RED}  x ERROR:${RST} %s\n" "$*" >&2; }
fatal() { err "$*"; exit 1; }

# ============= flags ==============================================================
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

# ============= OS detection =======================================================
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

# ============= systemd check ======================================================
is_systemd_running() {
    [[ "$(ps --no-headers -o comm 1 2>/dev/null)" == "systemd" ]]
}

# ============= sudo docker wrapper ================================================
# Set to "sudo" after fresh docker group add so remaining calls work without re-login.
DOCKER_SUDO=""

dc() {
    if [[ -n "$DOCKER_SUDO" ]]; then
        sudo docker compose "$@"
    else
        docker compose "$@"
    fi
}

# ============= platform-specific installers =======================================
require_apt() {
    if ! command -v apt-get &>/dev/null; then
        fatal "apt-get not found. Debian/Ubuntu only for auto-install. Install Docker manually: https://docs.docker.com/get-docker/"
    fi
}

install_docker_ubuntu() {
    info "Docker not found — installing via official Docker repo (Ubuntu/Debian)..."
    require_apt
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

    start_docker_daemon
    ok "Docker installed and daemon started"

    if ! groups "$USER" | grep -q '\bdocker\b'; then
        sudo usermod -aG docker "$USER"
        DOCKER_SUDO="sudo"
        ok "Added $USER to docker group (re-login required to take full effect)"
        ok "Using sudo for this session's docker calls"
    fi
}

install_docker_macos() {
    if command -v brew &>/dev/null; then
        info "Docker not found — installing Docker via Homebrew (this installs Docker Desktop)..."
        brew install --cask docker
        ok "Docker Desktop installed via Homebrew"
        info "Launch Docker Desktop from Applications, then re-run this script."
        exit 0
    else
        fatal "Docker not found. Install Docker Desktop from https://docs.docker.com/desktop/mac/install/ then re-run."
    fi
}

# ============= daemon management ==================================================
start_docker_daemon() {
    if is_systemd_running; then
        sudo systemctl start docker
        return
    fi
    # WSL without systemd / SysV init fallback
    if command -v service &>/dev/null; then
        sudo service docker start
        return
    fi
    err "Cannot start Docker: neither systemd nor service found."
    err "WSL users: add to /etc/wsl.conf and restart WSL:"
    err "  [boot]"
    err "  systemd=true"
    exit 1
}

ensure_docker_daemon() {
    if docker info &>/dev/null; then
        return 0
    fi

    case "$OS" in
        macos)
            # macOS daemon = Docker Desktop; cannot start programmatically
            err "Docker Desktop is not running."
            err "Start Docker Desktop from Applications and re-run this script."
            exit 1
            ;;
        wsl)
            # Docker Desktop for Windows integration: socket exists but daemon is Windows-side
            if [[ -S /var/run/docker.sock ]]; then
                ok "Docker socket found (Docker Desktop for Windows integration)"
                # Socket exists but current user may need sudo — try with sudo
                if sudo docker info &>/dev/null 2>&1; then
                    DOCKER_SUDO="sudo"
                    ok "Using sudo for Docker calls (Docker Desktop integration)"
                    return 0
                fi
            fi
            info "Docker daemon not running — attempting to start..."
            start_docker_daemon
            sleep 2
            if ! docker info &>/dev/null && ! sudo docker info &>/dev/null 2>&1; then
                fatal "Docker daemon failed to start. Check: sudo journalctl -u docker  OR  sudo service docker status"
            fi
            ;;
        linux)
            info "Docker daemon not running — attempting to start..."
            start_docker_daemon
            sleep 2
            docker info &>/dev/null || fatal "Docker daemon failed to start. Check: sudo journalctl -u docker"
            ok "Docker daemon started"
            ;;
        *)
            fatal "Docker daemon is not running — start it first"
            ;;
    esac
}

# ============= curl install =======================================================
ensure_curl() {
    if command -v curl &>/dev/null; then
        return 0
    fi
    case "$OS" in
        linux|wsl)
            require_apt
            info "curl not found — installing..."
            sudo apt-get update -qq
            sudo apt-get install -y -qq curl
            ok "curl installed"
            ;;
        macos)
            # curl ships with macOS; should never be missing
            fatal "curl not found. Install via: brew install curl"
            ;;
        *)
            fatal "curl not found in PATH"
            ;;
    esac
}

# ============= preflight ==========================================================
ensure_curl

if ! command -v docker &>/dev/null; then
    case "$OS" in
        linux|wsl) install_docker_ubuntu ;;
        macos)     install_docker_macos ;;
        *)         fatal "docker not found in PATH — install Docker first: https://docs.docker.com/get-docker/" ;;
    esac
fi

ensure_docker_daemon

if ! dc version &>/dev/null 2>&1; then
    case "$OS" in
        linux|wsl)
            require_apt
            info "docker compose plugin missing — installing..."
            sudo apt-get update -qq
            sudo apt-get install -y -qq docker-compose-plugin
            ok "docker compose plugin installed"
            ;;
        macos)
            fatal "'docker compose' plugin not available — Docker Desktop bundles it. Ensure Docker Desktop is up to date."
            ;;
        *)
            fatal "'docker compose' plugin not available — install docker-compose-plugin"
            ;;
    esac
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

[[ -f docker-compose.yml ]] || fatal "docker-compose.yml not found in $SCRIPT_DIR"
BIND_ADDR="${IXSE_BIND_ADDR:-0.0.0.0}"

# ============= build ==============================================================
if $BUILD; then
    info "Building images..."
    mkdir -p backend/vendor
    dc build
    ok "Images built"
fi

# ============= backend ============================================================
info "Starting backend..."
dc up -d backend
ok "Backend container started"

# ============= health poll ========================================================
HEALTH_URL="http://127.0.0.1:8080/health/"
TIMEOUT=60
INTERVAL=2
elapsed=0

info "Waiting for backend to be ready (timeout: ${TIMEOUT}s)..."
until curl --silent --fail --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; do
    if (( elapsed >= TIMEOUT )); then
        fatal "Backend did not become healthy within ${TIMEOUT}s. Check logs: dc logs backend"
    fi
    sleep "$INTERVAL"
    (( elapsed += INTERVAL )) || true
done
ok "Backend is healthy"

# ============= frontend ===========================================================
info "Starting frontend..."
dc up -d frontend
ok "Frontend container started"

# ============= URL summary ========================================================
printf "\n${BLD}${CYN}==============================================${RST}\n"
printf "${BLD}  IxNetwork Session Explorer -- Services${RST}\n"
printf "${BLD}${CYN}==============================================${RST}\n"
printf "  ${GRN}%-20s${RST} %s\n" "Frontend UI"      "http://${BIND_ADDR}:3000"
printf "  ${GRN}%-20s${RST} %s\n" "Backend API"      "http://${BIND_ADDR}:8080"
printf "  ${GRN}%-20s${RST} %s\n" "API Docs"         "http://${BIND_ADDR}:8080/docs"
printf "  ${GRN}%-20s${RST} %s\n" "Health Check"     "http://${BIND_ADDR}:8080/health/"
printf "${BLD}${CYN}==============================================${RST}\n\n"
