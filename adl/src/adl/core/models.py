from datetime import timezone

from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField
from django_countries.widgets import CountrySelectWidget
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from polymorphic.models import PolymorphicModel
from timescale.db.models.models import TimescaleModel
from timezone_field import TimeZoneField
from wagtail.admin.panels import FieldPanel, TabbedInterface, ObjectList, InlinePanel
from wagtail.admin.panels import MultiFieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting
from wagtail.contrib.settings.registry import register_setting
from wagtail.models import Orderable
from wagtail.snippets.models import register_snippet
from wagtailgeowidget.panels import LeafletPanel

from .dispatchers import get_dispatch_channel_data
from .dispatchers.wis2box import upload_to_wis2box
from .tasks import create_or_update_aggregation_periodic_tasks
from .units import units, validate_unit, TEMPERATURE_UNITS
from .utils import (
    validate_as_integer,
    get_custom_unit_context_entries
)
from .widgets import PluginSelectWidget


class Network(models.Model):
    WEATHER_STATION_TYPES = (
        ("automatic", _("Automatic Weather Stations")),
        ("manual", _("Manual Weather Stations")),
    )
    
    name = models.CharField(max_length=255, verbose_name=_("Name"), help_text=_("Name of the network"))
    type = models.CharField(max_length=255, choices=WEATHER_STATION_TYPES, verbose_name=_("Weather Stations Type"),
                            help_text=_("Weather station type"))
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    panels = [
        FieldPanel('name'),
        FieldPanel('type'),
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
    network = models.ForeignKey(Network, on_delete=models.CASCADE, verbose_name=_("Network"), related_name="stations")
    wsi_series = models.PositiveIntegerField(verbose_name=_("WSI Series"), help_text=_("WIGOS identifier series"))
    wsi_issuer = models.PositiveIntegerField(verbose_name=_("WSI Issuer"), help_text=_("WIGOS issuer of identifier"))
    wsi_issue_number = models.PositiveIntegerField(verbose_name=_("WSI Issue Number"),
                                                   help_text=_("WIGOS issue number"))
    wsi_local = models.CharField(max_length=255, verbose_name=_("WSI Local"), help_text=_("WIGOS local identifier"))
    wmo_block_number = models.PositiveIntegerField(verbose_name=_("WMO Block Number"), help_text=_("WMO block number"),
                                                   blank=True, null=True, default=None)
    wmo_station_number = models.CharField(max_length=255, blank=True, null=True, validators=[validate_as_integer],
                                          verbose_name=_("WMO Station Number"), help_text=_("WMO station number"))
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
        LeafletPanel("location"),
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


class Unit(models.Model):
    name = models.CharField(max_length=255, verbose_name=_("Name"), help_text=_("Name of the unit"), unique=True)
    symbol = models.CharField(max_length=255, verbose_name=_("Symbol"), help_text=_("Symbol of the unit"),
                              validators=[validate_unit], unique=True)
    description = models.TextField(verbose_name=_("Description"), blank=True, null=True,
                                   help_text=_("Description of the unit"))
    
    class Meta:
        verbose_name = _("Unit")
        verbose_name_plural = _("Units")
    
    def __str__(self):
        return self.name
    
    @property
    def pint_unit(self):
        return units(self.symbol)
    
    def get_registry_unit(self):
        unit = self.pint_unit.u
        return str(unit)
    
    get_registry_unit.short_description = _("Unit Registry")


class DataParameter(models.Model):
    name = models.CharField(max_length=255, verbose_name=_("Name"), help_text=_("Name of the variable"))
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, verbose_name=_("Unit"),
                             help_text=_("Unit of the variable"))
    description = models.TextField(verbose_name=_("Description"), blank=True, null=True,
                                   help_text=_("Description of the variable"))
    custom_unit_context = models.CharField(max_length=255, blank=True, null=True,
                                           choices=get_custom_unit_context_entries,
                                           verbose_name=_("Custom Unit Conversion Context"),
                                           help_text=_("Context of the unit"))
    panels = [
        FieldPanel("name"),
        FieldPanel("unit"),
        FieldPanel("description"),
        FieldPanel("custom_unit_context"),
    ]
    
    def __str__(self):
        return f"{self.name} - {self.unit.symbol}"
    
    def clean(self, *args, **kwargs):
        # do not change unit if ObservationRecord exist referencing this parameter
        if self.pk:
            observation_record = ObservationRecord.objects.filter(parameter=self).first()
            if observation_record:
                raise ValidationError(
                    {"unit": _("Cannot change unit of a parameter that has observation records in the database. "
                               "Please remove the observation records first.")}
                )
    
    def convert_value_from_units(self, value, from_unit):
        if from_unit.symbol in TEMPERATURE_UNITS:
            quantity = units.Quantity(value, from_unit.symbol)
        else:
            quantity = value * from_unit.pint_unit
        # use custom unit context if set
        # Useful for converting units that are not directly convertible  using pint,
        # like precipitation (from mm -> kg/m²)
        if self.custom_unit_context:
            with units.context(self.custom_unit_context):
                quantity_converted = quantity.to(self.unit.symbol)
        else:
            quantity_converted = quantity.to(self.unit.symbol)
        
        return quantity_converted.magnitude
    
    def convert_value_to_units(self, value, to_unit):
        if to_unit.symbol in TEMPERATURE_UNITS:
            quantity = units.Quantity(value, self.unit.symbol)
        else:
            quantity = value * self.unit.pint_unit
        # use custom unit context if set
        # Useful for converting units that are not directly convertible  using pint,
        # like precipitation (from mm -> kg/m²)
        if self.custom_unit_context:
            with units.context(self.custom_unit_context):
                quantity_converted = quantity.to(to_unit.symbol)
        else:
            quantity_converted = quantity.to(to_unit.symbol)
        
        return quantity_converted.magnitude


@register_setting
class AdlSettings(ClusterableModel, BaseSiteSetting):
    country = CountryField(blank_label=_("Select Country"), verbose_name=_("Country"))
    
    hourly_aggregation_interval = models.PositiveIntegerField(default=10, verbose_name=_("Hourly Aggregation Interval "
                                                                                         "in Minutes"), )
    
    daily_aggregation_time = models.TimeField(default="00:00", verbose_name=_("Daily Aggregation Time"))
    
    aggregate_from_date = models.DateTimeField(blank=True, null=True, verbose_name=_("Aggregate Start Date"),
                                               help_text=_("Date to start aggregation from. "
                                                           "Leave empty to use the current date and time"))
    
    panels = [
        FieldPanel("country", widget=CountrySelectWidget()),
        FieldPanel("hourly_aggregation_interval"),
        FieldPanel("daily_aggregation_time"),
        FieldPanel("aggregate_from_date"),
    ]
    
    class Meta:
        verbose_name = _("WIS2Box ADL Settings")
        verbose_name_plural = _("WIS2Box ADL Settings")


class OscarSurfaceStationLocal(models.Model):
    name = models.CharField(max_length=255, verbose_name=_("Name"), help_text=_("Name of the station"))
    wigos_id = models.CharField(max_length=255, verbose_name=_("WIGOS ID"), help_text=_("WIGOS ID of the station"),
                                unique=True)
    latitude = models.FloatField(verbose_name=_("Latitude"), help_text=_("Latitude of the station"))
    longitude = models.FloatField(verbose_name=_("Longitude"), help_text=_("Longitude of the station"))
    elevation = models.FloatField(verbose_name=_("Elevation"), help_text=_("Elevation of the station"))
    
    def __str__(self):
        return self.wigos_id


class NetworkConnection(PolymorphicModel, ClusterableModel):
    name = models.CharField(max_length=255, unique=True, verbose_name=_("Name"), )
    network = models.ForeignKey(Network, on_delete=models.CASCADE, verbose_name=_("Network"))
    plugin = models.CharField(max_length=255, verbose_name=_("Plugin"),
                              help_text=_("Plugin to use for this network"))
    plugin_processing_enabled = models.BooleanField(default=True, verbose_name=_("Plugin Auto Processing Enabled"),
                                                    help_text=_("If unchecked, the plugin will not run automatically"))
    plugin_processing_interval = models.PositiveIntegerField(default=15,
                                                             verbose_name=_("Plugin Auto Processing Interval "
                                                                            "in Minutes"),
                                                             help_text=_("How often the plugin should run, in minutes"),
                                                             validators=[
                                                                 MaxValueValidator(30),
                                                                 MinValueValidator(1)
                                                             ])
    is_daily_data = models.BooleanField(default=False, verbose_name=_("Is Daily Data"),
                                        help_text=_("Check to mark data from this connection as daily data"))
    
    panels = [
        FieldPanel("name"),
        FieldPanel("network"),
        MultiFieldPanel([
            FieldPanel('plugin', widget=PluginSelectWidget),
            FieldPanel("plugin_processing_enabled"),
            FieldPanel("plugin_processing_interval"),
        ], heading=_("Plugin Configuration")),
        FieldPanel("is_daily_data"),
    ]
    
    class Meta:
        verbose_name = _("Network Connection")
        verbose_name_plural = _("Network Connections")
    
    def __str__(self):
        return self.name


class StationLink(PolymorphicModel):
    network_connection = models.ForeignKey(NetworkConnection, on_delete=models.CASCADE,
                                           verbose_name=_("Network Connection"),
                                           related_name="station_links")
    station = models.ForeignKey(Station, on_delete=models.CASCADE, verbose_name=_("Station"))
    
    panels = [
        MultiFieldPanel([
            FieldPanel("network_connection"),
            FieldPanel("station"),
        ], heading=_("Base"))
    ]
    
    class Meta:
        unique_together = ['network_connection', 'station']


@register_snippet
class ObservationRecord(TimescaleModel, ClusterableModel):
    # time field is inherited from TimescaleModel. We use it to store the observation time of the data
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    station = models.ForeignKey(Station, on_delete=models.CASCADE, verbose_name=_("Station"))
    connection = models.ForeignKey(NetworkConnection, on_delete=models.CASCADE, verbose_name=_("Network Connection"),
                                   related_name="observation_records")
    parameter = models.ForeignKey(DataParameter, on_delete=models.CASCADE, verbose_name=_("Parameter"))
    value = models.FloatField(verbose_name=_("Value"))
    is_daily = models.BooleanField(default=False, verbose_name=_("Is Daily"))
    
    class Meta:
        verbose_name = _("Observation Record")
        verbose_name_plural = _("Observation Records")
        ordering = ['-time']
        constraints = [
            models.UniqueConstraint(
                fields=['time', 'station', 'connection', 'parameter'],
                name='unique_station_conn_param_obs_record'
            )
        ]
    
    @property
    def utc_time(self):
        return dj_timezone.localtime(self.time, timezone.utc)
    
    def __str__(self):
        return f"{self.station.name} - {self.utc_time} - {self.parameter.name} - {self.value}"


class AggregatedObservationRecord(TimescaleModel, ClusterableModel):
    # time field is inherited from TimescaleModel. We use it to store the observation time of the data
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    station = models.ForeignKey(Station, on_delete=models.CASCADE, verbose_name=_("Station"))
    parameter = models.ForeignKey(DataParameter, on_delete=models.CASCADE, verbose_name=_("Parameter"))
    min_value = models.FloatField(verbose_name=_("Min Value"))
    max_value = models.FloatField(verbose_name=_("Max Value"))
    avg_value = models.FloatField(verbose_name=_("Avg Value"))
    sum_value = models.FloatField(verbose_name=_("Sum Value"))
    records_count = models.PositiveIntegerField(verbose_name=_("Records Count"))
    
    def __str__(self):
        return f"{self.station.name} - {self.time} - {self.parameter.name}"
    
    class Meta:
        abstract = True


@register_snippet
class HourlyAggregatedObservationRecord(AggregatedObservationRecord):
    connection = models.ForeignKey(NetworkConnection, on_delete=models.CASCADE, verbose_name=_("Network Connection"),
                                   related_name="hourly_aggregated_observation_records")


@register_snippet
class DailyAggregatedObservationRecord(AggregatedObservationRecord):
    connection = models.ForeignKey(NetworkConnection, on_delete=models.CASCADE, verbose_name=_("Network Connection"),
                                   related_name="daily_aggregated_observation_records")


class DispatchChannel(PolymorphicModel, ClusterableModel):
    AGGREGATION_PERIOD_CHOICES = (
        ("hourly", _("Hourly")),
        ("daily", _("Daily")),
    )
    
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    network_connection = models.ForeignKey(NetworkConnection, on_delete=models.CASCADE,
                                           verbose_name=_("Network Connection"),
                                           related_name="dispatch_channels")
    enabled = models.BooleanField(default=True, verbose_name=_("Enabled"))
    data_check_interval = models.PositiveIntegerField(default=10, verbose_name=_("Data Check Interval in Minutes"),
                                                      help_text=_(
                                                          "How often the channel should check the database for new "
                                                          "data, in minutes"),
                                                      validators=[
                                                          MaxValueValidator(30),
                                                          MinValueValidator(1)
                                                      ])
    
    send_aggregated_data = models.BooleanField(default=False, verbose_name=_("Send Aggregated Data"))
    aggregation_period = models.CharField(max_length=255, blank=True, null=True, choices=AGGREGATION_PERIOD_CHOICES,
                                          default="hourly", verbose_name=_("Aggregation Period"))
    
    base_panels = [
        MultiFieldPanel([
            FieldPanel("name"),
            FieldPanel("network_connection"),
            FieldPanel("enabled"),
            FieldPanel("data_check_interval"),
            FieldPanel("send_aggregated_data"),
            FieldPanel("aggregation_period"),
        ], heading=_("Base")),
    ]
    
    parameter_panels = [
        InlinePanel("parameter_mappings", label=_("Parameter Mappings"), heading=_("Parameter Mappings")),
    ]
    
    def send_data(self, data_records):
        raise NotImplementedError("Method send_data must be implemented in the subclass")
    
    def get_data_records(self):
        data_records = get_dispatch_channel_data(self)
        
        return data_records
    
    def dispatch(self):
        data_records = self.get_data_records()
        self.send_data(data_records)


class DispatchChannelParameterMapping(Orderable):
    AGGREGATION_MEASURE_CHOICES = (
        ("avg_value", _("Average Value")),
        ("sum_value", _("Sum Value")),
        ("min_value", _("Minimum Value")),
        ("max_value", _("Maximum Value")),
    )
    
    dispatch_channel = ParentalKey(DispatchChannel, on_delete=models.CASCADE, related_name="parameter_mappings")
    parameter = models.ForeignKey(DataParameter, on_delete=models.CASCADE, verbose_name=_("Parameter"))
    channel_parameter = models.CharField(max_length=255, verbose_name=_("Channel Parameter"),
                                         help_text=_("Parameter name in the channel"))
    channel_unit = models.ForeignKey(Unit, blank=True, null=True, on_delete=models.CASCADE,
                                     verbose_name=_("Channel Unit"),
                                     help_text=_("Unit of the parameter in the channel. Leave empty if the same"))
    
    aggregation_measure = models.CharField(max_length=255, default="avg_value",
                                           choices=AGGREGATION_MEASURE_CHOICES,
                                           verbose_name=_("Aggregation Measure"), )
    
    class Meta:
        unique_together = ['dispatch_channel', 'parameter']
    
    def __str__(self):
        return f"{self.dispatch_channel.name} - {self.parameter.name}"


class Wis2BoxUpload(DispatchChannel):
    storage_endpoint = models.CharField(max_length=255, verbose_name=_("Storage Endpoint"))
    storage_username = models.CharField(max_length=255, verbose_name=_("Storage Username"))
    storage_password = models.CharField(max_length=255, verbose_name=_("Storage Password"))
    secure = models.BooleanField(default=False, verbose_name=_("Use Secure Connection"),
                                 help_text=_("If checked, HTTPS connection will be used,otherwise HTTP"))
    dataset_id = models.CharField(max_length=255, verbose_name=_("Dataset ID"))
    
    panels = DispatchChannel.base_panels + [
        MultiFieldPanel([
            FieldPanel("storage_endpoint"),
            FieldPanel("storage_username"),
            FieldPanel("storage_password"),
            FieldPanel("secure"),
            FieldPanel("dataset_id"),
        ], heading=_("Wis2Box Storage Configuration")),
    ] + DispatchChannel.parameter_panels
    
    class Meta:
        verbose_name = _("WIS2BOX Upload")
        verbose_name_plural = _("WIS2BOX Uploads")
    
    def __str__(self):
        return self.name
    
    def send_data(self, data_records):
        upload_to_wis2box(self, data_records)
    
    def connection_details(self):
        return {
            "storage_endpoint": self.storage_endpoint,
            "storage_username": self.storage_username,
            "storage_password": self.storage_password,
            "secure": self.secure,
            "dataset_id": self.dataset_id,
        }


@register_snippet
class StationChannelDispatchStatus(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    channel = models.ForeignKey(DispatchChannel, on_delete=models.CASCADE, verbose_name=_("Channel"))
    station = models.ForeignKey(Station, on_delete=models.CASCADE, verbose_name=_("Station"))
    last_sent_obs_time = models.DateTimeField(blank=True, null=True, verbose_name=_("Last Send Observation Time"))
    
    class Meta:
        verbose_name = _("Station Channel Dispatch Status")
        verbose_name_plural = _("Station Channel Dispatch Status")
        constraints = [
            models.UniqueConstraint(fields=['channel', 'station'], name='unique_channel_station_dispatch_status')
        ]
    
    def __str__(self):
        return f"{self.station.name} - {self.channel.name} - {self.last_sent_obs_time}"


@receiver(post_save, sender=AdlSettings)
def update_aggregation_period_tasks(sender, instance, **kwargs):
    create_or_update_aggregation_periodic_tasks(instance)
