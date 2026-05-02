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
    && pip install --no-cache-dir -r requirements.txt \
    && pip show django-storages \
    && pip show google-cloud-storage

# Copy project files
COPY . .

# Create directories
RUN mkdir -p staticfiles media

# Set default environment variables for build
ENV DEBUG=False
ENV ALLOWED_HOSTS=localhost
ENV CSRF_TRUSTED_ORIGINS=https://localhost
ENV USE_CLOUD_SQL=False
ENV USE_SQLITE=True
ENV SECRET_KEY=dummy-build-secret
ENV TENANT_BASE_DOMAIN=localhost

# Tailwind v4 + PostCSS — same as `make tailwind-build` (theme/static_src → theme/static/css/dist).
# Must not fail silently: collectstatic would ship stale or missing CSS.
RUN cd theme/static_src && npm ci && npm run build

# Collect static files. BUILD_PHASE is inline (not ENV) so it does NOT persist
# into the runtime image — production runtime never sees it, keeping the SQLite
# safety guard in config/settings.py intact.
RUN BUILD_PHASE=True python manage.py collectstatic --noinput --clear

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
