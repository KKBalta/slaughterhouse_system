from django.apps import AppConfig


class ScalesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scales"
    verbose_name = "Scale Operations (CarniTrack Edge)"

    def ready(self):
        import scales.signals  # noqa: F401
