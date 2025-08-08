from django.contrib import admin
from .models import Animal, CattleDetails, SheepDetails, GoatDetails, LambDetails, OglakDetails, WeightLog

class CattleDetailsInline(admin.StackedInline):
    model = CattleDetails
    can_delete = False
    verbose_name_plural = 'Cattle Details'

class SheepDetailsInline(admin.StackedInline):
    model = SheepDetails
    can_delete = False
    verbose_name_plural = 'Sheep Details'

class GoatDetailsInline(admin.StackedInline):
    model = GoatDetails
    can_delete = False
    verbose_name_plural = 'Goat Details'

class LambDetailsInline(admin.StackedInline):
    model = LambDetails
    can_delete = False
    verbose_name_plural = 'Lamb Details'

class OglakDetailsInline(admin.StackedInline):
    model = OglakDetails
    can_delete = False
    verbose_name_plural = 'Oglak Details'

@admin.register(Animal)
class AnimalAdmin(admin.ModelAdmin):
    list_display = ('identification_tag', 'animal_type', 'slaughter_order', 'status', 'received_date', 'slaughter_date')
    list_filter = ('animal_type', 'status', 'slaughter_order__service_package')
    search_fields = ('identification_tag', 'slaughter_order__id')
    inlines = [CattleDetailsInline, SheepDetailsInline, GoatDetailsInline, LambDetailsInline, OglakDetailsInline]
    raw_id_fields = ('slaughter_order',)

@admin.register(WeightLog)
class WeightLogAdmin(admin.ModelAdmin):
    list_display = ('animal', 'slaughter_order', 'weight_type', 'weight', 'is_group_weight', 'group_quantity', 'log_date')
    list_filter = ('weight_type', 'is_group_weight')
    search_fields = ('animal__identification_tag', 'slaughter_order__id')
    raw_id_fields = ('animal', 'slaughter_order')