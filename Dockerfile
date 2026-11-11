FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data

WORKDIR /app

# Install system dependencies (curl, libglib, libgl, libxcb for image processing/opencv)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    libgl1 \
    libxcb1 \
    libx11-6 \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app/ ./app/

# Create data directories
RUN mkdir -p /app/data/uploads/thumbnails

# Expose port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Start uvicorn with proxy headers enabled for 1Panel OpenResty / Nginx
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

