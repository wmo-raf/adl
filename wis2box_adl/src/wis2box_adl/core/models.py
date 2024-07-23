from datetime import timezone

from django.contrib.gis.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField
from django_countries.widgets import CountrySelectWidget
from modelcluster.models import ClusterableModel
from timescale.db.models.models import TimescaleModel
from timezone_field import TimeZoneField
from wagtail.admin.panels import FieldPanel, TabbedInterface, ObjectList
from wagtail.contrib.settings.models import BaseSiteSetting
from wagtail.contrib.settings.registry import register_setting
from wagtail.snippets.models import register_snippet

from .utils import get_data_parameters_as_choices, get_station_directory_path
from .widgets import PluginSelectWidget


class Network(models.Model):
    WEATHER_STATION_TYPES = (
        ("automatic", _("Automatic Weather Stations")),
        ("manual", _("Manual Weather Stations")),
    )
    name = models.CharField(max_length=255, verbose_name=_("Name"), help_text=_("Name of the network"))
    type = models.CharField(max_length=255, choices=WEATHER_STATION_TYPES, verbose_name=_("Weather Stations Type"),
                            help_text=_("Weather station type"))
    plugin = models.CharField(max_length=255, unique=True, verbose_name=_("Plugin"),
                              help_text=_("Plugin to use for this network"))
    plugin_processing_enabled = models.BooleanField(default=True, verbose_name=_("Plugin Auto Processing Enabled"))
    plugin_processing_interval = models.PositiveIntegerField(default=15,
                                                             verbose_name=_("Plugin Auto Processing Interval "
                                                                            "in Minutes"),
                                                             help_text=_("How often the plugin should run in minutes"),
                                                             validators=[
                                                                 MaxValueValidator(30),
                                                                 MinValueValidator(1)
                                                             ])
    created_at = models.DateTimeField(auto_now_add=True)

    panels = [
        FieldPanel('name'),
        FieldPanel('type'),
        FieldPanel('plugin', widget=PluginSelectWidget),
        FieldPanel("plugin_processing_enabled"),
        FieldPanel("plugin_processing_interval"),
    ]

    class Meta:
        verbose_name = _("Network")
        verbose_name_plural = _("Networks")

    def __str__(self):
        return self.name


class Station(models.Model):
    STATION_TYPE_CHOICES = (
        (0, _("Automatic")),
        (1, _("Manned")),
        (2, _("Hybrid: both automatic and manned")),
    )

    METHOD_OF_GROUND_STATE_MEASUREMENT_CHOICES = (
        (0, _("Manual observation")),
        (1, _("Video camera method")),
        (2, _("Infrared method")),
        (3, _("Laser method")),
        (14, _("Others")),
        (15, _("Missing value")),
    )

    METHOD_OF_SNOW_DEPTH_MEASUREMENT_CHOICES = (
        (0, _("Manual observation")),
        (1, _("Ultrasonic method")),
        (2, _("Video camera method")),
        (3, _("Laser method")),
        (14, _("Others")),
        (15, _("Missing value")),
    )
    station_id = models.CharField(max_length=255, verbose_name=_("Station ID"),
                                  help_text=_("Unique Station Identifier"))
    name = models.CharField(max_length=255, verbose_name=_("Name"), help_text=_("Name of the station"))
    network = models.ForeignKey(Network, on_delete=models.CASCADE, verbose_name=_("Network"))
    wsi_series = models.PositiveIntegerField(verbose_name=_("WSI Series"), help_text=_("WIGOS identifier series"))
    wsi_issuer = models.PositiveIntegerField(verbose_name=_("WSI Issuer"), help_text=_("WIGOS issuer of identifier"))
    wsi_issue_number = models.PositiveIntegerField(verbose_name=_("WSI Issue Number"),
                                                   help_text=_("WIGOS issue number"))
    wsi_local = models.CharField(max_length=255, verbose_name=_("WSI Local"), help_text=_("WIGOS local identifier"))
    wmo_block_number = models.PositiveIntegerField(verbose_name=_("WMO Block Number"), help_text=_("WMO block number"))
    wmo_station_number = models.PositiveIntegerField(verbose_name=_("WMO Station Number"),
                                                     help_text=_("WMO station number"))
    station_type = models.PositiveIntegerField(verbose_name=_("Station Type"), choices=STATION_TYPE_CHOICES,
                                               help_text=_("Type of observing station, encoding using code table "
                                                           "0 02 001 (set to 0, automatic)"))
    location = models.PointField(verbose_name=_("Location"), help_text=_("Location of the station"))
    station_height_above_msl = models.FloatField(blank=True, null=True, verbose_name=_("Station Height Above MSL"),
                                                 help_text=_("Height of the station ground above mean sea level "
                                                             "(to 1 decimal place)"))
    thermometer_height = models.FloatField(blank=True, null=True, verbose_name=_("Thermometer Height"),
                                           help_text=_("Height of thermometer or temperature sensor above the local "
                                                       "ground to 2 decimal places"))
    barometer_height_above_msl = models.FloatField(blank=True, null=True, verbose_name=_("Barometer Height Above MSL"),
                                                   help_text=_("Height of the barometer above mean sea level "
                                                               "(to 1 decimal place), typically height of station "
                                                               "ground plus the height of the sensor "
                                                               "above local ground"))
    anemometer_height = models.FloatField(blank=True, null=True, verbose_name=_("Anemometer Height"),
                                          help_text=_("Height of the anemometer above local ground to 2 decimal "
                                                      "places"))
    rain_sensor_height = models.FloatField(blank=True, null=True, verbose_name=_("Rain Sensor Height"),
                                           help_text=_("Height of the rain gauge above local ground to 2 decimal "
                                                       "place"))
    method_of_ground_state_measurement = models.PositiveIntegerField(blank=True, null=True,
                                                                     choices=METHOD_OF_GROUND_STATE_MEASUREMENT_CHOICES,
                                                                     verbose_name=_("Method of Ground State "
                                                                                    "Measurement"),
                                                                     help_text=_("Method of observing the snow depth "
                                                                                 "encoded using code table 0 02 177"))
    method_of_snow_depth_measurement = models.PositiveIntegerField(blank=True, null=True,
                                                                   verbose_name=_("Method of Snow Depth Measurement"),
                                                                   help_text=_("Method of observing the snow depth "
                                                                               "encoded using code table 0 02 177"))
    time_period_of_wind = models.PositiveIntegerField(blank=True, null=True, verbose_name=_("Time Period of Wind"),
                                                      help_text=_("Time period over which the wind speed and direction "
                                                                  "have been averaged. 10 minutes in normal cases or "
                                                                  "the number of minutes since a significant change "
                                                                  "occuring in the preceeding 10 minutes."))

    timezone = TimeZoneField(default='UTC', verbose_name=_("Station Timezone"),
                             help_text=_("Timezone used by the station for recording observations"))

    basic_info_panels = [
        FieldPanel("station_id"),
        FieldPanel("name"),
        FieldPanel("network"),
        FieldPanel("station_type"),
        FieldPanel("location"),
    ]

    identification_panels = [
        FieldPanel("wsi_series"),
        FieldPanel("wsi_issuer"),
        FieldPanel("wsi_issue_number"),
        FieldPanel("wsi_local"),
        FieldPanel("wmo_block_number"),
        FieldPanel("wmo_station_number"),
    ]

    metadata_panels = [
        FieldPanel("station_height_above_msl"),
        FieldPanel("thermometer_height"),
        FieldPanel("barometer_height_above_msl"),
        FieldPanel("anemometer_height"),
        FieldPanel("rain_sensor_height"),
        FieldPanel("method_of_ground_state_measurement"),
        FieldPanel("method_of_snow_depth_measurement"),
        FieldPanel("time_period_of_wind"),
        FieldPanel("timezone"),
    ]

    edit_handler = TabbedInterface([
        ObjectList(basic_info_panels, heading=_('Base Information')),
        ObjectList(identification_panels, heading=_('WIGOS Identification')),
        ObjectList(metadata_panels, heading=_('Metadata')),
    ])

    class Meta:
        verbose_name = _("Station")
        verbose_name_plural = _("Stations")
        constraints = [
            models.UniqueConstraint(fields=['station_id', 'network'], name='unique_station_id_network')
        ]

    def __str__(self):
        return self.name

    @property
    def wigos_id(self):
        return f"{self.wsi_series}-{self.wsi_issuer}-{self.wsi_issue_number}-{self.wsi_local}"

    @property
    def wis2box_csv_metadata(self):
        return {
            "wsi_series": self.wsi_series,
            "wsi_issuer": self.wsi_issuer,
            "wsi_issue_number": self.wsi_issue_number,
            "wsi_local": self.wsi_local,
            "wmo_block_number": self.wmo_block_number,
            "wmo_station_number": self.wmo_station_number,
            "station_type": self.station_type,
            "latitude": self.location.y,
            "longitude": self.location.x,
            "station_height_above_msl": self.station_height_above_msl,
            "barometer_height_above_msl": self.barometer_height_above_msl,
            "anemometer_height": self.anemometer_height,
            "rain_sensor_height": self.rain_sensor_height,
            "method_of_ground_state_measurement": self.method_of_ground_state_measurement,
            "method_of_snow_depth_measurement": self.method_of_snow_depth_measurement,
            "time_period_of_wind": self.time_period_of_wind,
        }


class DataParameter(models.Model):
    name = models.CharField(max_length=255, verbose_name=_("Name"), help_text=_("Name of the variable"))
    parameter = models.CharField(max_length=255, choices=get_data_parameters_as_choices, verbose_name=_("Parameter"),
                                 unique=True)
    unit = models.CharField(max_length=255, verbose_name=_("Unit"), help_text=_("Unit of the variable"))
    description = models.TextField(verbose_name=_("Description"), help_text=_("Description of the variable"))

    def __str__(self):
        return self.name


@register_snippet
class DataIngestionRecord(TimescaleModel):
    # time field is inherited from TimescaleModel. We use it to store the observation time of the data
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    station = models.ForeignKey(Station, on_delete=models.CASCADE, verbose_name=_("Station"))
    file = models.FileField(upload_to=get_station_directory_path, verbose_name=_("File"))
    uploaded_to_wis2box = models.BooleanField(default=False, verbose_name=_("Uploaded to WIS2BOX"))

    class Meta:
        verbose_name = _("Data Ingestion Record")
        verbose_name_plural = _("Data Ingestion Records")
        ordering = ['-time']
        constraints = [
            models.UniqueConstraint(fields=['time', 'station'], name='unique_station_ingestion_record')
        ]

    @property
    def utc_time(self):
        return self.time.replace(tzinfo=timezone.utc)

    def __str__(self):
        return f"{self.station.name} - {self.utc_time}"

    @property
    def wis2box_filename(self):
        utc_time = self.time.replace(tzinfo=timezone.utc)
        return f"WIGOS_{self.station.wigos_id}_{utc_time.strftime('%Y%m%dT%H%M%S')}.csv"

    def get_csv_content(self):
        return self.file.read().decode('utf-8')


@register_setting
class AdlSettings(ClusterableModel, BaseSiteSetting):
    country = CountryField(blank_label=_("Select Country"), verbose_name=_("Country"))

    panels = [
        FieldPanel("country", widget=CountrySelectWidget()),
    ]


@receiver(post_save, sender=Network)
def update_network_plugin_periodic_task(sender, instance, **kwargs):
    from wis2box_adl.core.tasks import create_or_update_network_plugin_periodic_task

    create_or_update_network_plugin_periodic_task(instance)
