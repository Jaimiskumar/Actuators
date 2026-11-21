# Multi-stage minimal container for Log Detective
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Upgrade pip and build tooling
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy packaging configuration and core source code
COPY pyproject.toml README.md ./
COPY logdetective/ ./logdetective/

# Install logdetective with all dependencies
RUN pip install --no-cache-dir .[all]

# Copy developer tools, test suites, and sample logs for judging validation
COPY tools/ ./tools/
COPY tests/ ./tests/

# Default entrypoint runs the logdetective CLI
ENTRYPOINT ["logdetective"]
CMD ["--help"]
