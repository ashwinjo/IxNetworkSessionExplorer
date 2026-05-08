# ---- build stage ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools + copy dependency manifests
COPY pyproject.toml requirements.txt ./

# Install runtime deps into an isolated prefix so we can copy them cleanly
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---- runtime stage ----
FROM python:3.11-slim

LABEL org.opencontainers.image.title="IxNetworkSessionExplorer" \
      org.opencontainers.image.description="Unified IxNetwork session manager" \
      org.opencontainers.image.version="0.1.0"

# Non-root user for security
RUN useradd --create-home --shell /bin/bash ixse

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY ixse/ ./ixse/
COPY pyproject.toml ./

# Install the package itself (no deps — already installed above)
RUN pip install --no-cache-dir --no-deps -e .

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
