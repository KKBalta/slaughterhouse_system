from core.models import ServicePackage
from users.models import User, ClientProfile
from reception.models import SlaughterOrder
from processing.models import Animal
from inventory.models import Carcass, MeatCut, Offal, ByProduct, StorageLocation
from labeling.models import LabelTemplate
from labeling.utils import generate_label_content
from django.utils import timezone
from datetime import date

# Setup (similar to test setUp)
user, _ = User.objects.get_or_create(username='testuser', defaults={'email': 'test@example.com', 'is_staff': True, 'is_superuser': True, 'role': User.Role.ADMIN})
user.set_password('testpassword')
user.save()
client_profile, _ = ClientProfile.objects.get_or_create(user=user, defaults={'account_type': ClientProfile.AccountType.INDIVIDUAL, 'phone_number': '1234567890', 'address': 'Test Address'})
service_package, _ = ServicePackage.objects.get_or_create(name='Full Processing', defaults={'includes_disassembly': True, 'includes_delivery': True})
order, _ = SlaughterOrder.objects.get_or_create(client=client_profile, order_datetime=timezone.now().date(), defaults={'service_package': service_package})
storage_location, _ = StorageLocation.objects.get_or_create(name='Freezer 1', defaults={'location_type': 'freezer'})

# Create an Animal and Carcass
animal, _ = Animal.objects.get_or_create(slaughter_order=order, animal_type='cattle', identification_tag='TEST-CATTLE-001')
carcass, _ = Carcass.objects.get_or_create(animal=animal, defaults={'hot_carcass_weight': 300.0, 'status': 'chilling', 'disposition': 'for_sale', 'storage_location': storage_location})

# Create a MeatCut
meat_cut, _ = MeatCut.objects.get_or_create(carcass=carcass, cut_type='RIBEYE', defaults={'weight': 10.5, 'disposition': 'for_sale', 'storage_location': storage_location})

# Create an Offal
offal, _ = Offal.objects.get_or_create(animal=animal, offal_type='LIVER', defaults={'weight': 2.0, 'disposition': 'for_sale', 'storage_location': storage_location})

# Create a ByProduct
by_product, _ = ByProduct.objects.get_or_create(animal=animal, byproduct_type='SKIN', defaults={'weight': 20.0, 'disposition': 'for_sale', 'storage_location': storage_location})

# Create LabelTemplates
carcass_template, _ = LabelTemplate.objects.get_or_create(name='Carcass Label', defaults={'template_data': ['identification_tag', 'hot_carcass_weight', 'status', 'disposition'], 'target_item_type': 'carcass'})
meat_cut_template, _ = LabelTemplate.objects.get_or_create(name='Meat Cut Label', defaults={'template_data': ['cut_type', 'weight', 'disposition'], 'target_item_type': 'meat_cut'})
offal_template, _ = LabelTemplate.objects.get_or_create(name='Offal Label', defaults={'template_data': ['offal_type', 'weight', 'disposition'], 'target_item_type': 'offal'})
by_product_template, _ = LabelTemplate.objects.get_or_create(name='ByProduct Label', defaults={'template_data': ['byproduct_type', 'weight', 'disposition'], 'target_item_type': 'by_product'})

# Test label generation
print("\n--- Generated Label Content ---")
print("Carcass Label:", generate_label_content('carcass', str(carcass.id), carcass_template))
print("Meat Cut Label:", generate_label_content('meat_cut', str(meat_cut.id), meat_cut_template))
print("Offal Label:", generate_label_content('offal', str(offal.id), offal_template))
print("ByProduct Label:", generate_label_content('by_product', str(by_product.id), by_product_template))
