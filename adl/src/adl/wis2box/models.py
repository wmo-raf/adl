from django.core.validators import MinValueValidator
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
    
    barometer_ground_clearance = models.FloatField(
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Barometer ground clearance (m)"),
        help_text=_("Height of the barometer above the station ground, used to suggest barometer heights "
                    "(station elevation + clearance) when exporting stations for wis2box."),
    )
    
    panels = [
        FieldPanel("wis2box_url"),
        FieldPanel("barometer_ground_clearance"),
    ]
    
    class Meta:
        verbose_name = _("Wis2Box Settings")
