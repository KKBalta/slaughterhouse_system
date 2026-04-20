from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

from tenants.email_index import normalize_email, normalize_phone, validate_normalized_phone_length

from .models import ClientProfile, User
from .services import phone_lookup_candidates

# Same country codes as reception walk-in phone (SlaughterOrderForm).
PHONE_AREA_CODE_CHOICES = [
    ("+90", "+90"),
    ("+1", "+1"),
]


def split_phone_parts(phone_number: str | None) -> tuple[str, str]:
    phone = (phone_number or "").strip()
    if phone.startswith("+90"):
        return "+90", phone[3:]
    if phone.startswith("+1"):
        return "+1", phone[2:]
    return "+90", phone


def combine_phone_parts(phone_area_code: str | None, phone_number: str | None) -> str:
    raw_phone = (phone_number or "").strip()
    if not raw_phone:
        return ""
    if raw_phone.startswith("+"):
        return normalize_phone(raw_phone)
    area = (phone_area_code or "+90").strip() or "+90"
    return normalize_phone(f"{area}{raw_phone}")


class ClientUserCredentialsForm(forms.Form):
    """Staff edit of login identifiers and optional password reset for a client user."""

    username = forms.CharField(max_length=150, label=_("Username"))
    email = forms.EmailField(required=False, label=_("Email"))
    phone_area_code = forms.ChoiceField(
        choices=PHONE_AREA_CODE_CHOICES,
        initial="+90",
        required=False,
        label=_("Area code"),
        widget=forms.Select(
            attrs={"class": "modern-select", "title": _("Select country code: +90 for Turkey, +1 for USA/Canada")}
        ),
    )
    phone_number = forms.CharField(
        max_length=15,
        required=False,
        label=_("Phone number"),
        help_text=_("At least one of email or phone is required."),
    )
    new_password1 = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text=_("Leave blank to keep the current password."),
    )
    new_password2 = forms.CharField(
        label=_("Confirm new password"),
        widget=forms.PasswordInput(render_value=False),
        required=False,
    )

    def __init__(
        self,
        *args,
        user_instance=None,
        require_password: bool = False,
        require_contact: bool = True,
        **kwargs,
    ):
        self.user_instance = user_instance
        self.require_password = require_password
        self.require_contact = require_contact
        super().__init__(*args, **kwargs)
        if user_instance and getattr(user_instance, "username", ""):
            self.fields["username"].initial = user_instance.username
        if user_instance and getattr(user_instance, "email", ""):
            self.fields["email"].initial = user_instance.email
        if require_password:
            self.fields["new_password1"].required = False
            self.fields["new_password2"].required = False
            self.fields["new_password1"].help_text = _("Leave blank to assign a random password.")
            self.fields["new_password1"].widget.attrs.setdefault("autocomplete", "new-password")
        if user_instance and getattr(user_instance, "phone_number", ""):
            area, local = split_phone_parts(user_instance.phone_number)
            self.fields["phone_area_code"].initial = area
            self.fields["phone_number"].initial = local

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username__iexact=username)
        if self.user_instance and getattr(self.user_instance, "pk", None):
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("A user with that username already exists."))
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
        phone_number = combine_phone_parts(
            self.cleaned_data.get("phone_area_code"),
            self.cleaned_data.get("phone_number"),
        )
        if not phone_number:
            return ""
        validate_normalized_phone_length(phone_number)
        qs = User.objects.filter(phone_number__in=phone_lookup_candidates(phone_number))
        if self.user_instance and getattr(self.user_instance, "pk", None):
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("A user with that phone number already exists in this tenant."))
        return phone_number

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data
        email = (cleaned_data.get("email") or "").strip()
        phone = (cleaned_data.get("phone_number") or "").strip()
        if self.require_contact and not email and not phone:
            raise forms.ValidationError(_("At least one of email or phone number is required."))
        p1 = cleaned_data.get("new_password1") or ""
        p2 = cleaned_data.get("new_password2") or ""
        if self.require_password:
            if not self.user_instance and not p1 and not p2:
                pass
            elif p1 != p2:
                self.add_error("new_password2", _("The two password fields don't match."))
            elif len(p1) < 8:
                self.add_error("new_password1", _("Password must be at least 8 characters."))
        elif p1 or p2:
            if p1 != p2:
                self.add_error("new_password2", _("The two password fields don't match."))
            elif len(p1) < 8:
                self.add_error("new_password1", _("Password must be at least 8 characters."))
        return cleaned_data


class TenantManagedUserForm(ClientUserCredentialsForm):
    role = forms.ChoiceField(required=True, label=_("Role"))
    is_active = forms.BooleanField(required=False, initial=True, label=_("Active"))

    def __init__(self, *args, allowed_roles=(), user_instance=None, **kwargs):
        self.allowed_roles = tuple(allowed_roles)
        super().__init__(*args, user_instance=user_instance, **kwargs)
        self.fields["role"].choices = [(role, User.Role(role).label) for role in self.allowed_roles]
        if user_instance:
            self.fields["role"].initial = user_instance.role
            self.fields["is_active"].initial = user_instance.is_active

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role not in self.allowed_roles:
            raise forms.ValidationError(_("You cannot assign that role from this screen."))
        return role


class SelfServiceContactForm(forms.Form):
    email = forms.EmailField(required=False, label=_("Email"))
    phone_area_code = forms.ChoiceField(
        choices=PHONE_AREA_CODE_CHOICES,
        initial="+90",
        required=False,
        label=_("Area code"),
        widget=forms.Select(
            attrs={"class": "modern-select", "title": _("Select country code: +90 for Turkey, +1 for USA/Canada")}
        ),
    )
    phone_number = forms.CharField(
        max_length=15,
        required=False,
        label=_("Phone number"),
        help_text=_("At least one of email or phone is required."),
    )

    def __init__(self, *args, user_instance=None, **kwargs):
        self.user_instance = user_instance
        super().__init__(*args, **kwargs)
        if user_instance and getattr(user_instance, "email", ""):
            self.fields["email"].initial = user_instance.email
        if user_instance and getattr(user_instance, "phone_number", ""):
            area, local = split_phone_parts(user_instance.phone_number)
            self.fields["phone_area_code"].initial = area
            self.fields["phone_number"].initial = local

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
        phone_number = combine_phone_parts(
            self.cleaned_data.get("phone_area_code"),
            self.cleaned_data.get("phone_number"),
        )
        if not phone_number:
            return ""
        validate_normalized_phone_length(phone_number)
        qs = User.objects.filter(phone_number__in=phone_lookup_candidates(phone_number))
        if self.user_instance and getattr(self.user_instance, "pk", None):
            qs = qs.exclude(pk=self.user_instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("A user with that phone number already exists in this tenant."))
        return phone_number

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data
        email = (cleaned_data.get("email") or "").strip()
        phone = (cleaned_data.get("phone_number") or "").strip()
        if not email and not phone:
            raise forms.ValidationError(_("At least one of email or phone number is required."))
        return cleaned_data


class SelfServicePasswordForm(forms.Form):
    current_password = forms.CharField(
        label=_("Current password"),
        widget=forms.PasswordInput(render_value=False),
    )
    new_password1 = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput(render_value=False),
    )
    new_password2 = forms.CharField(
        label=_("Confirm new password"),
        widget=forms.PasswordInput(render_value=False),
    )

    def __init__(self, *args, user_instance=None, **kwargs):
        self.user_instance = user_instance
        super().__init__(*args, **kwargs)
        for field_name in ("current_password", "new_password1", "new_password2"):
            self.fields[field_name].widget.attrs.setdefault("autocomplete", "current-password")
        self.fields["new_password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["new_password2"].widget.attrs["autocomplete"] = "new-password"

    def clean_current_password(self):
        current_password = self.cleaned_data.get("current_password") or ""
        if self.user_instance is None or not self.user_instance.check_password(current_password):
            raise forms.ValidationError(_("Your current password was entered incorrectly."))
        return current_password

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data:
            return cleaned_data
        password1 = cleaned_data.get("new_password1") or ""
        password2 = cleaned_data.get("new_password2") or ""
        if password1 != password2:
            self.add_error("new_password2", _("The two password fields don't match."))
            return cleaned_data
        if password1:
            validate_password(password1, self.user_instance)
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
                (User.Role.CLIENT, _("Client")),
                (User.Role.OPERATOR, _("Operator")),
            ]
            self.fields["role"].choices = allowed_roles

    def clean_email(self):
        return normalize_email(self.cleaned_data.get("email"))

    def clean_phone_number(self):
        phone = normalize_phone(self.cleaned_data.get("phone_number"))
        if phone:
            validate_normalized_phone_length(phone)
        return phone

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
            "default_destination",
            "company_name",
            "tax_id",
        ]

    def __init__(self, *args, **kwargs):
        self.allow_existing_phone_user = kwargs.pop("allow_existing_phone_user", False)
        self.registered_phone_user = None
        super().__init__(*args, **kwargs)
        self.fields["company_name"].required = False
        self.fields["tax_id"].required = False
        self.fields["contact_person"].required = False
        self.fields["address"].required = False
        self.fields["default_destination"].required = False
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
        self.registered_phone_user = None
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

        phone_number = cleaned_data.get("phone_number") or ""
        if phone_number:
            try:
                validate_normalized_phone_length(phone_number)
            except forms.ValidationError as exc:
                self.add_error("phone_number", exc)
            else:
                phone_candidates = phone_lookup_candidates(phone_number)
                qs = User.objects.filter(phone_number__in=phone_candidates)
                linked_user = getattr(getattr(self, "instance", None), "user", None)
                if linked_user and getattr(linked_user, "pk", None):
                    qs = qs.exclude(pk=linked_user.pk)
                self.registered_phone_user = qs.first()
                if self.registered_phone_user is not None and not self.allow_existing_phone_user:
                    self.add_error("phone_number", _("A user with that phone number already exists in this tenant."))

                if self.registered_phone_user is None or self.allow_existing_phone_user:
                    profile_qs = ClientProfile.objects.filter(phone_number__in=phone_candidates)
                    inst = getattr(self, "instance", None)
                    if inst and getattr(inst, "pk", None):
                        profile_qs = profile_qs.exclude(pk=inst.pk)
                    if profile_qs.exists():
                        self.add_error("phone_number", _("A client profile with that phone number already exists."))

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
        address = _strip("address") or ""
        _strip("default_destination")
        company_name = _strip("company_name")
        tax_id = _strip("tax_id")
        cleaned_data["address"] = address

        if at_val == ClientProfile.AccountType.ENTERPRISE.value:
            if not company_name:
                self.add_error("company_name", _("Company name is required for enterprise accounts."))
            if not tax_id:
                self.add_error("tax_id", _("Tax ID is required for enterprise accounts."))
            if not contact_person:
                self.add_error("contact_person", _("Contact person is required for enterprise accounts."))
            if not address:
                self.add_error("address", _("Address is required for enterprise accounts."))
        elif at_val == ClientProfile.AccountType.INDIVIDUAL.value:
            if not contact_person:
                self.add_error("contact_person", _("Contact person is required for individual accounts."))
            if not address:
                self.add_error("address", _("Address is required for individual accounts."))
        else:
            if not contact_person:
                self.add_error("contact_person", _("Name is required for walk-in accounts."))
        return cleaned_data
