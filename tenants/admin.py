from django import forms
from django.contrib import admin

from tenants.models import Client, Domain, PlatformAdmin


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("schema_name", "slug", "name", "company_name", "is_active", "created_on")
    search_fields = ("schema_name", "slug", "name", "company_name")
    prepopulated_fields = {"slug": ("schema_name",)}


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    search_fields = ("domain",)


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
