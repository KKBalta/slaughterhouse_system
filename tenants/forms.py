import os
import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from tenants.email_index import normalize_email
from tenants.models import LOGO_ALLOWED_EXTENSIONS, Client, Domain


class TenantLogoClearableFileInput(forms.ClearableFileInput):
    """Clearable image input with Tailwind-friendly template and copy for logo removal."""

    template_name = "tenants/widgets/tenant_logo_clearable.html"
    clear_checkbox_label = _("Remove current logo")
    initial_text = _("Current file")
    input_text = _("Replace with")


class TenantCompanyProfileForm(forms.ModelForm):
    """Editable company and regulatory fields for the current tenant (public `Client` row)."""

    class Meta:
        model = Client
        fields = [
            "name",
            "company_name",
            "company_full_name",
            "company_address",
            "license_no",
            "operation_no",
            "contact_email",
            "contact_phone",
            "logo",
            "printer_turkish_mode",
        ]
        widgets = {
            "company_address": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["printer_turkish_mode"].widget = forms.Select(
            choices=[
                ("unicode", "Unicode (recommended)"),
                ("ascii", "ASCII (replace Turkish characters)"),
                ("codepage1254", "Windows-1254"),
            ]
        )
        self.fields["logo"].widget = TenantLogoClearableFileInput(
            attrs={
                "class": (
                    "block w-full text-sm text-gray-500 file:mr-4 file:rounded-md file:border-0 "
                    "file:bg-blue-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-blue-700"
                ),
                "accept": "image/png,image/jpeg,image/webp,image/gif",
            }
        )

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        if logo in (None, False):
            return logo
        name = getattr(logo, "name", "") or ""
        ext = os.path.splitext(name)[1].lower()
        if ext not in LOGO_ALLOWED_EXTENSIONS:
            raise ValidationError(
                _("Please upload a PNG, JPEG, WebP, or GIF image."),
                code="invalid_logo_type",
            )
        return logo


class CreateTenantForm(forms.Form):
    """Provision a new tenant: creates Client row + Domain + PostgreSQL schema."""

    schema_name = forms.SlugField(
        max_length=63,
        label="Schema name",
        help_text="Lowercase letters, digits and hyphens only. Used as PostgreSQL schema and subdomain.",
    )
    name = forms.CharField(max_length=255, label="Display name")
    domain = forms.CharField(
        max_length=253,
        required=False,
        label="Custom domain",
        help_text="Leave blank to auto-generate {schema}.{base_domain}.",
    )
    company_name = forms.CharField(max_length=255, required=False, label="Company name")
    contact_email = forms.EmailField(required=False, label="Contact email")

    def clean_schema_name(self):
        value = self.cleaned_data["schema_name"].lower()
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,62}$", value):
            raise ValidationError("Use lowercase letters, digits and hyphens; must start with a letter or digit.")
        if value == "public":
            raise ValidationError('"public" is reserved.')
        if Client.objects.filter(schema_name=value).exists():
            raise ValidationError(f'Schema "{value}" already exists.')
        return value

    def clean_domain(self):
        value = self.cleaned_data.get("domain", "").strip().lower()
        if value and Domain.objects.filter(domain=value).exists():
            raise ValidationError(f'Domain "{value}" is already in use.')
        return value


class PlatformAdminSetupForm(forms.Form):
    """Creates the very first PlatformAdmin account (first-run only)."""

    name = forms.CharField(max_length=255, label="Your name")
    email = forms.EmailField(label="Email")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def clean_email(self):
        from tenants.models import PlatformAdmin

        value = self.cleaned_data["email"].strip().lower()
        if PlatformAdmin.objects.filter(email__iexact=value).exists():
            raise ValidationError("An account with that email already exists.")
        return value

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Passwords do not match.")
        return cleaned


class CreateTenantSuperuserForm(forms.Form):
    """
    Create an ADMIN-class user from platform admin (not OWNER — that role is only for
    the first user created when a tenant registration is approved).
    """

    username = forms.CharField(
        max_length=150,
        label="Username",
        help_text="Sign in with this or your email on the tenant site (language-prefixed /tr/login/ etc.).",
    )
    email = forms.EmailField(label="Email")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)
    account_kind = forms.ChoiceField(
        label="Account type",
        choices=[
            (
                "app_admin",
                "Tenant app admin (role ADMIN — full CarniTrack app access; not Django /admin/)",
            ),
            (
                "django_superuser",
                "Django superuser (role ADMIN + Django /admin/ on this tenant host)",
            ),
        ],
        initial="app_admin",
    )

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Passwords do not match.")
        return cleaned


class PlatformAdminAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget = forms.EmailInput(
            attrs={
                "autocomplete": "username",
                "autofocus": True,
            }
        )


class PublicTenantRegistrationForm(forms.Form):
    company_name = forms.CharField(max_length=255, label="Company name")
    owner_email = forms.EmailField(label="Owner email")
    owner_password = forms.CharField(label="Password", widget=forms.PasswordInput(render_value=True), strip=False)
    owner_password_confirm = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(render_value=True),
        strip=False,
    )
    company_full_name = forms.CharField(max_length=255, required=False, label="Registered company name")
    company_address = forms.CharField(
        max_length=500,
        required=False,
        label="Address",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    contact_phone = forms.CharField(max_length=64, required=False, label="Phone")
    license_no = forms.CharField(
        max_length=64,
        required=False,
        label="İşletme onay no",
        help_text="Government approval number on labels (ISLETME ONAY NO).",
    )
    operation_no = forms.CharField(
        max_length=64,
        required=False,
        label="Vergi dairesi / işletme no (VD)",
    )

    def clean_owner_email(self):
        return normalize_email(self.cleaned_data["owner_email"])

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("owner_password") or ""
        password_confirm = cleaned.get("owner_password_confirm") or ""
        if password and password_confirm and password != password_confirm:
            self.add_error("owner_password_confirm", "Passwords do not match.")
        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                self.add_error("owner_password", exc)
        return cleaned

    def registration_kwargs(self) -> dict[str, str]:
        cleaned = self.cleaned_data
        return {
            "company_name": (cleaned.get("company_name") or "").strip(),
            "company_full_name": (cleaned.get("company_full_name") or "").strip(),
            "company_address": (cleaned.get("company_address") or "").strip(),
            "license_no": (cleaned.get("license_no") or "").strip(),
            "operation_no": (cleaned.get("operation_no") or "").strip(),
            "contact_phone": (cleaned.get("contact_phone") or "").strip(),
            "owner_email": cleaned.get("owner_email") or "",
            "owner_password": cleaned.get("owner_password") or "",
        }
