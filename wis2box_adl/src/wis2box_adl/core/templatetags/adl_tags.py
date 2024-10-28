from django import template
from django.conf import settings

register = template.Library()


@register.filter
def django_settings(value):
    return getattr(settings, value, None)
