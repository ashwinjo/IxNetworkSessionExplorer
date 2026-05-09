# ---- build stage ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Copy vendored wheels first (may be an empty directory — that is fine).
# When vendor/ contains all required wheels, pip uses them directly and
# never opens a network connection.  When vendor/ is empty the build
# falls back to PyPI as normal.
COPY vendor/ /vendor/

# Copy dependency manifests
COPY pyproject.toml requirements.txt ./

# Install runtime deps into an isolated prefix so they copy cleanly.
# --find-links /vendor  → prefer local wheels over PyPI
# --no-index            → only used when vendor/ is populated (see Makefile)
#
# We use a shell form so we can test whether wheels exist and choose the
# right pip flags at build time.
RUN if [ "$(ls /vendor/*.whl 2>/dev/null | wc -l)" -gt 0 ]; then \
        pip install --no-cache-dir --prefix=/install \
            --find-links /vendor --no-index \
            -r requirements.txt; \
    else \
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
