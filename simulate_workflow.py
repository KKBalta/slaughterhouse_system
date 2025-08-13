from core.models import ServicePackage
from users.models import User, ClientProfile
from reception.models import SlaughterOrder
from processing.models import Animal, WeightLog
from django.utils import timezone

# 1. Create a ServicePackage
service_package, created = ServicePackage.objects.get_or_create(
    name="Full Processing",
    defaults={
        "description": "Includes slaughter, disassembly, and delivery.",
        "includes_disassembly": True,
        "includes_delivery": True
    }
)
print("ServicePackage: {} (Created: {})".format(service_package.name, created))

# 2. Create a User (Admin) - if not already exists
admin_user, created = User.objects.get_or_create(
    username="admin",
    defaults={
        "email": "admin@example.com",
        "is_staff": True,
        "is_superuser": True,
        "role": User.Role.ADMIN
    }
)
if created:
    admin_user.set_password("adminpassword") # Set a default password
    admin_user.save()
print("Admin User: {} (Created: {})".format(admin_user.username, created))

# 3. Create a ClientProfile
client_profile, created = ClientProfile.objects.get_or_create(
    user=admin_user, # Link to the admin user for simplicity, or create a new client user
    defaults={
        "account_type": ClientProfile.AccountType.ENTERPRISE,
        "company_name": "Acme Meats Inc.",
        "contact_person": "John Doe",
        "phone_number": "555-1234",
        "address": "123 Meat St, Anytown",
        "tax_id": "TAX12345"
    }
)
print("ClientProfile: {} (Created: {})".format(client_profile.company_name, created))

# 4. Create a SlaughterOrder
slaughter_order, created = SlaughterOrder.objects.get_or_create(
    client=client_profile,
    order_datetime=timezone.now(),
    defaults={
        "service_package": service_package,
        "status": SlaughterOrder.Status.PENDING
    }
)
print("SlaughterOrder: {} (Created: {})".format(slaughter_order.id, created))

# 5. Create an Animal
animal, created = Animal.objects.get_or_create(
    slaughter_order=slaughter_order,
    identification_tag="CATTLE-001",
    defaults={
        "animal_type": "cattle",
        "status": "received" # Initial status
    }
)
print("Animal: {} (Created: {})".format(animal.identification_tag, created))

# 6. Log a WeightLog for the animal (Live Weight)
weight_log, created = WeightLog.objects.get_or_create(
    animal=animal,
    weight_type="Live",
    defaults={
        "weight": 500.00,
        "log_date": timezone.now()
    }
)
print("WeightLog (Live): {} kg (Created: {})".format(weight_log.weight, created))

# 7. Transition the Animal's status
print("Animal status before transition: {}".format(animal.status))
if animal.status == 'received':
    animal.perform_slaughter()
    animal.save()
    print("Animal status after slaughter: {}".format(animal.status))

if animal.status == 'slaughtered':
    animal.prepare_carcass()
    animal.save()
    print("Animal status after carcass prep: {}".format(animal.status))

if animal.status == 'carcass_ready' and animal.slaughter_order.service_package.includes_disassembly:
    animal.perform_disassembly()
    animal.save()
    print("Animal status after disassembly: {}".format(animal.status))

print("\nWorkflow simulation complete.")
