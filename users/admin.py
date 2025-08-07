from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, ClientProfile

# This inline allows the ClientProfile to be edited directly
# from the User change page in the admin.
class ClientProfileInline(admin.StackedInline):
    model = ClientProfile
    can_delete = False
    verbose_name_plural = 'Client Profile'
    fk_name = 'user'

# Define a new User admin
class CustomUserAdmin(UserAdmin):
    inlines = (ClientProfileInline, )
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_superuser', 'groups')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('username',)

# Define a separate admin for ClientProfile to enable searching
@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'account_type', 'phone_number')
    search_fields = ('company_name', 'contact_person', 'user__username', 'user__first_name', 'user__last_name')
    list_filter = ('account_type',)

# Register the new CustomUserAdmin
admin.site.register(User, CustomUserAdmin)