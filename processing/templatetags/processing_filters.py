from django import template
from django.db.models import Sum

register = template.Library()


@register.filter
def grams_to_kg(grams):
    """Convert grams to kg for display. Returns formatted string like '2.70 kg'."""
    if grams is None:
        return "0 kg"
    try:
        kg = int(grams) / 1000
        return f"{kg:.2f} kg"
    except (TypeError, ValueError):
        return "0 kg"


@register.filter
def sum_weights(queryset):
    """Sum the weight_kg field from a queryset of DisassemblyCut objects."""
    if not queryset:
        return 0
    total = queryset.aggregate(total=Sum("weight_kg"))["total"]
    return total if total else 0
