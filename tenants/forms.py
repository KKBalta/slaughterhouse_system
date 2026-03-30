import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from tenants.models import Client, Domain


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
