from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create system user for automated report generation"

    def handle(self, *args, **options):
        User = get_user_model()

        # Create system user if it doesn't exist
        system_user, created = User.objects.get_or_create(
            username="system",
            defaults={
                "email": "system@slaughterhouse.local",
                "first_name": "System",
                "last_name": "User",
                "role": "ADMIN",
                "is_staff": True,
                "is_active": True,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS("System user created successfully"))
        else:
            self.stdout.write(self.style.WARNING("System user already exists"))
