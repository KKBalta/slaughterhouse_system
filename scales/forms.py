"""Forms for scale operations admin UI."""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Site

_TAILWIND_CONTROL = (
    "mt-1 block w-full rounded-md border-gray-300 shadow-sm "
    "focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
)


class SiteForm(forms.ModelForm):
    """Create or edit a tenant site (plant / location for Edges and scales)."""

    class Meta:
        model = Site
        fields = ("name", "address")
        labels = {
            "name": _("Site name"),
            "address": _("Address"),
        }
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": _TAILWIND_CONTROL,
                    "autocomplete": "organization",
                    "required": True,
                }
            ),
            "address": forms.Textarea(
                attrs={
                    "class": _TAILWIND_CONTROL,
                    "rows": 3,
                    "autocomplete": "street-address",
                }
            ),
        }
