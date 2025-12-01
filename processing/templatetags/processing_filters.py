from django import template
from django.db.models import Sum

register = template.Library()

@register.filter
def sum_weights(queryset):
    """Sum the weight_kg field from a queryset of DisassemblyCut objects."""
    if not queryset:
        return 0
    total = queryset.aggregate(total=Sum('weight_kg'))['total']
    return total if total else 0

