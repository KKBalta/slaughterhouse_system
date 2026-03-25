from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context

from tenants.models import PlatformAdmin


class Command(BaseCommand):
    help = "Create or update a PlatformAdmin user in the public schema (SamperLabs staff)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Login email (unique).")
        parser.add_argument("--name", default="", help="Display name.")
        parser.add_argument("--password", required=True, help="Password (will be hashed).")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        name = options["name"].strip() or email
        password = options["password"]

        with schema_context(get_public_schema_name()):
            obj, created = PlatformAdmin.objects.get_or_create(
                email=email,
                defaults={"name": name},
            )
            if not created:
                obj.name = name or obj.name
            obj.set_password(password)
            obj.is_active = True
            obj.save()

        action = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{action} platform admin: {email}"))
