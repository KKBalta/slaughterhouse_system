from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from processing.models import Animal, CattleDetails, SheepDetails, WeightLog
from reception.models import ClientProfile, ServicePackage, SlaughterOrder

User = get_user_model()


class Command(BaseCommand):
    help = "Create test data for reporting"

    def handle(self, *args, **options):
        # Create test user if not exists
        user, created = User.objects.get_or_create(
            username="testuser", defaults={"email": "test@example.com", "first_name": "Test", "last_name": "User"}
        )
        if created:
            user.set_password("testpass123")
            user.save()
            self.stdout.write(self.style.SUCCESS("Created test user"))

        # Create client profile
        client_profile, created = ClientProfile.objects.get_or_create(
            user=user,
            defaults={
                "company_name": "Test Client Company",
                "phone": "+90 555 123 4567",
                "address": "Test Address, Test City",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created client profile"))

        # Create service package
        service_package, created = ServicePackage.objects.get_or_create(
            name="Test Package",
            defaults={"includes_disassembly": True, "includes_delivery": True, "base_price": Decimal("100.00")},
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created service package"))

        # Create slaughter orders for the last 7 days
        today = timezone.now().date()
        for i in range(7):
            order_date = today - timedelta(days=i)

            # Create slaughter order
            order, created = SlaughterOrder.objects.get_or_create(
                client=client_profile,
                service_package=service_package,
                order_datetime=timezone.make_aware(datetime.combine(order_date, datetime.min.time())),
                defaults={
                    "status": "COMPLETED",
                    "client_name": f"Test Client {i + 1}",
                    "destination": f"Test Destination {i + 1}",
                },
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f"Created slaughter order for {order_date}"))

                # Create animals for this order
                animal_types = ["cattle", "sheep", "goat", "lamb"]
                for j, animal_type in enumerate(animal_types):
                    # Create animal
                    animal = Animal.objects.create(
                        slaughter_order=order,
                        animal_type=animal_type,
                        identification_tag=f"{animal_type.upper()}-{order_date.strftime('%Y%m%d')}-{j + 1:03d}",
                        slaughter_date=timezone.make_aware(datetime.combine(order_date, datetime.min.time())),
                        status="hot_carcass",  # Use hot_carcass status so it appears in reports
                        leather_weight_kg=Decimal(f"{10 + j * 5}.00"),
                    )

                    # Create weight logs
                    WeightLog.objects.create(
                        animal=animal,
                        log_date=timezone.make_aware(datetime.combine(order_date, datetime.min.time())),
                        weight=Decimal(f"{200 + j * 50}.00"),
                        weight_type="live_weight",
                        is_group_weight=False,
                    )

                    WeightLog.objects.create(
                        animal=animal,
                        log_date=timezone.make_aware(datetime.combine(order_date, datetime.min.time())),
                        weight=Decimal(f"{120 + j * 30}.00"),
                        weight_type="hot_carcass_weight",
                        is_group_weight=False,
                    )

                    # Create animal details
                    if animal_type == "cattle":
                        CattleDetails.objects.create(
                            animal=animal, breed="Holstein", sakatat_status=1.0, bowels_status=1.0
                        )
                    elif animal_type in ["sheep", "lamb"]:
                        SheepDetails.objects.create(
                            animal=animal, breed="Merino", sakatat_status=1.0, bowels_status=1.0
                        )

                    self.stdout.write(self.style.SUCCESS(f"Created {animal_type} animal for {order_date}"))

        self.stdout.write(self.style.SUCCESS("Test data creation completed!"))
        self.stdout.write(
            self.style.SUCCESS(f"Created data for the last 7 days (from {today - timedelta(days=6)} to {today})")
        )
        self.stdout.write(self.style.SUCCESS("You can now generate reports for any date in this range."))
