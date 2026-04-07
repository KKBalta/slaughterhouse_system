import os
import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from tenants.email_index import normalize_email
from tenants.models import LOGO_ALLOWED_EXTENSIONS, Client, Domain
from users.forms import PHONE_AREA_CODE_CHOICES, combine_phone_parts, split_phone_parts


class TenantLogoClearableFileInput(forms.ClearableFileInput):
    """Clearable image input with Tailwind-friendly template and copy for logo removal."""

    template_name = "tenants/widgets/tenant_logo_clearable.html"
    clear_checkbox_label = _("Remove current logo")
    initial_text = _("Current file")
    input_text = _("Replace with")


class TenantCompanyProfileForm(forms.ModelForm):
    """Editable company and regulatory fields for the current tenant (public `Client` row)."""

    contact_phone_area_code = forms.ChoiceField(
        choices=PHONE_AREA_CODE_CHOICES,
        initial="+90",
        required=False,
        label=_("Area code"),
        widget=forms.Select(
            attrs={
                "class": "modern-select",
                "title": _("Select country code: +90 for Turkey, +1 for USA/Canada"),
            }
        ),
    )

    class Meta:
        model = Client
        fields = [
            "name",
            "company_name",
            "company_full_name",
            "company_address",
            "registered_province_plaka",
            "license_no",
            "operation_no",
            "contact_email",
            "contact_phone",
            "logo",
            "printer_turkish_mode",
        ]
        widgets = {
            "company_address": forms.Textarea(attrs={"rows": 3}),
            "registered_province_plaka": forms.Select(
                attrs={
                    "class": "w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].label = _("Display name")
        self.fields["contact_phone"].max_length = 15
        self.fields["contact_phone"].widget.attrs.setdefault(
            "placeholder",
            _("Enter phone number"),
        )
        phone = ""
        if self.instance and getattr(self.instance, "pk", None):
            phone = (getattr(self.instance, "contact_phone", None) or "").strip()
        area, local = split_phone_parts(phone)
        self.fields["contact_phone_area_code"].initial = area
        self.fields["contact_phone"].initial = local
        self.fields["printer_turkish_mode"].widget = forms.Select(
            choices=[
                ("unicode", _("Unicode (recommended)")),
                ("ascii", _("ASCII (replace Turkish characters)")),
                ("codepage1254", _("Windows-1254")),
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

    def clean(self):
        cleaned = super().clean()
        if not cleaned:
            return cleaned
        cleaned["contact_phone"] = combine_phone_parts(
            cleaned.get("contact_phone_area_code"),
            cleaned.get("contact_phone"),
        )
        return cleaned


class CreateTenantForm(forms.Form):
    """Provision a new tenant: creates Client row + Domain + PostgreSQL schema."""

    schema_name = forms.SlugField(
        max_length=63,
        label=_("Schema name"),
        help_text=_("Lowercase letters, digits and hyphens only. Used as PostgreSQL schema and subdomain."),
    )
    name = forms.CharField(max_length=255, label=_("Display name"))
    domain = forms.CharField(
        max_length=253,
        required=False,
        label=_("Custom domain"),
        help_text=_("Leave blank to auto-generate {schema}.{base_domain}."),
    )
    company_name = forms.CharField(max_length=255, required=False, label=_("Company name"))
    contact_email = forms.EmailField(required=False, label=_("Contact email"))

    def clean_schema_name(self):
        value = self.cleaned_data["schema_name"].lower()
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,62}$", value):
            raise ValidationError(_("Use lowercase letters, digits and hyphens; must start with a letter or digit."))
        if value == "public":
            raise ValidationError(_('"public" is reserved.'))
        if Client.objects.filter(schema_name=value).exists():
            raise ValidationError(_('Schema "%(value)s" already exists.') % {"value": value})
        return value

    def clean_domain(self):
        value = self.cleaned_data.get("domain", "").strip().lower()
        if value and Domain.objects.filter(domain=value).exists():
            raise ValidationError(_('Domain "%(value)s" is already in use.') % {"value": value})
        return value


class PlatformAdminSetupForm(forms.Form):
    """Creates the very first PlatformAdmin account (first-run only)."""

    name = forms.CharField(max_length=255, label=_("Your name"))
    email = forms.EmailField(label=_("Email"))
    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Confirm password"), widget=forms.PasswordInput)

    def clean_email(self):
        from tenants.models import PlatformAdmin

        value = self.cleaned_data["email"].strip().lower()
        if PlatformAdmin.objects.filter(email__iexact=value).exists():
            raise ValidationError(_("An account with that email already exists."))
        return value

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("Passwords do not match."))
        return cleaned


class CreateTenantSuperuserForm(forms.Form):
    """
    Create an ADMIN-class user from platform admin (not OWNER — that role is only for
    the first user created when a tenant registration is approved).
    """

    username = forms.CharField(
        max_length=150,
        label=_("Username"),
        help_text=_("Sign in with this or your email on the tenant site (language-prefixed /tr/login/ etc.)."),
    )
    email = forms.EmailField(label=_("Email"))
    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Confirm password"), widget=forms.PasswordInput)
    account_kind = forms.ChoiceField(
        label=_("Account type"),
        choices=[
            (
                "app_admin",
                _("Tenant app admin (role ADMIN, full CarniTrack app access; not Django /admin/)"),
            ),
            (
                "django_superuser",
                _("Django superuser (role ADMIN plus Django /admin/ on this tenant host)"),
            ),
        ],
        initial="app_admin",
    )

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError(_("Passwords do not match."))
        return cleaned


class PlatformAdminAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = _("Email")
        self.fields["username"].widget = forms.EmailInput(
            attrs={
                "autocomplete": "username",
                "autofocus": True,
            }
        )


class PublicTenantRegistrationForm(forms.Form):
    company_name = forms.CharField(max_length=255, label=_("Company name"))
    owner_email = forms.EmailField(label=_("Owner email"))
    owner_password = forms.CharField(label=_("Password"), widget=forms.PasswordInput(render_value=True), strip=False)
    owner_password_confirm = forms.CharField(
        label=_("Confirm password"),
        widget=forms.PasswordInput(render_value=True),
        strip=False,
    )
    company_full_name = forms.CharField(max_length=255, required=False, label=_("Registered company name"))
    company_address = forms.CharField(
        max_length=500,
        required=False,
        label=_("Address"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    contact_phone = forms.CharField(max_length=64, required=False, label=_("Phone"))
    license_no = forms.CharField(
        max_length=64,
        required=False,
        label=_("İşletme onay no"),
        help_text=_("Government approval number on labels (ISLETME ONAY NO)."),
    )
    operation_no = forms.CharField(
        max_length=64,
        required=False,
        label=_("Vergi dairesi / işletme no (VD)"),
    )

    def clean_owner_email(self):
        return normalize_email(self.cleaned_data["owner_email"])

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("owner_password") or ""
        password_confirm = cleaned.get("owner_password_confirm") or ""
        if password and password_confirm and password != password_confirm:
            self.add_error("owner_password_confirm", _("Passwords do not match."))
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
