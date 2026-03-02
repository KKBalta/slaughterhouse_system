from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import ClientProfile, User


class UserRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ("email", "role")

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user and hasattr(user, "role") and user.role in [User.Role.ADMIN, User.Role.MANAGER]:
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
        account_type = cleaned_data.get("account_type")
        if account_type == ClientProfile.AccountType.ENTERPRISE:
            if not cleaned_data.get("company_name"):
                self.add_error("company_name", "Company name is required for enterprise accounts.")
            if not cleaned_data.get("tax_id"):
                self.add_error("tax_id", "Tax ID is required for enterprise accounts.")
            if not cleaned_data.get("contact_person"):
                self.add_error("contact_person", "Contact person is required for enterprise accounts.")
        else:
            if not cleaned_data.get("contact_person"):
                self.add_error("contact_person", "Contact person is required for individual accounts.")
        return cleaned_data
