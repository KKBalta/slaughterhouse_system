"""
Django test settings for CI/CD and local testing.

This configuration is optimized for fast test execution.
"""

import os
from pathlib import Path

from django.utils.translation import gettext_lazy as _

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Test environment settings
SECRET_KEY = "test-secret-key-for-ci-only-not-for-production"
DEBUG = True

# SQLite tests do not run the full django-tenants stack; views use getattr(..., False) where possible.
# Tests and tenants.services import tenants.models → django_tenants.DomainMixin, which requires
# TENANT_MODEL / TENANT_DOMAIN_MODEL at import time. (tenants app is not in INSTALLED_APPS: its migrations
# are PostgreSQL-specific; tenant-registration URLs use lazy view imports.)
USE_MULTITENANT = False
TENANT_MODEL = "tenants.Client"
TENANT_DOMAIN_MODEL = "tenants.Domain"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
CSRF_TRUSTED_ORIGINS = ["http://localhost", "http://127.0.0.1"]

# Application definition
# Note: do not list django_tenants here — its AppConfig requires TENANT_APPS / SHARED_APPS.
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_fsm",
    "tailwind",
    "theme",
    "widget_tweaks",
    "tenants",
    # Local Apps
    "users",
    "reception",
    "processing",
    "inventory",
    "portal",
    "core",
    "labeling",
    "reporting",
    "scales",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "tenants.middleware.ClearLegacyMessagesCookieMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Match production: session-only flash storage (see config/settings.py).
MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# -------------------------
# Database Configuration for Tests
# Use SQLite for speed, or PostgreSQL for parity with production
# -------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",  # In-memory database for fast tests
    }
}

# Use PostgreSQL in CI if environment variables are set
if os.environ.get("USE_POSTGRES_FOR_TESTS"):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("TEST_DB_NAME", "test_carnitrack"),
        "USER": os.environ.get("TEST_DB_USER", "postgres"),
        "PASSWORD": os.environ.get("TEST_DB_PASSWORD", "postgres"),
        "HOST": os.environ.get("TEST_DB_HOST", "localhost"),
        "PORT": os.environ.get("TEST_DB_PORT", "5432"),
    }

# -------------------------
# Password validation - Disabled for faster tests
# -------------------------
AUTH_PASSWORD_VALIDATORS = []

# -------------------------
# Internationalization
# -------------------------
LANGUAGE_CODE = "en"  # Use English for consistent test assertions
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LANGUAGES = [
    ("tr", _("Turkish")),
    ("en", _("English")),
]

LOCALE_PATHS = [BASE_DIR / "locale"]

LANGUAGE_COOKIE_NAME = "django_language"
LANGUAGE_COOKIE_SECURE = False
LANGUAGE_COOKIE_HTTPONLY = False

# -------------------------
# Static and Media files for tests
# -------------------------
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles_test")
STATICFILES_DIRS = []

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media_test")

# Use simple storage backend for tests (no manifest – avoids "Missing staticfiles
# manifest entry" when templates reference {% static %} and collectstatic not run).
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# -------------------------
# Other settings
# -------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TAILWIND_APP_NAME = "theme"
AUTH_USER_MODEL = "users.User"

# Fallback when tenant URL is not used (SQLite tests)
SITE_URL_FALLBACK = "http://testserver"

# When USE_MULTITENANT is False, labeling.get_company_info() reads these optional settings (same keys as legacy single-tenant).
COMPANY_NAME = "Test Company"
COMPANY_FULL_NAME = "Test Company Ltd"
COMPANY_ADDRESS = "Test Address"
LICENSE_NO = "00-0000"
OPERATION_NO = "0000000000"

# Printer Settings (per-tenant in multitenant mode; kept here as test fallback for SQLite runs)
PRINTER_TURKISH_MODE = "unicode"

# Authentication Settings
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/logged-out/"

# -------------------------
# Test-specific optimizations
# -------------------------

# MD5 hasher is for test speed only; never use in production.
# Django's default (PBKDF2) is used in production (config/settings.py).
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Disable debug toolbar in tests
DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": lambda request: False,
}

# Email backend for tests - don't send actual emails
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Logging - reduce noise during tests
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}
