import uuid as uuid_lib

from django import forms
from django.db import models
from django.urls import reverse
from modelcluster.fields import ParentalKey, ParentalManyToManyField
from modelcluster.models import ClusterableModel
from wagtail.admin.panels import InlinePanel, FieldPanel, TabbedInterface, ObjectList
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting
from wagtail.fields import StreamField

from adl.core.models import DataParameter
from .blocks import ColorScaleBlock


@register_setting
class MapViewerSetting(BaseSiteSetting, ClusterableModel):
    class Meta:
        verbose_name = 'Map Viewer Settings'
    
    map_styles_panels = [
        InlinePanel('data_parameter_styles', label='Data Parameter Styles'),
    ]
    
    edit_handler = TabbedInterface([
        ObjectList(map_styles_panels, heading='Map Styles'),
        # ObjectList(general_panels, heading='General'),
    ])


class DataParameterStyle(ClusterableModel):
    setting = ParentalKey(
        MapViewerSetting,
        related_name='data_parameter_styles',
        on_delete=models.CASCADE
    )
    data_parameter = models.ForeignKey(
        DataParameter,
        on_delete=models.CASCADE,
        related_name='styles'
    )
    
    # Color scale as a StreamField
    color_scale = StreamField(
        [
            ('color_stop', ColorScaleBlock()),
        ],
        blank=True,
        use_json_field=True,
        collapsed=True,
        help_text="Define color stops for the gradient. Add values from low to high with corresponding colors."
    )
    
    panels = [
        FieldPanel('data_parameter'),
        FieldPanel('color_scale'),
    ]
    
    class Meta:
        verbose_name = 'Data Parameter Style'
        verbose_name_plural = 'Data Parameter Styles'
        unique_together = ['setting', 'data_parameter']
    
    def __str__(self):
        return f"Style for {self.data_parameter}"
    
    def get_maplibre_color_scale(self):
        """
        Convert the color scale to MapLibre GL JS format
        Returns an array in the format:
        ['interpolate', ['linear'], ['get', 'value'], 0, '#color1', 50, '#color2', ...]
        """
        if not self.color_scale:
            return None
        
        scale = ['interpolate', ['linear'], ['get', 'value']]
        
        for stop in self.color_scale:
            scale.append(stop.value['value'])
            scale.append(stop.value['color'])
        
        return scale
    
    def get_color_scale_json(self):
        """
        Get color scale as a simple list for API responses
        """
        return [
            {
                'value': stop.value['value'],
                'color': stop.value['color'],
                'label': stop.value.get('label', '')
            }
            for stop in self.color_scale
        ]


class WidgetDisplay(ClusterableModel):
    uuid = models.UUIDField(default=uuid_lib.uuid4, editable=False, unique=True)
    name = models.CharField(max_length=255)
    rotation_interval = models.PositiveIntegerField(
        default=10,
        help_text="Seconds to display each station before rotating"
    )
    poll_interval = models.PositiveIntegerField(
        default=5,
        help_text="Minutes between data refresh requests"
    )
    default_view = models.CharField(
        max_length=20,
        choices=[("rotating", "Rotating Cards + Mini Map"), ("map", "Full Map Overlay")],
        default="rotating"
    )
    stations = ParentalManyToManyField(
        "core.StationLink",
        blank=True,
        related_name="widget_displays"
    )
    parameters = ParentalManyToManyField(
        DataParameter,
        blank=True,
        related_name="widget_displays"
    )

    panels = [
        FieldPanel("name"),
        FieldPanel("default_view"),
        FieldPanel("rotation_interval"),
        FieldPanel("poll_interval"),
        FieldPanel("stations", widget=forms.CheckboxSelectMultiple),
        FieldPanel("parameters", widget=forms.CheckboxSelectMultiple),
    ]

    class Meta:
        verbose_name = "Widget Display"
        verbose_name_plural = "Widget Displays"

    def __str__(self):
        return self.name

    def get_display_url(self):
        return reverse("widget_display", kwargs={"pk": self.pk})

    @property
    def display_url(self):
        if not self.pk:
            return "(save first to get the display URL)"
        return self.get_display_url()
