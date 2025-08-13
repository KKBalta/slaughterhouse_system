from django.contrib import admin, messages
from .models import SlaughterOrder
from users.models import User, ClientProfile

@admin.register(SlaughterOrder)
class SlaughterOrderAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'status', 'order_datetime')
    list_filter = ('status', 'order_datetime')
    search_fields = ('client__company_name', 'client_name', 'client_phone')
    autocomplete_fields = ('client',)
    actions = ['convert_to_registered_client']

    @admin.action(description='Convert to Registered Client')
    def convert_to_registered_client(self, request, queryset):
        for order in queryset:
            if order.client:
                self.message_user(request, f"Order {order.id} is already linked to a registered client.", level=messages.WARNING)
                continue

            if not order.client_name or not order.client_phone:
                self.message_user(request, f"Order {order.id} is missing a client name or phone number.", level=messages.ERROR)
                continue

            # Create a new user
            username = order.client_name.lower().replace(' ', '') + order.client_phone[-4:]
            password = User.objects.make_random_password()
            user = User.objects.create_user(username=username, password=password, role=User.Role.CLIENT)

            # Create a client profile
            client_profile = ClientProfile.objects.create(
                user=user,
                account_type=ClientProfile.AccountType.INDIVIDUAL,
                contact_person=order.client_name,
                phone_number=order.client_phone
            )

            # Link this order and any other matching walk-in orders to the new profile
            SlaughterOrder.objects.filter(client_name=order.client_name, client_phone=order.client_phone).update(client=client_profile)

            self.message_user(request, f"Successfully converted {order.client_name}. Username: {username}, Password: {password}", level=messages.SUCCESS)

