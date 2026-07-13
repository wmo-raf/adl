from datetime import timezone
from enum import IntFlag, auto

from django import forms
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _
from django_countries.fields import CountryField
from django_countries.widgets import CountrySelectWidget
from enum_intflagfield import IntFlagField
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel
from polymorphic.models import PolymorphicModel
from timescale.db.models.models import TimescaleModel
from timezone_field import TimeZoneField
from wagtail.admin.panels import FieldPanel, TabbedInterface, ObjectList, InlinePanel
from wagtail.admin.panels import MultiFieldPanel
from wagtail.contrib.settings.models import BaseSiteSetting
from wagtail.contrib.settings.registry import register_setting
from wagtail.fields import StreamField
from wagtail.models import Orderable
from wagtail.snippets.models import register_snippet
from wagtailgeowidget.panels import LeafletPanel
from wagtailiconchooser.widgets import IconChooserWidget

from adl.core.registries import plugin_registry
from .blocks import QCChecksStreamBlock
from .dispatchers import get_dispatch_channel_data
from .dispatchers.wis2box import upload_to_wis2box, test_wis2box_connection
from .units import units, validate_unit, TEMPERATURE_UNITS
from .utils import (
    validate_as_integer,
    get_custom_unit_context_entries
)
from .widgets import PluginSelectWidget


class Network(models.Model):
    """
    An organisational grouping of stations sharing the same vendor type or
    collection method.

    A network carries no ingestion logic itself — it exists to scope station
    lists in the admin and to group :class:`NetworkConnection` instances.
    Examples: "National AWS Network", "TAHMO Stations", "Manual Synoptic Stations".
    """
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
    """
    A physical observing point with full WMO WIGOS identification metadata.

    Each station belongs to one :class:`Network` and is identified by a
    four-component WIGOS Station Identifier (WSI). The :attr:`wigos_id`
    property returns the formatted WSI string. Stations are linked to upstream
    data sources via :class:`StationLink` instances, and observations are
    stored in :class:`ObservationRecord` keyed by station.

    Location is stored as a PostGIS ``PointField`` (longitude, latitude).
    Sensor height fields (thermometer, anemometer, rain gauge, barometer) are
    used when encoding observations into WMO formats such as BUFR.
    """
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
        return f"{self.name} - {self.network}"
    
    @property
    def wigos_id(self):
        return f"{self.wsi_series}-{self.wsi_issuer}-{self.wsi_issue_number}-{self.wsi_local}"


class Unit(models.Model):
    """
    A unit of measurement backed by the `pint <https://pint.readthedocs.io>`_
    unit registry.
    
    The ``symbol`` field must be a valid pint symbol. ADL uses pint to drive
    automatic unit conversion when observations arrive in a unit that differs
    from a :class:`DataParameter`'s canonical unit. Common valid symbols:
    ``degC``, ``K``, ``m/s``, ``km/h``, ``mm``, ``hPa``, ``Pa``, ``%``,
    ``W/m^2``.
    
    .. important::
       If a unit conversion fails silently during ingestion, verify that the
       symbol is recognised by pint before looking elsewhere.
       """
    name = models.CharField(max_length=255, verbose_name=_("Name"), help_text=_("Name of the unit"), unique=True)
    symbol = models.CharField(max_length=255, verbose_name=_("Symbol"), help_text=_("Symbol of the unit"),
                              validators=[validate_unit], unique=True)
    description = models.TextField(verbose_name=_("Description"), blank=True, null=True,
                                   help_text=_("Description of the unit"))
    
    panels = [
        FieldPanel("name"),
        FieldPanel("symbol"),
        FieldPanel("description"),
    ]
    
    class Meta:
        verbose_name = _("Unit")
        verbose_name_plural = _("Units")
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    @property
    def pint_unit(self):
        return units(self.symbol)
    
    def get_registry_unit(self):
        unit = self.pint_unit.u
        return str(unit)
    
    get_registry_unit.short_description = _("Unit Registry")


class DataParameter(ClusterableModel):
    """
    ADL's canonical representation of a measurable meteorological or
    environmental variable.

    A ``DataParameter`` names a variable (e.g. ``air_temperature``), declares
    the :class:`Unit` in which values are stored, and drives automatic unit
    conversion when observations arrive in a different unit. It also holds the
    QC check configuration that is applied to every incoming value for this
    parameter.

    **Unit conversion** is performed by :meth:`convert_value_from_units` and
    :meth:`convert_value_to_units` using pint. For conversions that are not
    dimensionally straightforward (e.g. precipitation ``mm`` → ``kg/m²``),
    set ``custom_unit_context`` to the appropriate pint context name.

    **Aggregation** of stored observations into hourly summaries uses
    ``aggregation_method``. Use ``circular`` for angular variables like wind
    direction to avoid wrap-around errors (e.g. averaging 350° and 10° should
    give 0°, not 180°).

    .. warning::
        Changing the ``unit`` of a parameter that already has
        :class:`ObservationRecord` rows will raise a ``ValidationError``.
        Create a new parameter instead, or delete the existing records first.
        """
    CATEGORY_CHOICES = [
        ("meteorological", _("Meteorological")),
        ("environmental", _("Environmental")),
        ("health", _("Station Health")),
        ("communication", _("Communication")),
    ]
    
    AGGREGATION_METHOD_CHOICES = [
        ("standard", _("Standard (Min/Max/Avg/Sum)")),
        ("circular", _("Circular Mean (for angular data like wind direction)")),
    ]
    
    name = models.CharField(max_length=255, verbose_name=_("Name"), help_text=_("Name of the variable"), unique=True)
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, verbose_name=_("Unit"),
                             help_text=_("Unit of the variable"))
    description = models.TextField(verbose_name=_("Description"), blank=True, null=True,
                                   help_text=_("Description of the variable"))
    icon = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name=_("Icon"),
        help_text=_("Icon displayed alongside this parameter in dashboards and widgets"),
    )
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default="meteorological",
                                verbose_name=_("Category"), help_text=_("Type of parameter"))
    custom_unit_context = models.CharField(max_length=255, blank=True, null=True,
                                           choices=get_custom_unit_context_entries,
                                           verbose_name=_("Custom Unit Conversion Context"),
                                           help_text=_("Context of the unit"))
    aggregation_method = models.CharField(
        max_length=20,
        choices=AGGREGATION_METHOD_CHOICES,
        default="standard",
        verbose_name=_("Aggregation Method"),
        help_text=_(
            "How to aggregate this parameter in hourly/daily summaries. Use 'Circular Mean' for angular measurements like wind direction.")
    )
    is_coded = models.BooleanField(
        default=False,
        verbose_name=_("Is Coded Value"),
        help_text=_(
            "Check if values are WMO integer lookup-table codes rather than physical measurements "
            "(e.g. cloud cover in oktas, cloud type, present weather code). "
            "Pint unit conversion is skipped for coded parameters. "
            "The manual entry form renders a dropdown instead of a number input."
        ),
    )
    wmo_code_table = models.CharField(
        max_length=10,
        blank=True,
        default='',
        verbose_name=_("WMO Code Table"),
        help_text=_(
            "WMO code table identifier used to render dropdown choices in the entry form "
            "(e.g. '2700' for cloud cover in oktas, '0513' for low cloud type CL). "
            "Leave blank for physical-quantity parameters."
        ),
    )
    
    modified_at = models.DateTimeField(auto_now=True)
    qc_checks = StreamField(
        QCChecksStreamBlock(),
        null=True,
        blank=True,
        verbose_name=_("Quality Control Checks"),
        help_text=_("Configure automatic data quality validation rules for this parameter.")
    )
    
    panels = [
        FieldPanel("name"),
        FieldPanel("unit"),
        FieldPanel("description"),
        FieldPanel("icon", widget=IconChooserWidget),
        FieldPanel("category"),
        FieldPanel("custom_unit_context"),
        FieldPanel("aggregation_method"),
        FieldPanel("is_coded"),
        FieldPanel("wmo_code_table"),
        FieldPanel("qc_checks"),
    ]
    
    class Meta:
        verbose_name = _("Data Parameter")
        verbose_name_plural = _("Data Parameters")
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} - {self.unit.symbol}"
    
    def clean(self, *args, **kwargs):
        if not self.pk:
            return
        
        try:
            old_instance = DataParameter.objects.only("unit").get(pk=self.pk)
        except ObjectDoesNotExist:
            return
        
        if old_instance.unit_id != self.unit_id:
            if ObservationRecord.objects.filter(parameter_id=self.pk).exists():
                raise ValidationError({
                    "unit": _(
                        "Cannot change the unit of a parameter that already has observation records. "
                        "Please delete them before changing the unit."
                    )
                })
    
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
    
    daily_aggregation_time = models.TimeField(default="00:00", verbose_name=_("Daily Aggregation Time"))
    
    organisation_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name=_("Organisation Name"),
        help_text=_("Displayed in the footer of widget display pages"),
    )
    logo = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        verbose_name=_("Logo"),
        help_text=_("Displayed in the footer of widget display pages"),
    )
    
    panels = [
        FieldPanel("country", widget=CountrySelectWidget()),
        FieldPanel("organisation_name"),
        FieldPanel("logo"),
    ]
    
    class Meta:
        verbose_name = _("ADL Settings")
        verbose_name_plural = _("ADL Settings")


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
    """
    Configuration for one upstream data integration — credentials, schedule,
    timezone defaults, and the plugin type that performs ingestion.
    
    ``NetworkConnection`` is a Django-polymorphic base class. Each plugin
    defines a concrete subclass that adds its own credential fields (API keys,
    FTP details, database URLs, etc.). ADL uses the ``plugin`` field to look up
    the registered :class:`~adl.core.registries.Plugin` instance at runtime.
    
    Celery Beat triggers :meth:`collect_data` on the interval set by
    ``plugin_processing_interval``. Setting ``plugin_processing_enabled`` to
    ``False`` pauses ingestion for the entire connection without deleting any
    configuration.
    
    .. important::
       Plugin subclasses **must** set ``station_link_model_string_label`` to
       the ``"app_label.ModelName"`` string of their
       :class:`StationLink` subclass. Without this, station links will not
       appear in the admin and ingestion will silently do nothing.
    """
    
    name = models.CharField(max_length=255, unique=True, verbose_name=_("Name"), )
    network = models.ForeignKey(Network, on_delete=models.CASCADE, verbose_name=_("Network"))
    plugin = models.CharField(max_length=255, verbose_name=_("Plugin"),
                              help_text=_("Plugin to use for this network"))
    plugin_processing_enabled = models.BooleanField(default=True, verbose_name=_("Active"),
                                                    help_text=_("If unchecked, the plugin will NOT run automatically"))
    plugin_processing_interval = models.PositiveIntegerField(default=15, verbose_name=_("Interval"),
                                                             help_text=_("How often the plugin should run, in minutes"),
                                                             validators=[
                                                                 MaxValueValidator(30),
                                                                 MinValueValidator(1)
                                                             ])
    stations_timezone = TimeZoneField(default='UTC', verbose_name=_("Stations Timezone"),
                                      help_text=_("Default Timezone of the stations in this network connection"))
    batch_size = models.PositiveIntegerField(default=10, verbose_name=_("Processing Batch Size"),
                                             help_text=_("Number of stations to process in a single batch"))
    is_daily_data = models.BooleanField(default=False, verbose_name=_("Is Daily Data"),
                                        help_text=_("Check to mark data from this connection as daily data"))
    sort_order = models.PositiveIntegerField(default=0, verbose_name=_("Sort Order"),
                                             help_text=_("Order in which the connections are displayed"))
    
    panels = [
        FieldPanel("name"),
        FieldPanel("network"),
        FieldPanel("stations_timezone"),
        MultiFieldPanel([
            FieldPanel('plugin', widget=PluginSelectWidget),
            FieldPanel("plugin_processing_enabled"),
            FieldPanel("plugin_processing_interval"),
            FieldPanel("batch_size"),
        ], heading=_("Plugin Configuration")),
        FieldPanel("is_daily_data"),
        FieldPanel("sort_order"),
    ]
    
    class Meta:
        verbose_name = _("Network Connection")
        verbose_name_plural = _("Network Connections")
        ordering = ["sort_order"]
    
    def __str__(self):
        return self.name
    
    @property
    def enabled(self):
        return self.plugin_processing_enabled
    
    @property
    def interval(self):
        return self.plugin_processing_interval
    
    def get_plugin(self):
        plugin_type = self.plugin
        plugin = plugin_registry.get(plugin_type)
        return plugin
    
    @property
    def plugin_name(self):
        plugin = self.get_plugin()
        return plugin.label
    
    def collect_data(self, initial_start_date=None):
        plugin = self.get_plugin()
        if not plugin:
            raise ValueError(f"Plugin {self.plugin} not found in the registry.")
        return plugin.run_process(self, initial_start_date=initial_start_date)
    
    @property
    def edit_url(self):
        from adl.core.utils import get_url_for_connection
        return get_url_for_connection(self, "edit", takes_args=True)
    
    @property
    def delete_url(self):
        from adl.core.utils import get_url_for_connection
        return get_url_for_connection(self, "delete", takes_args=True)
    
    @property
    def station_link_url(self):
        from adl.core.utils import get_connection_station_link_url
        return get_connection_station_link_url(self)


class StationLink(PolymorphicModel, ClusterableModel):
    """
    Binds one :class:`Station` to one :class:`NetworkConnection` and holds all
    per-station ingestion configuration.

    ``StationLink`` is a Django-polymorphic base class. Each plugin defines a
    concrete subclass that adds the upstream station identifier (e.g. a TAHMO
    station code, an FTP filename pattern) and per-station variable mappings.

    The effective timezone for a station link is resolved by the :attr:`timezone`
    property: it returns the connection's ``stations_timezone`` when
    ``use_connection_timezone`` is ``True``, otherwise the per-station
    ``timezone_info``. ADL uses this timezone when computing date windows and
    normalizing observation timestamps.

    Setting ``enabled`` to ``False`` causes :meth:`~adl.core.registries.Plugin.run_process`
    to skip this station without affecting any other stations on the same
    connection.
    """
    network_connection = models.ForeignKey(NetworkConnection, on_delete=models.CASCADE,
                                           verbose_name=_("Network Connection"),
                                           related_name="station_links")
    station = models.ForeignKey(Station, on_delete=models.CASCADE, verbose_name=_("Station"))
    
    enabled = models.BooleanField(default=True, verbose_name=_("Enabled"),
                                  help_text=_("If unchecked, this station  will not be processed"))
    use_connection_timezone = models.BooleanField(default=True,
                                                  verbose_name=_("Use Connection Timezone"),
                                                  help_text=_("If checked, the station will use the timezone from the "
                                                              "network connection. If unchecked, it will use the "
                                                              "station's set timezone that will be appear below"))
    timezone_info = TimeZoneField(default='UTC', verbose_name=_("Station Timezone"),
                                  help_text=_("Timezone used by the station for recording observations"))
    
    aggregate_from_date = models.DateTimeField(blank=True, null=True, verbose_name=_("Aggregation Start Date"),
                                               help_text=_("Date to start aggregation from. "
                                                           "Leave empty to use the current date and time"))
    modified_at = models.DateTimeField(auto_now=True)
    
    panels = [
        MultiFieldPanel([
            FieldPanel("network_connection"),
            FieldPanel("station"),
            FieldPanel("enabled"),
            FieldPanel("use_connection_timezone"),
            FieldPanel("timezone_info"),
        ], heading=_("Base"))
    ]
    
    aggregation_panels = [
        FieldPanel("aggregate_from_date"),
    ]
    
    class Meta:
        unique_together = ['network_connection', 'station']
    
    def __str__(self):
        return f"{self.station.name} - {self.network_connection.name}"
    
    @property
    def timezone(self):
        """
        Returns the timezone for the station link.
        If use_connection_timezone is True, it returns the timezone from the network connection.
        Otherwise, it returns the station's timezone.
        """
        if self.use_connection_timezone:
            return self.network_connection.stations_timezone
        return self.timezone_info
    
    def get_variable_mappings(self):
        """
        Returns the variable mappings for the station link.
        This method should be overridden in subclasses to provide specific mappings.
        """
        return []
    
    def get_first_collection_date(self):
        """
        Returns the first collection date for the station link.
        This method should be overridden in subclasses to provide specific logic.
        """
        return None
    
    def get_extra_model_admin_buttons(self, classname=None):
        return []
    
    def fetch_latest_data(self):
        """
        Fetches latest data for the station link using the network connection's plugin.
        """
        
        # get latest date
        start_date, end_date = self.plugin.get_dates_for_station(self, latest=True)
        
        # get data records, using the latest dates
        data_records = self.plugin.get_station_data(self, start_date=start_date, end_date=end_date)
        
        return {
            "start_date": start_date,
            "end_date": end_date,
            "data_records": data_records
        }
    
    def fetch_and_save_latest_data(self):
        """
        Fetches latest data for the station link and saves it to the database.
        """
        fetch_result = self.fetch_latest_data()
        data_records = fetch_result.get("data_records", [])
        
        saved_records = self.plugin.save_data_records(self, data_records)
        
        return {
            "start_date": fetch_result.get("start_date"),
            "end_date": fetch_result.get("end_date"),
            "fetched_count": len(data_records),
            "saved_count": len(saved_records),
            "saved_records": saved_records,
        }
    
    @property
    def plugin(self):
        return self.network_connection.get_plugin()
    
    @property
    def wigos_id(self):
        return self.station.wigos_id
    
    def get_dispatch_channels(self):
        """
        A channel includes this station iff:
          - station.network_connection is among channel.network_connections
          - NOT explicitly disabled for that channel
        """
        return DispatchChannel.objects.filter(
            network_connections=self.network_connection
        ).exclude(
            dispatch_station_links__station_link=self,
            dispatch_station_links__disabled=True,
        ).distinct()


class QCStatus(models.IntegerChoices):
    """
    Integer enumeration of quality control outcomes stored on each
    :class:`ObservationRecord`.

    ``NOT_EVALUATED`` is the default and means no QC checks are configured
    for the parameter. ``SUSPECT`` means one or more checks failed but the
    value was retained. Failure details are stored in :class:`QCMessage`.
    """
    
    PASS = 0, "Pass"
    SUSPECT = 1, "Suspect"
    FAIL = 2, "Fail"
    MISSING = 3, "Missing"
    ESTIMATED = 4, "Estimated"
    CORRECTED = 5, "Corrected"
    NOT_EVALUATED = 6, "Not evaluated"


class QCBits(IntFlag):
    """
    Bitmask flags indicating which QC checks failed for an
    :class:`ObservationRecord`.
    
    Multiple bits can be set simultaneously when more than one check fails.
    The bitmask is stored alongside :class:`QCStatus` — a non-zero
    ``qc_bits`` value always corresponds to a ``qc_status`` of ``SUSPECT``.
    Detailed failure messages for each set bit are stored in
    :class:`QCMessage`.
    """
    RANGE = auto()
    STEP = auto()
    PERSISTENCE = auto()
    SPIKE = auto()


@register_snippet
class ObservationRecord(TimescaleModel, ClusterableModel):
    wagtail_reference_index_ignore = True
    """
    The atomic unit of stored observation data in ADL.
    
    Backed by `TimescaleDB <https://www.timescale.com>`_ for efficient
    time-series queries. The ``time`` field (inherited from ``TimescaleModel``)
    is always stored as UTC. Use the :attr:`utc_time` property to retrieve it
    as a timezone-aware UTC datetime.
    
    Each row is uniquely identified by ``(time, station, connection,
    parameter)``. ADL's ingestion pipeline uses
    ``bulk_create(update_conflicts=True)`` against this constraint, so
    re-ingesting an already-stored window updates the existing value rather
    than raising an error.
    
    QC results are stored as a bitmask (:class:`QCBits`) and a status code
    (:class:`QCStatus`). A ``qc_status`` of ``NOT_EVALUATED`` means no QC
    checks are configured for the parameter, not that the value failed.
    Failure messages are stored in related :class:`QCMessage` rows.`
    """
    
    # time field is inherited from TimescaleModel. We use it to store the observation time of the data
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    station = models.ForeignKey(Station, on_delete=models.CASCADE, verbose_name=_("Station"))
    connection = models.ForeignKey(NetworkConnection, on_delete=models.CASCADE, verbose_name=_("Network Connection"),
                                   related_name="observation_records")
    parameter = models.ForeignKey(DataParameter, on_delete=models.CASCADE, verbose_name=_("Parameter"))
    value = models.FloatField(verbose_name=_("Value"))
    is_daily = models.BooleanField(default=False, verbose_name=_("Is Daily"))
    qc_status = models.PositiveSmallIntegerField(
        choices=QCStatus.choices,
        default=QCStatus.NOT_EVALUATED
    )
    qc_bits = IntFlagField(choices=QCBits, default=0)
    qc_version = models.PositiveIntegerField(default=1)
    
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
        
        indexes = [
            models.Index(fields=['station', '-time']),
            models.Index(fields=['connection', 'station', '-time']),
        ]
    
    @property
    def utc_time(self):
        return dj_timezone.localtime(self.time, timezone.utc)
    
    def __str__(self):
        return f"{self.station.name} - {self.utc_time} - {self.parameter.name} - {self.value}"


@register_snippet
class QCMessage(models.Model):
    """
    A single QC failure message associated with one observation value.
    
    Created by the ingestion pipeline when a QC check fails. Multiple
    ``QCMessage`` rows can exist for the same observation time and parameter
    if more than one check failed. Keyed by ``obs_record_id`` and
    ``obs_time`` / ``station_id`` for efficient lookup without a direct
    foreign key to :class:`ObservationRecord` (which is a TimescaleDB
    hypertable and does not support standard FK constraints).
    """
    
    obs_record_id = models.BigIntegerField(db_index=True)
    obs_time = models.DateTimeField(db_index=True)
    station_id = models.IntegerField()
    parameter_id = models.IntegerField()
    check_type = models.PositiveIntegerField(choices=[(b.value, b.name) for b in QCBits])
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['obs_record_id']),
            models.Index(fields=['obs_time', 'station_id']),
        ]


@register_snippet
class HourlyObsAgg(models.Model):
    """
    Read-only TimescaleDB continuous aggregate view providing pre-computed
    hourly summaries of :class:`ObservationRecord` data.
    
    Backed by the database view ``obs_agg_1h_v``. Not a managed Django model
    — ADL does not create or migrate it directly; TimescaleDB maintains it
    incrementally from the underlying ``ObservationRecord`` hypertable.
    
    Use this model instead of querying ``ObservationRecord`` directly whenever
    you need hourly aggregates over large time ranges — it is significantly
    faster because the aggregates are pre-computed.
    
    The :attr:`time` property aliases ``bucket`` for API consistency with
    :class:`ObservationRecord`.
    """
    id = models.CharField(primary_key=True, max_length=32)  # md5 hex
    station = models.ForeignKey(Station, on_delete=models.DO_NOTHING)
    connection = models.ForeignKey(NetworkConnection, on_delete=models.DO_NOTHING)
    parameter = models.ForeignKey(DataParameter, on_delete=models.DO_NOTHING)
    bucket = models.DateTimeField()
    
    min_value = models.FloatField(null=True)
    max_value = models.FloatField(null=True)
    avg_value = models.FloatField(null=True)
    sum_value = models.FloatField(null=True)
    records_count = models.IntegerField()
    
    class Meta:
        managed = False
        ordering = ['-bucket', 'station']
        db_table = 'obs_agg_1h_v'
        indexes = [
            models.Index(fields=['station', 'connection', 'parameter', 'bucket']),
        ]
    
    def __str__(self):
        return f"{self.station.name} - {self.parameter.name} - {self.bucket} ({self.records_count} records)"
    
    @property
    def time(self):
        return self.bucket


class DispatchChannel(PolymorphicModel, ClusterableModel):
    """
    Base class for outbound data channels that push stored observations to
    external systems.

    ``DispatchChannel`` is a Django-polymorphic base class. Each destination
    type (e.g. :class:`Wis2BoxUpload`) subclasses it and implements
    :meth:`send_station_data`. ADL's dispatch Celery task calls
    :meth:`get_data_records_by_station` on a schedule to fetch observations
    that have not yet been sent, then calls :meth:`send_station_data` for
    each eligible station.

    A channel is linked to one or more :class:`NetworkConnection` instances
    via ``network_connections``. All stations on those connections are
    eligible for dispatch unless explicitly disabled via a
    :class:`DispatchChannelStationLink` row with ``disabled=True``.

    Parameter mappings (:class:`DispatchChannelParameterMapping`) translate
    ADL's internal parameter names and units to whatever the destination
    system expects, applying unit conversion and aggregation (avg, sum, min,
    max) as configured.
    """
    
    AGGREGATION_PERIOD_CHOICES = (
        ("hourly", _("Hourly")),
        # ("daily", _("Daily")),
    )
    
    name = models.CharField(max_length=255, verbose_name=_("Name"))
    network_connections = models.ManyToManyField(NetworkConnection,
                                                 verbose_name=_("Network Connections"),
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
    dispatch_timeout_seconds = models.PositiveIntegerField(default=300,
                                                           verbose_name=_("Dispatch Timeout in Seconds"),
                                                           help_text=_(
                                                               "Maximum time a single station dispatch may run "
                                                               "before it is terminated"),
                                                           validators=[
                                                               MinValueValidator(30),
                                                               MaxValueValidator(1800)
                                                           ])
    max_records_per_dispatch = models.PositiveIntegerField(default=500,
                                                           verbose_name=_("Maximum Records per Dispatch"),
                                                           help_text=_(
                                                               "Maximum number of records (observation times) sent "
                                                               "per station in a single dispatch run. A backlog is "
                                                               "drained incrementally across runs"),
                                                           validators=[
                                                               MinValueValidator(1),
                                                               MaxValueValidator(10000)
                                                           ])
    start_date = models.DateTimeField(blank=True, null=True, verbose_name=_("Starting date for the data to dispatch"),
                                      help_text=_("Leave blank to use the whole data period"))
    
    send_aggregated_data = models.BooleanField(default=False, verbose_name=_("Send Aggregated Data"))
    aggregation_period = models.CharField(max_length=255, blank=True, null=True, choices=AGGREGATION_PERIOD_CHOICES,
                                          default="hourly", verbose_name=_("Aggregation Period"))
    public_url = models.URLField(blank=True, null=True, verbose_name=_("Public URL"),
                                 help_text=_("Public URL of the channel,if available"))
    sort_order = models.PositiveIntegerField(default=0, verbose_name=_("Sort Order"),
                                             help_text=_("Order in which the connections are displayed"))
    
    base_panels = [
        MultiFieldPanel([
            FieldPanel("name"),
            FieldPanel("network_connections", widget=forms.CheckboxSelectMultiple),
            FieldPanel("enabled"),
            FieldPanel("data_check_interval"),
            FieldPanel("dispatch_timeout_seconds"),
            FieldPanel("max_records_per_dispatch"),
            FieldPanel("send_aggregated_data"),
            FieldPanel("aggregation_period"),
            FieldPanel("start_date"),
            FieldPanel("public_url"),
        ], heading=_("Base")),
        FieldPanel("sort_order"),
    ]
    
    class Meta:
        ordering = ["sort_order"]
    
    parameter_panels = [
        InlinePanel("parameter_mappings", label=_("Parameter Mappings"), heading=_("Parameter Mappings")),
    ]
    
    def __str__(self):
        return f"{self.name}"
    
    def get_parameter_mappings(self):
        return self.parameter_mappings.all()
    
    def get_parameter_mapping_values(self):
        channel_param_values = [pm.channel_parameter for pm in self.get_parameter_mappings()]
        return channel_param_values
    
    def send_station_data(self, station_link, station_data_records):
        raise NotImplementedError("Method send_station_data must be implemented in the subclass")

    def test_connection(self):
        """
        Probe whether the channel's destination is reachable and responsive.

        Subclasses override this with a short, bounded check against their
        destination (reachability + authentication). Implementations must
        never raise and must never block for more than ~10 seconds.

        :return: dict with keys ``ok`` (bool), ``supported`` (bool),
            ``message`` (str) and ``latency_ms`` (int or None).
        """
        return {
            "ok": False,
            "supported": False,
            "message": _("Connection test not supported for this channel type"),
            "latency_ms": None,
        }
    
    def get_data_records_by_station(self):
        data_records_by_station = get_dispatch_channel_data(self)
        return data_records_by_station
    
    def stations_allowed_to_send(self):
        """
        Eligible = station in this channel's networks AND not explicitly disabled
        """
        base_qs = StationLink.objects.filter(
            network_connection__in=self.network_connections.all()
        )
        
        # Explicit disables win
        qs = base_qs.exclude(
            dispatch_channel_links__dispatch_channel=self,
            dispatch_channel_links__disabled=True,
        )
        
        return qs.distinct()
    
    def clean_parameter_mapping(self, *args, **kwargs):
        pass
    
    @property
    def edit_url(self):
        from adl.core.utils import get_url_for_dispatch_channel
        return get_url_for_dispatch_channel(self, "edit", takes_args=True)
    
    @property
    def delete_url(self):
        from adl.core.utils import get_url_for_dispatch_channel
        return get_url_for_dispatch_channel(self, "delete", takes_args=True)


class DispatchChannelParameterMapping(Orderable):
    """
    Maps one ADL :class:`DataParameter` to the name and unit expected by a
    :class:`DispatchChannel` destination.
    
    Controls three things for each parameter sent through the channel:
    
    - **Name translation** — ``channel_parameter`` is the parameter name the
      destination system expects (e.g. ``total_precipitation_1_hour``).
    - **Unit conversion** — ``channel_unit`` is the unit the destination
      expects. Leave blank if it matches the parameter's canonical unit.
      ADL converts automatically using pint.
    - **Aggregation** — ``aggregation_measure`` determines how sub-hourly
      observations are collapsed before sending (average, sum, min, or max).
      Must match the physical meaning of the parameter: use ``sum_value`` for
      accumulated quantities like precipitation, ``avg_value`` for
      instantaneous quantities like temperature.
    """
    
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
    
    def clean(self):
        super(DispatchChannelParameterMapping, self).clean()
        
        if self.dispatch_channel_id:
            channel = self.dispatch_channel
            if hasattr(channel, "clean_parameter_mapping"):
                channel.clean_parameter_mapping(self)


class DispatchChannelStationLink(Orderable):
    """
    Explicitly disables one :class:`StationLink` from a specific
    :class:`DispatchChannel`.
    
    By default, all stations on a channel's ``network_connections`` are
    eligible for dispatch. Creating a ``DispatchChannelStationLink`` row with
    ``disabled=True`` excludes that station from the channel without removing
    it from the network or connection.
    """
    dispatch_channel = ParentalKey(DispatchChannel, on_delete=models.CASCADE, related_name="dispatch_station_links")
    station_link = models.ForeignKey(StationLink, on_delete=models.CASCADE, verbose_name=_("Station Link"),
                                     related_name="dispatch_channel_links")
    disabled = models.BooleanField(default=False, verbose_name=_("Disabled"))
    
    class Meta:
        unique_together = ['dispatch_channel', 'station_link']
    
    def __str__(self):
        return f"{self.dispatch_channel.name} - {self.station_link.station.name}"


class Wis2BoxUpload(DispatchChannel):
    """
    A :class:`DispatchChannel` that uploads observation data to a
    `wis2box <https://github.com/World-Meteorological-Organization/wis2box>`_
    MinIO storage endpoint in BUFR format for WMO Information System 2.0
    publication.

    Connects to the wis2box MinIO instance using ``storage_endpoint``,
    ``storage_username``, and ``storage_password``. The ``dataset_id``
    identifies the WIS2 dataset topic the data belongs to.

    Set ``secure=True`` when the storage endpoint uses HTTPS.
    """
    
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
    
    def send_station_data(self, station_link, data_records):
        return upload_to_wis2box(self, data_records)

    def test_connection(self):
        return test_wis2box_connection(self)
    
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
    """
    Tracks the last successfully dispatched observation time for each
    ``(station, channel)`` pair.

    Used by the dispatch pipeline to determine where to resume sending after
    a gap or restart — analogous to how :meth:`~adl.core.registries.Plugin.get_start_date_from_db`
    works for ingestion. One row per ``(channel, station)`` pair; updated
    after each successful dispatch batch.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    channel = models.ForeignKey(DispatchChannel, on_delete=models.CASCADE, verbose_name=_("Channel"),
                                related_name="dispatch_statuses")
    station = models.ForeignKey(Station, on_delete=models.CASCADE, verbose_name=_("Station"))
    last_sent_obs_time = models.DateTimeField(blank=True, null=True, verbose_name=_("Last Send Observation Time"))
    
    class Meta:
        verbose_name = _("Station Channel Dispatch Status")
        verbose_name_plural = _("Station Channel Dispatch Status")
        constraints = [
            models.UniqueConstraint(fields=['channel', 'station'], name='unique_channel_station_dispatch_status')
        ]
        # order by latest first
        ordering = ['-last_sent_obs_time']
    
    def __str__(self):
        return f"{self.station.name} - {self.channel.name} - {self.last_sent_obs_time}"


def status_from_bits(bits: QCBits) -> int:
    if bits == QCBits(0):
        return QCStatus.PASS
    return QCStatus.SUSPECT
