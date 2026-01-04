# Dockerfile for Jarvis MVP
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (for task executor)
RUN playwright install --with-deps chromium

# Copy application code
COPY jarvis/ ./jarvis/

# Expose API port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "jarvis.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
