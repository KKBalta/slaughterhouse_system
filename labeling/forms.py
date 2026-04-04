from datetime import timedelta

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import CustomLabel


class CustomLabelForm(forms.ModelForm):
    """
    Form for creating custom labels with manual data entry.
    """

    class Meta:
        model = CustomLabel
        fields = [
            "uretici",
            "kupe_no",
            "tuccar",
            "kesim_tarihi",
            "stt",
            "siparis_no",
            "cinsi",
            "weight",
            "sakatat_status",
            "qr_data",
        ]
        widgets = {
            "uretici": forms.TextInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "placeholder": "Üretici adı",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                }
            ),
            "kupe_no": forms.TextInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "placeholder": "Küpe numarası",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                }
            ),
            "tuccar": forms.TextInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "placeholder": "Tüccar adı (opsiyonel)",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                }
            ),
            "kesim_tarihi": forms.DateInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "type": "date",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                },
                format="%Y-%m-%d",
            ),
            "stt": forms.DateInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "type": "date",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                },
                format="%Y-%m-%d",
            ),
            "siparis_no": forms.TextInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "placeholder": "Sipariş numarası (opsiyonel)",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                }
            ),
            "cinsi": forms.Select(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                }
            ),
            "weight": forms.NumberInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "placeholder": "Ağırlık (kg)",
                    "step": "0.01",
                    "min": "0",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                }
            ),
            "sakatat_status": forms.TextInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "placeholder": "Sakatat durumu",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                }
            ),
            "qr_data": forms.TextInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white",
                    "placeholder": "QR kod verisi (opsiyonel)",
                    "style": "color: #111827 !important; background-color: #ffffff !important;",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        localized_labels = {
            "uretici": _("Üretici Ünvanı"),
            "kupe_no": _("Küpe No"),
            "tuccar": _("Tüccar Ünvanı"),
            "kesim_tarihi": _("Kesim Tarihi"),
            "stt": _("Son Tüketim Tarihi"),
            "siparis_no": _("Sipariş No"),
            "cinsi": _("Cinsi"),
            "weight": _("Ağırlık (kg)"),
            "sakatat_status": _("Sakatat Durumu"),
            "qr_data": _("QR Verisi"),
        }
        localized_placeholders = {
            "uretici": _("Üretici adı"),
            "kupe_no": _("Küpe numarası"),
            "tuccar": _("Tüccar adı (opsiyonel)"),
            "siparis_no": _("Sipariş numarası (opsiyonel)"),
            "weight": _("Ağırlık (kg)"),
            "sakatat_status": _("Sakatat durumu"),
            "qr_data": _("QR kod verisi (opsiyonel)"),
        }
        localized_help_texts = {
            "uretici": _("Üretici / firma adı"),
            "kupe_no": _("Kulak küpe numarası / kimlik numarası"),
            "tuccar": _("Tüccar adı"),
            "kesim_tarihi": _("Kesim tarihi"),
            "stt": _("Son tüketim tarihi"),
            "siparis_no": _("Sipariş numarası"),
            "cinsi": _("Hayvan türü"),
            "weight": _("Net ağırlık (kg)"),
            "sakatat_status": _("Sakatat durum değeri"),
            "qr_data": _("İsteğe bağlı QR kod verisi"),
        }

        for field_name, label in localized_labels.items():
            self.fields[field_name].label = label
        for field_name, placeholder in localized_placeholders.items():
            self.fields[field_name].widget.attrs["placeholder"] = placeholder
        for field_name, help_text in localized_help_texts.items():
            self.fields[field_name].help_text = help_text

        self.fields["cinsi"].choices = [
            ("SIGIR", _("Sığır")),
            ("KOYUN", _("Koyun")),
            ("KECI", _("Keçi")),
            ("KUZU", _("Kuzu")),
            ("OGLAK", _("Oğlak")),
            ("BUZA", _("Buzağı")),
            ("DUVE", _("Düve")),
            ("DANA", _("Dana")),
        ]

        # Set default values
        today = timezone.now().date()
        self.fields["kesim_tarihi"].initial = today
        self.fields["stt"].initial = today + timedelta(days=10)
        self.fields["sakatat_status"].initial = "0.51"

        # Mark required fields
        self.fields["uretici"].required = True
        self.fields["kupe_no"].required = True
        self.fields["kesim_tarihi"].required = True
        self.fields["stt"].required = True
        self.fields["cinsi"].required = True
        self.fields["weight"].required = True

        # Optional fields
        self.fields["tuccar"].required = False
        self.fields["siparis_no"].required = False
        self.fields["sakatat_status"].required = False
        self.fields["qr_data"].required = False

    def clean_weight(self):
        weight = self.cleaned_data.get("weight")
        if weight is not None and weight <= 0:
            raise forms.ValidationError(_("Ağırlık 0'dan büyük olmalıdır."))
        return weight

    def clean(self):
        cleaned_data = super().clean()
        kesim_tarihi = cleaned_data.get("kesim_tarihi")
        stt = cleaned_data.get("stt")

        if kesim_tarihi and stt and stt < kesim_tarihi:
            raise forms.ValidationError(_("Son tüketim tarihi kesim tarihinden önce olamaz."))

        return cleaned_data
