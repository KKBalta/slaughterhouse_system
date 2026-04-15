from django.apps import AppConfig


class LabelingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "labeling"

    def ready(self):
        from . import signals  # noqa: F401
