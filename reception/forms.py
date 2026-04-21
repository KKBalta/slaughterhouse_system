from django import forms
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from processing.models import Animal
from tenants.email_index import normalize_phone, validate_normalized_phone_length

from .models import ServicePackage, SlaughterOrder
from .services import (
    can_edit_order_datetime,
    can_edit_order_destination,
    can_edit_order_service_package,
    can_reassign_order_client,
)


def _normalize_walk_in_client_phone(area_code: str | None, phone: str | None) -> str:
    """Combine area + local digits, normalize to +digits, validate supported lengths."""
    raw = (phone or "").strip()
    if not raw:
        return ""
    area = (area_code or "+90").strip() or "+90"
    combined = raw if raw.startswith("+") else f"{area}{raw}"
    normalized = normalize_phone(combined)
    validate_normalized_phone_length(normalized)
    return normalized


class SlaughterOrderForm(forms.ModelForm):
    # Custom client search field
    client_search = forms.CharField(
        max_length=255,
        required=False,
        label=_("Search client"),
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Search by name, phone, or destination..."),
                "id": "client-search",
                "autocomplete": "off",
            }
        ),
    )

    # Hidden field to store selected client ID
    client_id = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "client-id"}))

    client_name = forms.CharField(
        max_length=255,
        required=False,
        label=_("Walk-in Client Name"),
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Enter client name for walk-in customers"),
            }
        ),
    )

    # Phone area code selection
    AREA_CODE_CHOICES = [
        ("+90", "+90"),
        ("+1", "+1"),
    ]

    client_phone_area_code = forms.ChoiceField(
        choices=AREA_CODE_CHOICES,
        initial="+90",
        required=False,
        label=_("Area Code"),
        widget=forms.Select(
            attrs={"class": "modern-select", "title": _("Select country code: +90 for Turkey, +1 for USA/Canada")}
        ),
    )

    client_phone = forms.CharField(
        max_length=15,
        required=False,
        label=_("Walk-in Client Phone"),
        help_text=_(
            "Optional — leave blank if you're in a rush. Without a phone we cannot save this walk-in as a reusable client for future orders or follow-up."
        ),
        widget=forms.TextInput(
            attrs={
                "class": "flex-1 px-3 py-2 border border-l-0 border-gray-300 rounded-r-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Enter phone number"),
            }
        ),
    )

    destination_search = forms.CharField(
        max_length=255,
        required=False,
        label=_("Destination Client"),
        help_text=_("Type to search destination clients. Select one to keep it linked for future orders."),
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Type destination client name to search..."),
                "id": "destination-search",
                "autocomplete": "off",
            }
        ),
    )
    destination_client_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "destination-client-id"}),
    )

    class Meta:
        model = SlaughterOrder
        fields = ["service_package", "order_datetime", "destination"]
        labels = {
            "service_package": _("Service package"),
            "order_datetime": _("Order datetime"),
            "destination": _("Destination"),
        }
        help_texts = {
            "service_package": _("The service package selected for this order."),
            "destination": _("Hidden snapshot of the selected destination client."),
        }
        widgets = {
            "order_datetime": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                }
            ),
            "destination": forms.HiddenInput(
                attrs={
                    "id": "destination-text",
                }
            ),
            "service_package": forms.Select(attrs={"class": "modern-select-full"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        sp = self.fields["service_package"]
        sp.queryset = ServicePackage.objects.filter(is_active=True)
        sp.empty_label = _("Select service package")
        sp.label_from_instance = lambda obj: obj.localized_name()
        # Model allows null; orders must still pick a package at intake.
        sp.required = True
        msgs = dict(sp.error_messages)
        msgs["required"] = _("Please choose a service package before creating the order.")
        msgs["invalid_choice"] = _("Select a valid service package.")
        sp.error_messages = msgs

    def clean(self):
        cleaned_data = super().clean()
        client_id = (cleaned_data.get("client_id") or "").strip()
        client_name = (cleaned_data.get("client_name") or "").strip()
        cleaned_data["client_id"] = client_id
        cleaned_data["client_name"] = client_name

        if not client_id and not client_name:
            raise forms.ValidationError(
                _("An order must be linked to either a saved client from search or a walk-in client name.")
            )

        if client_id and client_name:
            raise forms.ValidationError(_("Please provide either a client from search or walk-in fields, not both."))

        # Phone is optional for walk-ins; validate format only when one is provided.
        phone = (cleaned_data.get("client_phone") or "").strip()
        if phone:
            area_code = cleaned_data.get("client_phone_area_code") or "+90"
            try:
                cleaned_data["client_phone"] = _normalize_walk_in_client_phone(area_code, phone)
            except forms.ValidationError as exc:
                self.add_error("client_phone", exc)
                cleaned_data["client_phone"] = ""
        else:
            cleaned_data["client_phone"] = ""

        destination_search = (cleaned_data.get("destination_search") or "").strip()
        cleaned_data["destination_search"] = destination_search
        cleaned_data["destination_client_id"] = (cleaned_data.get("destination_client_id") or "").strip()
        cleaned_data["destination"] = destination_search or None

        return cleaned_data


class SlaughterOrderUpdateForm(forms.ModelForm):
    # Client search functionality for updates
    client_search = forms.CharField(
        max_length=255,
        required=False,
        label=_("Search client"),
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Search by name, phone, or destination..."),
                "id": "client-search",
                "autocomplete": "off",
            }
        ),
    )

    # Hidden field to store selected client ID
    client_id = forms.CharField(required=False, widget=forms.HiddenInput(attrs={"id": "client-id"}))

    client_name = forms.CharField(
        max_length=255,
        required=False,
        label=_("Walk-in Client Name"),
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Enter client name for walk-in customers"),
            }
        ),
    )

    # Phone area code selection
    AREA_CODE_CHOICES = [
        ("+90", "+90"),
        ("+1", "+1"),
    ]

    client_phone_area_code = forms.ChoiceField(
        choices=AREA_CODE_CHOICES,
        initial="+90",
        required=False,
        label=_("Area Code"),
        widget=forms.Select(
            attrs={"class": "modern-select", "title": _("Select country code: +90 for Turkey, +1 for USA/Canada")}
        ),
    )

    client_phone = forms.CharField(
        max_length=15,
        required=False,
        label=_("Walk-in Client Phone"),
        help_text=_(
            "Optional — leave blank if you're in a rush. Without a phone we cannot save this walk-in as a reusable client for future orders or follow-up."
        ),
        widget=forms.TextInput(
            attrs={
                "class": "flex-1 px-3 py-2 border border-l-0 border-gray-300 rounded-r-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Enter phone number"),
            }
        ),
    )

    destination_search = forms.CharField(
        max_length=255,
        required=False,
        label=_("Destination Client"),
        help_text=_("Type to search destination clients. Select one to keep it linked for future orders."),
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Type destination client name to search..."),
                "id": "destination-search",
                "autocomplete": "off",
            }
        ),
    )
    destination_client_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "destination-client-id"}),
    )

    class Meta:
        model = SlaughterOrder
        fields = ["service_package", "order_datetime", "destination"]
        labels = {
            "service_package": _("Service package"),
            "order_datetime": _("Order datetime"),
            "destination": _("Destination"),
        }
        help_texts = {
            "service_package": _("The service package selected for this order."),
            "destination": _("Hidden snapshot of the selected destination client."),
        }
        widgets = {
            "order_datetime": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                }
            ),
            "destination": forms.HiddenInput(
                attrs={
                    "id": "destination-text",
                }
            ),
            "service_package": forms.Select(attrs={"class": "modern-select-full"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.can_edit_client = True
        self.can_edit_order_datetime = True
        self.can_edit_service_package = True
        self.can_edit_destination = True
        self.is_destination_only_mode = False
        self.is_readonly_mode = False
        self.generated_animal_label_count = 0
        self.has_generated_animal_labels = False
        sp = self.fields["service_package"]
        qs = ServicePackage.objects.filter(is_active=True)
        if self.instance and getattr(self.instance, "service_package_id", None):
            qs = ServicePackage.objects.filter(Q(is_active=True) | Q(pk=self.instance.service_package_id))
        sp.queryset = qs
        sp.empty_label = _("Select service package")
        sp.label_from_instance = lambda obj: obj.localized_name()
        sp.required = True
        msgs = dict(sp.error_messages)
        msgs["required"] = _("Please choose a service package before saving the order.")
        msgs["invalid_choice"] = _("Select a valid service package.")
        sp.error_messages = msgs

        # Pre-populate client fields if instance exists
        if self.instance and self.instance.pk:
            if self.instance.client:
                self.fields["client_search"].initial = (
                    self.instance.client.company_name or self.instance.client.get_full_name()
                )
                self.fields["client_id"].initial = self.instance.client.pk
            else:
                self.fields["client_name"].initial = self.instance.client_name
                # Split phone number if it exists
                if self.instance.client_phone:
                    phone = self.instance.client_phone
                    if phone.startswith("+90"):
                        self.fields["client_phone_area_code"].initial = "+90"
                        self.fields["client_phone"].initial = phone[3:]
                    elif phone.startswith("+1"):
                        self.fields["client_phone_area_code"].initial = "+1"
                        self.fields["client_phone"].initial = phone[2:]
                    else:
                        self.fields["client_phone"].initial = phone
            if self.instance.destination_client:
                self.fields["destination_search"].initial = self.instance.destination_client.get_full_name()
                self.fields["destination_client_id"].initial = self.instance.destination_client.pk
            else:
                self.fields["destination_search"].initial = self.instance.destination or ""

            self.can_edit_client = can_reassign_order_client(self.instance)
            self.can_edit_order_datetime = can_edit_order_datetime(self.instance)
            self.can_edit_service_package = can_edit_order_service_package(self.instance)
            self.can_edit_destination = can_edit_order_destination(self.instance)
            self.is_destination_only_mode = (
                self.can_edit_destination
                and not self.can_edit_client
                and not self.can_edit_order_datetime
                and not self.can_edit_service_package
            )
            self.is_readonly_mode = not (
                self.can_edit_client
                or self.can_edit_order_datetime
                or self.can_edit_service_package
                or self.can_edit_destination
            )

            from labeling.models import AnimalLabel

            self.generated_animal_label_count = AnimalLabel.objects.filter(
                animal__slaughter_order=self.instance,
                cut__isnull=True,
                is_active=True,
            ).count()
            self.has_generated_animal_labels = self.generated_animal_label_count > 0

        if not self.can_edit_client:
            for field_name in ["client_search", "client_id", "client_name", "client_phone_area_code", "client_phone"]:
                self.fields[field_name].disabled = True
                self.fields[field_name].required = False

        if not self.can_edit_service_package:
            self.fields["service_package"].disabled = True
            self.fields["service_package"].required = False

        if not self.can_edit_order_datetime:
            self.fields["order_datetime"].disabled = True
            self.fields["order_datetime"].required = False

        if not self.can_edit_destination:
            for field_name in ["destination_search", "destination_client_id", "destination"]:
                self.fields[field_name].disabled = True
                self.fields[field_name].required = False

    def clean(self):
        cleaned_data = super().clean()
        if self.can_edit_client:
            client_id = (cleaned_data.get("client_id") or "").strip()
            client_name = (cleaned_data.get("client_name") or "").strip()
            cleaned_data["client_id"] = client_id
            cleaned_data["client_name"] = client_name

            if not client_id and not client_name:
                raise forms.ValidationError(
                    _("An order must be linked to either a saved client from search or a walk-in client name.")
                )

            if client_id and client_name:
                raise forms.ValidationError(
                    _("Please provide either a client from search or walk-in fields, not both.")
                )

            # Phone is optional for walk-ins; validate format only when one is provided.
            phone = (cleaned_data.get("client_phone") or "").strip()
            if phone:
                area_code = cleaned_data.get("client_phone_area_code") or "+90"
                try:
                    cleaned_data["client_phone"] = _normalize_walk_in_client_phone(area_code, phone)
                except forms.ValidationError as exc:
                    self.add_error("client_phone", exc)
                    cleaned_data["client_phone"] = ""
            else:
                cleaned_data["client_phone"] = ""
        else:
            cleaned_data["client_id"] = str(self.instance.client_id) if self.instance.client_id else ""
            cleaned_data["client_name"] = (self.instance.client_name or "").strip()
            cleaned_data["client_phone"] = (self.instance.client_phone or "").strip()

        if self.can_edit_destination:
            destination_search = (cleaned_data.get("destination_search") or "").strip()
            cleaned_data["destination_search"] = destination_search
            cleaned_data["destination_client_id"] = (cleaned_data.get("destination_client_id") or "").strip()
            cleaned_data["destination"] = destination_search or None
        else:
            if self.instance.destination_client:
                cleaned_data["destination_search"] = self.instance.destination_client.get_full_name()
                cleaned_data["destination_client_id"] = str(self.instance.destination_client_id)
            else:
                cleaned_data["destination_search"] = (self.instance.destination or "").strip()
                cleaned_data["destination_client_id"] = ""
            cleaned_data["destination"] = self.instance.destination or None

        if not self.can_edit_service_package:
            cleaned_data["service_package"] = self.instance.service_package

        if not self.can_edit_order_datetime:
            cleaned_data["order_datetime"] = self.instance.order_datetime

        return cleaned_data


class AnimalForm(forms.ModelForm):
    class Meta:
        model = Animal
        fields = ["animal_type", "identification_tag", "received_date", "picture", "passport_picture"]
        widgets = {
            "animal_type": forms.Select(attrs={"class": "modern-select-full"}),
            "identification_tag": forms.TextInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "placeholder": _("Enter identification tag (optional - auto-generated if empty)"),
                }
            ),
            "received_date": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                }
            ),
            "picture": forms.FileInput(
                attrs={
                    "accept": "image/*",
                    "class": "block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100",
                }
            ),
            "passport_picture": forms.FileInput(
                attrs={
                    "accept": "image/*",
                    "class": "block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        # Extract skip_photos parameter if provided
        self.skip_photos = kwargs.pop("skip_photos", False)
        super().__init__(*args, **kwargs)
        self.fields["animal_type"].empty_label = _("Select animal type")
        self.fields["identification_tag"].required = False

        # Set custom labels
        self.fields["picture"].label = _("Animal Photo (Optional)")
        self.fields["passport_picture"].label = _("Passport/Document Photo (Optional)")

        # Make photos optional for both individual and batch creation
        self.fields["picture"].required = False
        self.fields["passport_picture"].required = False


class BatchAnimalForm(forms.Form):
    """Form for creating multiple animals at once with automatic tag generation"""

    animal_type = forms.ChoiceField(
        choices=Animal.ANIMAL_TYPES, label=_("Animal Type"), widget=forms.Select(attrs={"class": "modern-select-full"})
    )

    quantity = forms.IntegerField(
        min_value=1,
        max_value=100,
        initial=1,
        label=_("Number of Animals"),
        widget=forms.NumberInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("Enter number of animals (1-100)"),
            }
        ),
    )

    tag_prefix = forms.CharField(
        max_length=20,
        required=False,
        label=_("Tag Prefix (Optional)"),
        widget=forms.TextInput(
            attrs={
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                "placeholder": _("e.g., BATCH-001 (leave empty for auto-generation)"),
            }
        ),
        help_text=_(
            "Custom prefix for identification tags. The sequence continues for the same prefix on the same day and resets the next day. If empty, auto-generated tags will be used."
        ),
    )

    received_date = forms.DateTimeField(
        required=False,
        label=_("Received Date & Time"),
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "type": "datetime-local",
                "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
            },
        ),
        input_formats=[
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M",
        ],
        help_text=_("Pre-filled with the current date and time; clear to use the time when you submit."),
    )

    skip_photos = forms.BooleanField(
        required=False,
        initial=False,
        label=_("Skip Photos for Batch"),
        widget=forms.CheckboxInput(
            attrs={"class": "h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"}
        ),
        help_text=_("Check this to create animals without photos (photos can be added later)"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["animal_type"].empty_label = _("Select animal type")
        if not self.is_bound:
            self.fields["received_date"].initial = timezone.localtime(timezone.now())

    def clean_quantity(self):
        quantity = self.cleaned_data.get("quantity")
        if quantity and quantity > 100:
            raise forms.ValidationError(_("Maximum 100 animals can be created in a single batch."))
        return quantity
