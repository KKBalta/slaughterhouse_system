from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from tenants.email_index import normalize_email, normalize_phone

from .models import ClientProfile, User

# Same country codes as reception walk-in phone (SlaughterOrderForm).
PHONE_AREA_CODE_CHOICES = [
    ("+90", "+90"),
    ("+1", "+1"),
]


class ClientUserCredentialsForm(forms.Form):
    """Staff edit of login identifiers and optional password reset for a client user."""

    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    phone_number = forms.CharField(
        max_length=20,
        required=False,
        label=_("Phone number"),
        help_text=_("At least one of email or phone is required."),
    )
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
        if user_instance and getattr(user_instance, "email", ""):
            self.fields["email"].initial = user_instance.email
        if require_password:
            self.fields["new_password1"].required = True
            self.fields["new_password2"].required = True
            self.fields["new_password1"].help_text = ""
            self.fields["new_password1"].widget.attrs.setdefault("autocomplete", "new-password")
        if user_instance and getattr(user_instance, "phone_number", ""):
            self.fields["phone_number"].initial = user_instance.phone_number

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username__iexact=username)
        if self.user_instance and getattr(self.user_instance, "pk", None):
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get("email"))
        if not email:
            return ""
        qs = User.objects.filter(email__iexact=email)
        if self.user_instance and getattr(self.user_instance, "pk", None):
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("A user with that email already exists in this tenant."))
        return email

    def clean_phone_number(self):
        return normalize_phone(self.cleaned_data.get("phone_number"))

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data
        # At least one of email or phone required.
        email = (cleaned_data.get("email") or "").strip()
        phone = (cleaned_data.get("phone_number") or "").strip()
        if not email and not phone:
            raise forms.ValidationError(_("At least one of email or phone number is required."))
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
        fields = UserCreationForm.Meta.fields + ("email", "phone_number", "role")

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["email"].required = False
        self.fields["phone_number"].required = False
        if (
            user
            and hasattr(user, "role")
            and user.role
            in [
                User.Role.OWNER,
                User.Role.ADMIN,
                User.Role.MANAGER,
            ]
        ):
            self.fields["role"].choices = User.Role.choices
        else:
            allowed_roles = [
                (User.Role.CLIENT, "Client"),
                (User.Role.OPERATOR, "Operator"),
            ]
            self.fields["role"].choices = allowed_roles

    def clean_email(self):
        return normalize_email(self.cleaned_data.get("email"))

    def clean_phone_number(self):
        return normalize_phone(self.cleaned_data.get("phone_number"))

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data
        email = (cleaned_data.get("email") or "").strip()
        phone = (cleaned_data.get("phone_number") or "").strip()
        if not email and not phone:
            raise forms.ValidationError(_("At least one of email or phone number is required."))
        return cleaned_data


class ClientProfileRegisterForm(forms.ModelForm):
    email = forms.EmailField(
        required=False,
        label=_("Email"),
        help_text=_("At least one of email or phone is required."),
    )
    phone_area_code = forms.ChoiceField(
        choices=PHONE_AREA_CODE_CHOICES,
        initial="+90",
        required=False,
        label=_("Area code"),
        widget=forms.Select(
            attrs={"class": "modern-select", "title": _("Select country code: +90 for Turkey, +1 for USA/Canada")}
        ),
    )

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
        self.fields["phone_number"].required = False
        self.fields["phone_number"].max_length = 15
        self.fields["phone_number"].widget = forms.TextInput(
            attrs={
                "class": "flex-1 px-3 py-2 border border-l-0 border-gray-300 rounded-r-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Enter phone number"),
                "autocomplete": "tel-national",
            }
        )
        self.fields["phone_number"].label = _("Phone number")
        self.fields["phone_number"].help_text = _("At least one of email or phone is required.")

        inst = getattr(self, "instance", None)
        if inst and getattr(getattr(inst, "user", None), "email", ""):
            self.fields["email"].initial = inst.user.email
        if inst and getattr(inst, "pk", None) and inst.phone_number:
            phone = inst.phone_number.strip()
            if phone.startswith("+90"):
                self.fields["phone_area_code"].initial = "+90"
                self.fields["phone_number"].initial = phone[3:]
            elif phone.startswith("+1"):
                self.fields["phone_area_code"].initial = "+1"
                self.fields["phone_number"].initial = phone[2:]
            else:
                self.fields["phone_number"].initial = phone

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get("email"))
        if not email:
            return ""
        qs = User.objects.filter(email__iexact=email)
        linked_user = getattr(getattr(self, "instance", None), "user", None)
        if linked_user and getattr(linked_user, "pk", None):
            qs = qs.exclude(pk=linked_user.pk)
        if qs.exists():
            raise forms.ValidationError(_("A user with that email already exists in this tenant."))
        return email

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data

        phone = cleaned_data.get("phone_number")
        area = cleaned_data.get("phone_area_code") or "+90"
        if phone is not None:
            p = phone.strip()
            if p.startswith("+"):
                cleaned_data["phone_number"] = normalize_phone(p)
            elif p:
                cleaned_data["phone_number"] = normalize_phone(f"{area}{p}")
            else:
                cleaned_data["phone_number"] = ""
        if not cleaned_data.get("email") and not cleaned_data.get("phone_number"):
            raise forms.ValidationError(_("At least one of email or phone number is required."))

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
