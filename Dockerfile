# Multi-stage / Production Python 3.12 Slim Image
FROM python:3.12-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install build dependencies, build wheels, then purge build packages
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y gcc libpq-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Copy project code
COPY . .

# Create non-root user for enhanced security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose FastAPI port
EXPOSE 8000

# Default command: run FastAPI web server with Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
