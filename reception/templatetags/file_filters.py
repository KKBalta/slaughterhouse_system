import os

from django import template

register = template.Library()


@register.filter
def basename(value):
    """Extract the filename from a file path."""
    if hasattr(value, "name"):
        return os.path.basename(value.name)
    return os.path.basename(str(value))
