from django import forms
from django.utils.translation import gettext_lazy as _
from .models import Animal, WeightLog, CattleDetails, SheepDetails, GoatDetails, LambDetails, OglakDetails, CalfDetails, HeiferDetails, BeefDetails
from django.core.exceptions import ValidationError

class AnimalFilterForm(forms.Form):
    # Status filter
    status = forms.ChoiceField(
        choices=[('', _('All Statuses'))] + list(Animal.STATUS_CHOICES),
        required=False,
        label=_("Status"),
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md  focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white modern-select-full',
            'id': 'status',
            'style': 'color: #111827 !important; background-color: #ffffff !important;'
        })
    )
    
    # Animal type filter
    animal_type = forms.ChoiceField(
        choices=[('', _('All Types'))] + list(Animal.ANIMAL_TYPES),
        required=False,
        label=_("Animal Type"),
        widget=forms.Select(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white modern-select-full',
            'id': 'animal_type',
            'style': 'color: #111827 !important; background-color: #ffffff !important;'
        })
    )
    
    # Search field with AJAX functionality
    search = forms.CharField(
        max_length=255,
        required=False,
        label=_("Search Animals"),
        widget=forms.TextInput(attrs={
            'class': 'w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-gray-900 bg-white',
            'placeholder': _('Search by Tag, Order Number, Client Name, or Animal Type'),
            'id': 'animal-search',
            'autocomplete': 'off',
            'style': 'color: #111827 !important; background-color: #ffffff !important;'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set initial values if provided in GET parameters
        if args and len(args) > 0:
            data = args[0]
            if data:
                self.fields['status'].initial = data.get('status', '')
                self.fields['animal_type'].initial = data.get('animal_type', '')
                self.fields['search'].initial = data.get('search', '')


class WeightLogForm(forms.ModelForm):
    """Form for logging individual animal weights including leather weight"""
    
    WEIGHT_TYPE_CHOICES = [
        ('', _('Select weight type')),
        ('live_weight', _('Live Weight')),
        ('hot_carcass_weight', _('Hot Carcass Weight')),
        ('cold_carcass_weight', _('Cold Carcass Weight')),
        ('final_weight', _('Final Weight')),
        ('leather_weight', _('Leather Weight')),
    ]
    
    weight_type = forms.ChoiceField(
        choices=WEIGHT_TYPE_CHOICES,
        required=True,
        label=_("Weight Type"),
        widget=forms.Select(attrs={
            'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500',
            'id': 'weight_type',
            'style': 'color: #111827 !important; background-color: #ffffff !important;'
        })
    )
    
    weight = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        label=_("Weight (kg)"),
        widget=forms.NumberInput(attrs={
            'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white placeholder-gray-500 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': _('Enter weight in kg'),
            'step': '0.01',
            'id': 'weight',
            'style': 'color: #111827 !important; background-color: #ffffff !important;'
        })
    )
    
    class Meta:
        model = WeightLog
        fields = ['weight_type', 'weight']
    
    def __init__(self, *args, animal=None, **kwargs):
        self.animal = animal
        super().__init__(*args, **kwargs)
        
        # Filter weight type choices based on animal status
        if self.animal:
            available_choices = [('', _('Select weight type'))]
            
            # Live weight is always available
            available_choices.append(('live_weight', _('Live Weight')))
            
            # Hot carcass weight only for slaughtered animals
            if self.animal.status in ['slaughtered', 'carcass_ready']:
                available_choices.append(('hot_carcass_weight', _('Hot Carcass Weight')))
            
            # Cold carcass weight only for carcass_ready or later
            if self.animal.status in ['carcass_ready', 'disassembled', 'packaged', 'delivered']:
                available_choices.append(('cold_carcass_weight', _('Cold Carcass Weight')))
            
            # Final weight only for disassembled or later
            if self.animal.status in ['disassembled', 'packaged', 'delivered']:
                available_choices.append(('final_weight', _('Final Weight')))
            
            # Leather weight for any status except received
            if self.animal.status != 'received':
                available_choices.append(('leather_weight', _('Leather Weight')))
            
            self.fields['weight_type'].choices = available_choices
    
    def clean_weight(self):
        weight = self.cleaned_data.get('weight')
        weight_type = self.cleaned_data.get('weight_type')
        
        if weight and weight_type:
            # Basic validation - adjust limits based on animal type if needed
            if weight > 2000:  # 2000kg seems like a reasonable upper limit
                raise ValidationError(_("Weight seems unusually high. Please verify."))
            if weight < 0.01:
                raise ValidationError(_("Weight must be greater than 0."))
        
        return weight
    
    def clean(self):
        cleaned_data = super().clean()
        weight_type = cleaned_data.get('weight_type')
        weight = cleaned_data.get('weight')
        
        if weight_type and weight and self.animal:
            # Validate weight type based on animal status
            weight_type_lower = weight_type.lower()
            
            if weight_type_lower in ['hot_carcass_weight']:
                if self.animal.status not in ['slaughtered', 'carcass_ready']:
                    raise ValidationError({
                        'weight_type': _('Hot carcass weight can only be logged for slaughtered animals. Animal %(tag)s is currently %(status)s.') % {'tag': self.animal.identification_tag, 'status': self.animal.get_status_display()}
                    })
            elif weight_type_lower in ['cold_carcass_weight']:
                if self.animal.status not in ['carcass_ready', 'disassembled', 'packaged', 'delivered']:
                    raise ValidationError({
                        'weight_type': _('Cold carcass weight can only be logged for animals with carcass ready or later status. Animal %(tag)s is currently %(status)s.') % {'tag': self.animal.identification_tag, 'status': self.animal.get_status_display()}
                    })
            elif weight_type_lower in ['final_weight']:
                if self.animal.status not in ['disassembled', 'packaged', 'delivered']:
                    raise ValidationError({
                        'weight_type': _('Final weight can only be logged for disassembled animals. Animal %(tag)s is currently %(status)s.') % {'tag': self.animal.identification_tag, 'status': self.animal.get_status_display()}
                    })
            elif weight_type_lower in ['leather_weight']:
                if self.animal.status == 'received':
                    raise ValidationError({
                        'weight_type': _('Leather weight should be logged after slaughter. Animal %(tag)s is currently %(status)s.') % {'tag': self.animal.identification_tag, 'status': self.animal.get_status_display()}
                    })
            # live_weight can be logged for any status - no validation needed
            
            # Note: Removed duplicate validation to allow overwriting existing weight entries
        
        return cleaned_data


class LeatherWeightForm(forms.ModelForm):
    """Dedicated form for logging leather weight directly to Animal model"""
    
    leather_weight_kg = forms.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=0.01,
        label=_("Leather Weight (kg)"),
        widget=forms.NumberInput(attrs={
            'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white placeholder-gray-500 focus:ring-blue-500 focus:border-blue-500',
            'placeholder': _('Enter leather weight in kg'),
            'step': '0.01'
        })
    )
    
    class Meta:
        model = Animal
        fields = ['leather_weight_kg']
    
    def clean_leather_weight_kg(self):
        weight = self.cleaned_data.get('leather_weight_kg')
        
        if weight:
            if weight > 200:  # Reasonable upper limit for leather weight
                raise ValidationError(_("Leather weight seems unusually high. Please verify."))
            if weight < 0.01:
                raise ValidationError(_("Weight must be greater than 0."))
        
        return weight


class ScaleReceiptUploadForm(forms.ModelForm):
    class Meta:
        model = Animal
        fields = ['scale_receipt_picture']
        labels = {
            'scale_receipt_picture': _('Scale Receipt Image'),
        }
        widgets = {
            'scale_receipt_picture': forms.FileInput(attrs={
                'class': 'sr-only',  # Hide native input
                'accept': 'image/*',
                'id': 'id_scale_receipt_picture',
            })
        }

    def clean_scale_receipt_picture(self):
        image = self.cleaned_data.get('scale_receipt_picture')
        if image and hasattr(self.instance, 'scale_receipt_picture') and self.instance.scale_receipt_picture:
            self.instance.scale_receipt_picture.delete(save=False)
        return image


class BatchWeightLogForm(forms.Form):
    """Form for logging batch weights"""
    
    BATCH_WEIGHT_TYPE_CHOICES = [
        ('', _('Select weight type')),
        ('live_weight', _('Live Weight')),
        ('hot_carcass_weight', _('Hot Carcass Weight')),
        ('cold_carcass_weight', _('Cold Carcass Weight')),
        ('final_weight', _('Final Weight')),
    ]
    
    order_id = forms.UUIDField(
        widget=forms.HiddenInput(attrs={
            'style': 'display: none;'
        })
    )
    
    weight_type = forms.ChoiceField(
        choices=BATCH_WEIGHT_TYPE_CHOICES,
        required=True,
        label=_("Weight Type"),
        widget=forms.Select(attrs={
            'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-gray-900 bg-white focus:ring-purple-500 focus:border-purple-500'
        })
    )
    
    total_weight = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        label=_("Total Weight (kg)"),
        help_text=_("Enter the combined weight of all animals in the batch"),
        widget=forms.NumberInput(attrs={
            'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-gray-900 bg-white placeholder-gray-500 focus:ring-purple-500 focus:border-purple-500',
            'placeholder': _('Enter total weight in kilograms'),
            'step': '0.01'
        })
    )
    
    animal_count = forms.IntegerField(
        min_value=1,
        label=_("Number of Animals"),
        help_text=_("Number of animals included in this batch weight"),
        widget=forms.NumberInput(attrs={
            'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-gray-900 bg-white placeholder-gray-500 focus:ring-purple-500 focus:border-purple-500',
            'placeholder': _('Number of animals weighed together')
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        total_weight = cleaned_data.get('total_weight')
        animal_count = cleaned_data.get('animal_count')
        order_id = cleaned_data.get('order_id')
        weight_type = cleaned_data.get('weight_type')
        
        if total_weight and animal_count:
            average_weight = total_weight / animal_count
            
            # Sanity check for average weight
            if average_weight > 1000:  # 1000kg average seems high
                raise ValidationError(_("Average weight per animal seems unusually high. Please verify."))
            if average_weight < 1:  # 1kg average seems low
                raise ValidationError(_("Average weight per animal seems unusually low. Please verify."))
            
            # Validate that we don't exceed the actual number of slaughtered animals
            if order_id and weight_type:
                try:
                    from reception.models import SlaughterOrder
                    from .models import WeightLog
                    
                    order = SlaughterOrder.objects.get(pk=order_id)
                    
                    # Determine available animal count based on weight type
                    if weight_type == 'live_weight':
                        # For live weight, count all relevant statuses
                        available_count = order.animals.filter(status__in=['received', 'slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered']).count()
                    elif weight_type == 'hot_carcass_weight':
                        # For hot carcass weight, count slaughtered/carcass_ready+ animals
                        available_count = order.animals.filter(status__in=['slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered']).count()
                    elif weight_type == 'cold_carcass_weight':
                        # For cold carcass weight, count carcass_ready+ animals
                        available_count = order.animals.filter(status__in=['carcass_ready', 'disassembled', 'packaged', 'delivered']).count()
                    elif weight_type == 'final_weight':
                        # For final weight, count disassembled+ animals
                        available_count = order.animals.filter(status__in=['disassembled', 'packaged', 'delivered']).count()
                    else:
                        # Default fallback for any other weight types
                        available_count = order.animals.filter(status__in=['received', 'slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered']).count()
                    
                    # Basic validation: ensure this batch doesn't exceed available animals
                    if animal_count > available_count:
                        raise ValidationError(
                            _("Cannot log weight for %(animal_count)s animals. Only %(available_count)s animals are available for %(weight_type)s weighing in this order.") % {
                                'animal_count': animal_count, 
                                'available_count': available_count, 
                                'weight_type': weight_type.replace('_', ' ').title()
                            }
                        )
                    
                    # CUMULATIVE VALIDATION: Check existing batch logs for this weight type
                    group_weight_type = f"{weight_type} Group"
                    existing_logs = WeightLog.objects.filter(
                        slaughter_order=order,
                        weight_type=group_weight_type,
                        is_group_weight=True
                    )
                    
                    # Calculate total animals already weighed for this weight type
                    total_animals_already_weighed = sum(log.group_quantity for log in existing_logs)
                    
                    # Check if adding this batch would exceed available animals
                    total_after_this_batch = total_animals_already_weighed + animal_count
                    
                    if total_after_this_batch > available_count:
                        remaining_available = available_count - total_animals_already_weighed
                        raise ValidationError(
                            _("Cannot log weight for %(animal_count)s animals. Only %(remaining_available)s animals remain available for %(weight_type)s weighing (%(already_weighed)s already weighed out of %(total)s total).") % {
                                'animal_count': animal_count, 
                                'remaining_available': remaining_available, 
                                'weight_type': weight_type.replace('_', ' ').title(), 
                                'already_weighed': total_animals_already_weighed, 
                                'total': available_count
                            }
                        )
                        
                except SlaughterOrder.DoesNotExist:
                    raise ValidationError(_("Invalid order selected."))
        
        return cleaned_data


class CattleDetailsForm(forms.ModelForm):
    """Form for cattle-specific details"""
    class Meta:
        model = CattleDetails
        fields = ['breed', 'sakatat_status', 'bowels_status']
        labels = {
            'breed': _('Breed'),
            'sakatat_status': _('Sakatat Status'),
            'bowels_status': _('Bowels Status'),
        }
        widgets = {
            'breed': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white placeholder-gray-500 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': _('Enter breed (e.g., Holstein, Angus, Hereford)')
            }),
            'sakatat_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
            'bowels_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
        }

class SheepDetailsForm(forms.ModelForm):
    """Form for sheep-specific details"""
    class Meta:
        model = SheepDetails
        fields = ['breed', 'sakatat_status', 'bowels_status']
        labels = {
            'breed': _('Breed'),
            'sakatat_status': _('Sakatat Status'),
            'bowels_status': _('Bowels Status'),
        }
        widgets = {
            'breed': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white placeholder-gray-500 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': _('Enter breed (e.g., Merino, Suffolk, Dorper)')
            }),
            'sakatat_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
            'bowels_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
        }

class GoatDetailsForm(forms.ModelForm):
    """Form for goat-specific details"""
    class Meta:
        model = GoatDetails
        fields = ['breed', 'sakatat_status', 'bowels_status']
        labels = {
            'breed': _('Breed'),
            'sakatat_status': _('Sakatat Status'),
            'bowels_status': _('Bowels Status'),
        }
        widgets = {
            'breed': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white placeholder-gray-500 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': _('Enter breed (e.g., Boer, Nubian, Angora)')
            }),
            'sakatat_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
            'bowels_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
        }

class LambDetailsForm(forms.ModelForm):
    """Form for lamb-specific details"""
    class Meta:
        model = LambDetails
        fields = ['sakatat_status', 'bowels_status']
        labels = {
            'sakatat_status': _('Sakatat Status'),
            'bowels_status': _('Bowels Status'),
        }
        widgets = {
            'sakatat_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
            'bowels_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
        }

class OglakDetailsForm(forms.ModelForm):
    """Form for oglak-specific details"""
    class Meta:
        model = OglakDetails
        fields = ['sakatat_status', 'bowels_status']
        labels = {
            'sakatat_status': _('Sakatat Status'),
            'bowels_status': _('Bowels Status'),
        }
        widgets = {
            'sakatat_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
            'bowels_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
        }

class CalfDetailsForm(forms.ModelForm):
    """Form for calf-specific details"""
    class Meta:
        model = CalfDetails
        fields = ['breed', 'sakatat_status', 'bowels_status']
        labels = {
            'breed': _('Breed'),
            'sakatat_status': _('Sakatat Status'),
            'bowels_status': _('Bowels Status'),
        }
        widgets = {
            'breed': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white placeholder-gray-500 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': _('Enter breed (e.g., Holstein, Jersey, Brahman)')
            }),
            'sakatat_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
            'bowels_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
        }

class HeiferDetailsForm(forms.ModelForm):
    """Form for heifer-specific details"""
    class Meta:
        model = HeiferDetails
        fields = ['breed', 'sakatat_status', 'bowels_status']
        labels = {
            'breed': _('Breed'),
            'sakatat_status': _('Sakatat Status'),
            'bowels_status': _('Bowels Status'),
        }
        widgets = {
            'breed': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white placeholder-gray-500 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': _('Enter breed (e.g., Holstein, Angus, Charolais)')
            }),
            'sakatat_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
            'bowels_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
        }

class BeefDetailsForm(forms.ModelForm):
    """Form for beef-specific details"""
    class Meta:
        model = BeefDetails
        fields = ['breed', 'sakatat_status', 'bowels_status']
        labels = {
            'breed': _('Breed'),
            'sakatat_status': _('Sakatat Status'),
            'bowels_status': _('Bowels Status'),
        }
        widgets = {
            'breed': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white placeholder-gray-500 focus:ring-blue-500 focus:border-blue-500',
                'placeholder': _('Enter breed (e.g., Holstein, Angus, Charolais)')
            }),
            'sakatat_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            }),
            'bowels_status': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-md px-3 py-2 text-sm text-gray-900 bg-white focus:ring-blue-500 focus:border-blue-500'
            })
        }

# Mapping of animal types to their detail forms
ANIMAL_DETAIL_FORMS = {
    'cattle': CattleDetailsForm,
    'sheep': SheepDetailsForm,
    'goat': GoatDetailsForm,
    'lamb': LambDetailsForm,
    'oglak': OglakDetailsForm,
    'calf': CalfDetailsForm,
    'heifer': HeiferDetailsForm,
    'beef': BeefDetailsForm,
}