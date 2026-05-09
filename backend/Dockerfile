# ---- build stage ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Copy dependency manifests
COPY pyproject.toml requirements.txt ./

# Create /vendor unconditionally so the subsequent COPY never fails even
# when the host-side vendor/ directory is absent or empty.
# `make build` also runs `mkdir -p backend/vendor` for the same reason.
RUN mkdir -p /vendor
COPY vendor/ /vendor/

# Install runtime deps into an isolated prefix so they copy cleanly.
# If vendor/ contains wheels (populated by `make vendor`), pip uses them
# directly and never opens a network connection.  Otherwise it falls back
# to PyPI as normal.
RUN if [ "$(ls /vendor/*.whl 2>/dev/null | wc -l)" -gt 0 ]; then \
        echo "==> Prefer vendor wheels, fall back to PyPI for unmatched platforms" && \
        pip install --no-cache-dir --prefix=/install \
            --find-links /vendor \
            -r requirements.txt; \
    else \
        echo "==> Online install from PyPI" && \
        pip install --no-cache-dir --prefix=/install \
            -r requirements.txt; \
    fi

# Copy source and build the wheel
COPY ixse/ ./ixse/
RUN pip install --no-cache-dir --prefix=/install --no-deps .


# ---- runtime stage ----
FROM python:3.11-slim

LABEL org.opencontainers.image.title="IxNetworkSessionExplorer" \
      org.opencontainers.image.description="Unified IxNetwork session manager" \
      org.opencontainers.image.version="0.1.0"

# Non-root user for security
RUN useradd --create-home --shell /bin/bash ixse

WORKDIR /app

# Copy installed packages (deps + the ixse package itself) from builder
COPY --from=builder /install /usr/local

# Writable data directory for SQLite
RUN mkdir -p /app/data && chown ixse:ixse /app/data

USER ixse

# Config is expected at /app/ixse_config.yaml — mount it at runtime.
# Override with IXSE_CONFIG env var to use a different path.
ENV IXSE_CONFIG=/app/ixse_config.yaml \
    IXSE_DB=/app/data/ixse.db \
    PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health/')" || exit 1

CMD ["uvicorn", "ixse.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
