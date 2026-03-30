from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import ClientProfile, User


class ClientUserCredentialsForm(forms.Form):
    """Staff edit of login identifiers and optional password reset for a client user."""

    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    new_password1 = forms.CharField(
        label="New password",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave blank to keep the current password.",
    )
    new_password2 = forms.CharField(
        label="Confirm new password",
        widget=forms.PasswordInput(render_value=False),
        required=False,
    )

    def __init__(self, *args, user_instance=None, require_password: bool = False, **kwargs):
        self.user_instance = user_instance
        self.require_password = require_password
        super().__init__(*args, **kwargs)
        if require_password:
            self.fields["new_password1"].required = True
            self.fields["new_password2"].required = True
            self.fields["new_password1"].help_text = ""
            self.fields["new_password1"].widget.attrs.setdefault(
                "autocomplete", "new-password"
            )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username__iexact=username)
        if self.user_instance and getattr(self.user_instance, "pk", None):
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data
        p1 = cleaned_data.get("new_password1") or ""
        p2 = cleaned_data.get("new_password2") or ""
        if self.require_password:
            if p1 != p2:
                self.add_error("new_password2", "The two password fields don't match.")
            elif len(p1) < 8:
                self.add_error("new_password1", "Password must be at least 8 characters.")
        elif p1 or p2:
            if p1 != p2:
                self.add_error("new_password2", "The two password fields don't match.")
            elif len(p1) < 8:
                self.add_error("new_password1", "Password must be at least 8 characters.")
        return cleaned_data


class UserRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ("email", "role")

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user and hasattr(user, "role") and user.role in [
            User.Role.OWNER,
            User.Role.ADMIN,
            User.Role.MANAGER,
        ]:
            self.fields["role"].choices = User.Role.choices
        else:
            allowed_roles = [
                (User.Role.CLIENT, "Client"),
                (User.Role.OPERATOR, "Operator"),
            ]
            self.fields["role"].choices = allowed_roles


class ClientProfileRegisterForm(forms.ModelForm):
    class Meta:
        model = ClientProfile
        fields = [
            "account_type",
            "contact_person",
            "phone_number",
            "address",
            "company_name",
            "tax_id",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company_name"].required = False
        self.fields["tax_id"].required = False
        self.fields["contact_person"].required = False

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data

        # ModelForm may supply TextChoices members or plain strings depending on Django version.
        account_type = cleaned_data.get("account_type")
        at_val = getattr(account_type, "value", account_type)

        def _strip(name: str) -> str | None:
            v = cleaned_data.get(name)
            if v is None:
                return None
            if isinstance(v, str):
                s = v.strip()
                cleaned_data[name] = s
                return s if s else None
            return v

        contact_person = _strip("contact_person")
        company_name = _strip("company_name")
        tax_id = _strip("tax_id")

        if at_val == ClientProfile.AccountType.ENTERPRISE.value:
            if not company_name:
                self.add_error("company_name", "Company name is required for enterprise accounts.")
            if not tax_id:
                self.add_error("tax_id", "Tax ID is required for enterprise accounts.")
            if not contact_person:
                self.add_error("contact_person", "Contact person is required for enterprise accounts.")
        else:
            # INDIVIDUAL (and any non-enterprise value)
            if not contact_person:
                self.add_error("contact_person", "Contact person is required for individual accounts.")
        return cleaned_data
