"""
Create a new admin/owner user in a tenant schema, or promote an existing user.

Usage:
    # Create new admin in tenant
    python manage.py create_tenant_admin --schema=pomet --email=admin@example.com --username=admin --password=secret

    # Create with OWNER role
    python manage.py create_tenant_admin --schema=pomet --email=admin@example.com --username=admin --password=secret --role=OWNER

    # Promote existing user to ADMIN
    python manage.py create_tenant_admin --schema=pomet --email=existing@example.com --promote

    # Promote existing user to OWNER
    python manage.py create_tenant_admin --schema=pomet --email=existing@example.com --promote --role=OWNER
"""

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = "Create or promote a tenant admin/owner user."

    def add_arguments(self, parser):
        parser.add_argument("--schema", required=True, help="Tenant schema name (e.g. pomet)")
        parser.add_argument("--email", required=True, help="User email")
        parser.add_argument("--username", help="Username (required for new users)")
        parser.add_argument("--password", help="Password (required for new users)")
        parser.add_argument("--first-name", default="", help="First name")
        parser.add_argument("--last-name", default="", help="Last name")
        parser.add_argument(
            "--role",
            default="ADMIN",
            choices=["OWNER", "ADMIN"],
            help="Role to assign (default: ADMIN)",
        )
        parser.add_argument(
            "--promote",
            action="store_true",
            help="Promote an existing user instead of creating a new one",
        )

    def handle(self, *args, **options):
        schema = options["schema"]
        email = options["email"]
        role = options["role"]
        promote = options["promote"]

        with schema_context(schema):
            from users.models import User

            if promote:
                try:
                    user = User.objects.get(email=email)
                except User.DoesNotExist:
                    raise CommandError(f"User with email '{email}' not found in schema '{schema}'.")

                old_role = user.role
                user.role = role
                user.is_staff = True
                user.is_superuser = True
                user.is_active = True
                user.save(update_fields=["role", "is_staff", "is_superuser", "is_active"])
                self.stdout.write(self.style.SUCCESS(
                    f"Promoted {email} from {old_role} to {role} in '{schema}' (is_staff=True, is_superuser=True)"
                ))
            else:
                username = options.get("username")
                password = options.get("password")
                if not username or not password:
                    raise CommandError("--username and --password are required when creating a new user.")

                if User.objects.filter(email=email).exists():
                    raise CommandError(
                        f"User with email '{email}' already exists in schema '{schema}'. "
                        f"Use --promote to change their role."
                    )
                if User.objects.filter(username=username).exists():
                    raise CommandError(f"Username '{username}' already taken in schema '{schema}'.")

                user = User.objects.create_superuser(
                    username=username,
                    email=email,
                    password=password,
                    first_name=options["first_name"],
                    last_name=options["last_name"],
                )
                user.role = role
                user.save(update_fields=["role"])
                self.stdout.write(self.style.SUCCESS(
                    f"Created {role} user '{username}' ({email}) in schema '{schema}'"
                ))
