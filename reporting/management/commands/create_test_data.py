from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import ServicePackage
from processing.models import Animal, BeefDetails, LambDetails, SheepDetails, WeightLog
from reception.models import SlaughterOrder
from users.models import ClientProfile

User = get_user_model()


class Command(BaseCommand):
    help = "Create test data for reporting (last 7 days)"

    def handle(self, *args, **options):
        # Manager user
        manager, created = User.objects.get_or_create(
            username="manager",
            defaults={"email": "manager@example.com", "first_name": "Test", "last_name": "Manager", "role": "MANAGER"},
        )
        if created:
            manager.set_password("manager123")
            manager.save()
            self.stdout.write(self.style.SUCCESS("Created manager user  (manager / manager123)"))

        # Client user + profile
        client_user, created = User.objects.get_or_create(
            username="testclient",
            defaults={"email": "client@example.com", "first_name": "Ali", "last_name": "Yılmaz", "role": "CLIENT"},
        )
        if created:
            client_user.set_password("client123")
            client_user.save()
            self.stdout.write(self.style.SUCCESS("Created client user  (testclient / client123)"))

        client_profile, _ = ClientProfile.objects.get_or_create(
            user=client_user,
            defaults={
                "account_type": "ENTERPRISE",
                "company_name": "Ali Yılmaz Et Ltd. Şti.",
                "phone_number": "05551234567",
                "address": "Çanakkale Merkez",
            },
        )

        # Second client (walk-in style, no user account)
        walkin_profile, _ = ClientProfile.objects.get_or_create(
            contact_person="Mehmet Demir",
            defaults={
                "account_type": "INDIVIDUAL",
                "phone_number": "05559876543",
                "address": "Ezine, Çanakkale",
            },
        )

        # Service packages
        basic_pkg, _ = ServicePackage.objects.get_or_create(
            name="Temel Kesim",
            defaults={"includes_disassembly": False, "includes_delivery": False},
        )
        full_pkg, _ = ServicePackage.objects.get_or_create(
            name="Tam Hizmet (Parçalama + Teslimat)",
            defaults={"includes_disassembly": True, "includes_delivery": True},
        )

        today = timezone.now().date()
        created_count = 0

        # --- Animal templates: (type, live_w, hot_w, leather_w, details_cls, breed_kwarg) ---
        ANIMALS = [
            ("beef",   450, 270, 14.0, BeefDetails,  {"breed": "Simmental"}),
            ("beef",   420, 248, 12.5, BeefDetails,  {"breed": "Angus"}),
            ("beef",   380, 220, 11.0, BeefDetails,  {"breed": "Holstein"}),
            ("lamb",    45,  25,  1.2, LambDetails,  {}),
            ("lamb",    42,  23,  1.0, LambDetails,  {}),
            ("sheep",   70,  40,  2.5, SheepDetails, {"breed": "Merino"}),
        ]

        for day_offset in range(7):
            order_date = today - timedelta(days=day_offset)
            slaughter_dt = timezone.make_aware(datetime.combine(order_date, datetime.min.time()))

            # Alternate between client_profile and walkin_profile
            client = client_profile if day_offset % 2 == 0 else walkin_profile
            pkg = full_pkg if day_offset % 3 != 0 else basic_pkg

            order, order_created = SlaughterOrder.objects.get_or_create(
                client=client,
                order_datetime=slaughter_dt,
                defaults={
                    "service_package": pkg,
                    "status": "COMPLETED",
                    "destination": "Soğuk Hava Deposu" if day_offset % 2 == 0 else "Müşteriye Teslim",
                },
            )

            if not order_created:
                continue

            for idx, (atype, live_w, hot_w, leather_w, details_cls, details_kwargs) in enumerate(ANIMALS):
                tag = f"{atype.upper()}-{order_date.strftime('%Y%m%d')}-{idx + 1:03d}"

                animal = Animal.objects.create(
                    slaughter_order=order,
                    animal_type=atype,
                    identification_tag=tag,
                    received_date=slaughter_dt - timedelta(hours=3),
                    slaughter_date=slaughter_dt,
                    status="carcass_ready",
                    leather_weight_kg=Decimal(str(leather_w)),
                )

                WeightLog.objects.create(
                    animal=animal,
                    weight=Decimal(str(live_w)),
                    weight_type="live_weight",
                    is_group_weight=False,
                )
                WeightLog.objects.create(
                    animal=animal,
                    weight=Decimal(str(hot_w)),
                    weight_type="hot_carcass_weight",
                    is_group_weight=False,
                )

                details_cls.objects.create(
                    animal=animal,
                    sakatat_status=Decimal("1.0"),
                    bowels_status=Decimal("1.0"),
                    **details_kwargs,
                )

                created_count += 1

            self.stdout.write(f"  {order_date}  — order #{order.slaughter_order_no}  ({len(ANIMALS)} animals)")

        self.stdout.write(self.style.SUCCESS(f"\nDone. Created {created_count} animals across 7 days."))
        self.stdout.write(self.style.SUCCESS("Login credentials:"))
        self.stdout.write("  Manager:  manager  /  manager123   → /reporting/")
        self.stdout.write("  Client:   testclient  /  client123  → /reporting/portal/")
        self.stdout.write(f"\nDate range to use in reports:  {today - timedelta(days=6)}  →  {today}")
