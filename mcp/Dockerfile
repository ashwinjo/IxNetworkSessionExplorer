FROM python:3.11-slim

WORKDIR /app

# Install build backend first (hatchling required by pyproject.toml)
RUN pip install --no-cache-dir hatchling

# Copy package definition and source
COPY pyproject.toml ixnse_mcp.py ./

# Install the package and its runtime deps
RUN pip install --no-cache-dir .

ENV IXNSE_API_URL=http://backend:8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8889

CMD ["ixnse-mcp", "--host", "0.0.0.0", "--port", "8889"]
