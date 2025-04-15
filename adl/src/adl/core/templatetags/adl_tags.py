from django import template
from django.conf import settings

from adl import __version__

register = template.Library()


@register.filter
def django_settings(value):
    return getattr(settings, value, None)


@register.simple_tag
def adl_version():
    return __version__
