from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting
from wagtail.contrib.settings.registry import register_setting


@register_setting
class Wis2BoxSettings(BaseSiteSetting):
    """
    Site-level configuration for the wis2box sidecar integration.

    Stores the base URL of the wis2box instance. The station listing
    endpoint is derived automatically as::

        {wis2box_url}/oapi/collections/stations/items?f=json
    """
    
    wis2box_url = models.URLField(
        blank=True,
        verbose_name=_("Wis2Box URL"),
        help_text=_("Base URL of the wis2box instance, e.g. https://wis2box.example.org"),
    )
    
    panels = [
        FieldPanel("wis2box_url"),
    ]
    
    class Meta:
        verbose_name = _("Wis2Box Settings")
