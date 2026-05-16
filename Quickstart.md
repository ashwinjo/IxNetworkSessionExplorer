# Quickstart — Fresh Ubuntu / AWS EC2

## 1. Install git

```bash
sudo apt update && sudo apt install -y git
```

## 2. Clone repo

```bash
git clone https://github.com/yourusername/IxNetworkSessionExplorer.git
cd IxNetworkSessionExplorer
```

## 3. Run start.sh

```bash
./start.sh --build
```

Script auto-handles:
- Installs `curl` if missing
- Adds Docker CE apt repo + installs `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin`, `docker-compose-plugin`
- Enables + starts Docker daemon
- Adds current user to `docker` group, re-execs via `sg docker`
- Builds backend image (`python:3.11-slim` + app)
- Starts backend, polls `/health/` until ready
- Starts frontend (nginx)

> Requires `sudo` privileges for Docker installation.

## 4. Verify

```bash
curl http://localhost:8080/health/
curl http://localhost:3000
```

## 5. Access from browser

On EC2, open inbound ports in your security group:

| Port | Protocol | Source |
|------|----------|--------|
| 3000 | TCP | Your IP |
| 8080 | TCP | Your IP |

Then open: `http://<ec2-public-ip>:3000`

## 6. Manage

```bash
docker compose logs -f backend     # tail logs
docker compose down                # stop
docker compose down -v             # stop + wipe DB
./start.sh                         # restart (no rebuild)
./start.sh --build                 # restart + rebuild
```
