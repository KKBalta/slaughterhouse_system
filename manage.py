#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys
from pathlib import Path


def _load_env_file(path: Path) -> None:
    """Apply KEY=value lines into os.environ (overrides). Decouple honors env over `.env`."""
    text = path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = rest.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ[key] = val


def _preload_optional_dotenv() -> None:
    """Use a specific env file before settings load (optional).

    Resolution order: ``DOTENV_FILE``, then ``CARNITRACK_ENV`` / ``ENV`` (e.g. ``.env.staging``),
    then ``.env.dev`` if that file exists in the project root (local dev default).

    Examples::

        CARNITRACK_ENV=staging python manage.py createsuperuser
        DOTENV_FILE=.env.staging python manage.py migrate
    """
    root = Path(__file__).resolve().parent
    path_str = os.environ.get("DOTENV_FILE", "").strip()
    if not path_str:
        slug = os.environ.get("CARNITRACK_ENV", "").strip() or os.environ.get("ENV", "").strip()
        if slug == "env.staging":
            slug = "staging"
        elif slug == "env.dev":
            slug = "dev"
        if slug:
            candidate = root / f".env.{slug}"
            if candidate.is_file():
                path_str = str(candidate)
    if not path_str:
        dev_env = root / ".env.dev"
        if dev_env.is_file():
            path_str = str(dev_env)
    if not path_str:
        return
    path = Path(path_str)
    if not path.is_file():
        path = root / path_str
    if path.is_file():
        _load_env_file(path)


def main():
    """Run administrative tasks."""
    _preload_optional_dotenv()
    argv = sys.argv
    has_explicit_settings = any(arg.startswith("--settings=") for arg in argv)
    if len(argv) > 1 and argv[1] == "test" and not has_explicit_settings and "DJANGO_SETTINGS_MODULE" not in os.environ:
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_test"
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
