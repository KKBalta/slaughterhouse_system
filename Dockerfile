FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Install system dependencies including Node.js for Tailwind
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        pkg-config \
        curl \
        build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create directories
RUN mkdir -p staticfiles media

# Set default environment variables for build
ENV DEBUG=False
ENV ALLOWED_HOSTS=localhost
ENV CSRF_TRUSTED_ORIGINS=https://localhost
ENV USE_CLOUD_SQL=False
ENV SECRET_KEY=dummy-build-secret

# Install Tailwind dependencies (with better error handling)
RUN python manage.py tailwind install --no-input 2>/dev/null || echo "Tailwind install skipped - theme app not configured"

# Build Tailwind CSS (with better error handling)
RUN python manage.py tailwind build --no-input 2>/dev/null || echo "Tailwind build skipped - using default styles"

# Collect static files
RUN python manage.py collectstatic --noinput --clear

# Create a non-root user
RUN adduser --disabled-password --gecos '' appuser \
    && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/ || exit 1

# Start command
CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "--timeout", "0", "config.wsgi:application"]