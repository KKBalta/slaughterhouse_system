from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from tenants.models import Client, Domain, EmailTenantMembership, PlatformAdmin, TenantRegistrationRequest


@admin.register(TenantRegistrationRequest)
class TenantRegistrationRequestAdmin(admin.ModelAdmin):
    list_display = ("company_name", "derived_schema_name", "owner_email", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("company_name", "derived_schema_name", "owner_email")
    readonly_fields = ("id", "owner_password_hash", "status_token_hash", "created_at", "updated_at")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("schema_name", "slug", "name", "company_name", "license_no", "is_active", "created_on")
    search_fields = ("schema_name", "slug", "name", "company_name", "license_no")
    # Default; overridden on change so slug↔schema_name prepop does not touch form["schema_name"] when readonly
    prepopulated_fields = {"slug": ("schema_name",)}
    fieldsets = (
        (
            _("Identity"),
            {"fields": ("schema_name", "slug", "name", "is_active", "created_on")},
        ),
        (
            _("Labels and reports — company block"),
            {
                "fields": (
                    "company_name",
                    "company_full_name",
                    "company_address",
                    "registered_province_plaka",
                    "license_no",
                    "operation_no",
                ),
                "description": _(
                    "İşletme onay no and VD numbers are printed on meat labels; keep them aligned with official registrations."
                ),
            },
        ),
        (
            _("Branding and contact"),
            {"fields": ("logo", "contact_email", "contact_phone")},
        ),
        (
            _("Locale and printing"),
            {"fields": ("printer_turkish_mode", "timezone", "language_code")},
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        """Lock schema after creation; provisioning normally creates tenants outside this admin."""
        ro = ["created_on"]
        if obj is not None:
            ro = ["schema_name", "created_on"]
        return ro

    def get_prepopulated_fields(self, request, obj=None):
        """
        On change, `schema_name` is readonly and omitted from the ModelForm. Prepopulated slug
        dependencies still access `form['schema_name']` during AdminForm init, which raises KeyError.
        Only prepopulate slug from schema_name when adding a new Client.
        """
        if obj is not None:
            return {}
        return {"slug": ("schema_name",)}


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    search_fields = ("domain",)


@admin.register(EmailTenantMembership)
class EmailTenantMembershipAdmin(admin.ModelAdmin):
    list_display = ("email_normalized", "tenant", "tenant_user_id", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("email_normalized", "tenant__schema_name")
    raw_id_fields = ("tenant",)
    readonly_fields = ("created_at", "updated_at")


class PlatformAdminForm(forms.ModelForm):
    """Optional password change on edit; required on create."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, required=False)
    password2 = forms.CharField(label="Password confirmation", widget=forms.PasswordInput, required=False)

    class Meta:
        model = PlatformAdmin
        fields = ("email", "name", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not kwargs.get("instance"):
            self.fields["password1"].required = True
            self.fields["password2"].required = True

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 or p2:
            if p1 != p2:
                raise forms.ValidationError("The two password fields do not match.")
        elif not self.instance.pk:
            raise forms.ValidationError("Password is required for new platform admins.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        pwd = self.cleaned_data.get("password1")
        if pwd:
            user.set_password(pwd)
        if commit:
            user.save()
        return user


@admin.register(PlatformAdmin)
class PlatformAdminAdmin(admin.ModelAdmin):
    form = PlatformAdminForm
    list_display = ("email", "name", "is_active", "created_on", "last_login")
    search_fields = ("email", "name")
    readonly_fields = ("created_on", "last_login")
    fieldsets = (
        (None, {"fields": ("email", "name", "password1", "password2", "is_active")}),
        ("Metadata", {"fields": ("created_on", "last_login")}),
    )
