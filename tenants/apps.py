from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tenants"
    verbose_name = "Tenants"

    def ready(self) -> None:
        from django.conf import settings

        # Importing django_tenants.signals registers a global post_delete handler; skip when not multitenant
        # (e.g. settings_test + SQLite) so unrelated model deletes do not call get_tenant_model().
        if getattr(settings, "USE_MULTITENANT", True):
            import tenants.signals  # noqa: F401
