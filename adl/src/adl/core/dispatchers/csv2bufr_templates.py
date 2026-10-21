"""
csv2bufr templates a WIS2BOX Upload channel can produce CSV for.

wis2box turns uploaded CSV into BUFR with csv2bufr, using a mapping template
installed for the dataset. A WIS2BOX Upload channel must write CSV in exactly
the shape of that template, so each template is described here column by
column: the column name, the unit csv2bufr expects, the data type, and where
ADL gets the value from.

Templates are defined in code, not in the admin: a template only works when
the matching csv2bufr mapping is installed in wis2box, so each one is a
deliberate, versioned pairing. Core registers the AWS template, which is the
default; plugins can register more on ``csv2bufr_template_registry`` from
their app config's ``ready()``.
"""

from dataclasses import dataclass

from adl.core.registry import Instance, Registry
from adl.core.units import units_are_convertible

STATION = "station"
"""Filled from the :class:`~adl.core.models.Station`'s metadata."""

TIMESTAMP = "timestamp"
"""Filled from the observation time."""

OBSERVATION = "observation"
"""Filled from a parameter mapping. The only columns that can be mapped."""

DEFAULT_CSV2BUFR_TEMPLATE = "aws"


@dataclass(frozen=True)
class Csv2BufrColumn:
    """
    One column of a csv2bufr template.

    :param name: the CSV header, as csv2bufr reads it
    :param source: ``STATION``, ``TIMESTAMP`` or ``OBSERVATION``
    :param data_type: ``"integer"``, ``"decimal"`` or ``"string"``
    :param unit: pint symbol of the unit csv2bufr expects, or ``None`` for
        identifiers, code-table values and other unitless columns
    :param default_aggregation: for observation columns, the aggregation
        measure (as on ``DispatchChannelParameterMapping``) used when
        aggregated data is sent, unless the mapping overrides it
    :param section: for observation columns, the group the column is shown
        under in the admin
    :param window_hours: for observation columns covering more than one hour,
        the window length. Hourly aggregation cannot build these, so they need
        a source parameter already accumulated over that window
    :param unit_context: pint context needed to convert into ``unit``, e.g.
        ``"precipitation"`` for mm of rain into kg m-2
    """

    name: str
    source: str
    data_type: str
    unit: str = None
    default_aggregation: str = None
    section: str = None
    window_hours: int = None
    unit_context: str = None
    
    def get_unit_context(self, parameter):
        """The pint context for converting ``parameter`` into this column: the parameter's own, else the column's."""
        return parameter.get_unit_context(self.unit_context)
    
    def accepts_unit_of(self, parameter):
        """Whether ``parameter``'s values can be converted into this column's unit."""
        if not self.unit:
            return True
        return units_are_convertible(parameter.unit.symbol, self.unit, self.get_unit_context(parameter))


def station_column(name, data_type, unit=None):
    return Csv2BufrColumn(name=name, source=STATION, data_type=data_type, unit=unit)


def timestamp_column(name):
    return Csv2BufrColumn(name=name, source=TIMESTAMP, data_type="integer")


def observation_column(name, data_type, unit, section, default_aggregation="avg_value", window_hours=None,
                       unit_context=None):
    return Csv2BufrColumn(
        name=name,
        source=OBSERVATION,
        data_type=data_type,
        unit=unit,
        default_aggregation=default_aggregation,
        section=section,
        window_hours=window_hours,
        unit_context=unit_context,
    )


def precipitation_column(name, unit, default_aggregation="sum_value", window_hours=None):
    return observation_column(name, "decimal", unit, PRECIPITATION, default_aggregation=default_aggregation,
                              window_hours=window_hours, unit_context="precipitation")


class Csv2BufrTemplate(Instance):
    """
    A csv2bufr mapping template, described column by column in CSV order.
    """

    label = ""
    documentation_url = ""
    columns = ()

    @property
    def column_names(self):
        return [column.name for column in self.columns]

    @property
    def observation_columns(self):
        return [column for column in self.columns if column.source == OBSERVATION]
    
    def get_column(self, name):
        for column in self.columns:
            if column.name == name:
                return column
        return None

    def get_observation_column(self, name):
        column = self.get_column(name)
        if column and column.source == OBSERVATION:
            return column
        return None


PRESSURE = "pressure"
TEMPERATURE_HUMIDITY = "temperature_humidity"
GROUND_SNOW = "ground_snow"
PRECIPITATION = "precipitation"
WIND = "wind"
GUSTS = "gusts"


class AwsCsv2BufrTemplate(Csv2BufrTemplate):
    """
    The wis2box csv2bufr AWS template, for hourly automatic weather station
    reports.

    Columns, units and types follow
    https://training.wis2box.wis.wmo.int/csv2bufr-templates/aws-template/
    """

    type = "aws"
    label = "AWS"
    documentation_url = "https://training.wis2box.wis.wmo.int/csv2bufr-templates/aws-template/"
    columns = (
        station_column("wsi_series", "integer"),
        station_column("wsi_issuer", "integer"),
        station_column("wsi_issue_number", "integer"),
        station_column("wsi_local", "string"),
        station_column("wmo_block_number", "integer"),
        station_column("wmo_station_number", "integer"),
        station_column("station_type", "integer"),
        timestamp_column("year"),
        timestamp_column("month"),
        timestamp_column("day"),
        timestamp_column("hour"),
        timestamp_column("minute"),
        station_column("latitude", "decimal", "degree"),
        station_column("longitude", "decimal", "degree"),
        station_column("station_height_above_msl", "decimal", "m"),
        station_column("barometer_height_above_msl", "decimal", "m"),
        observation_column("station_pressure", "decimal", "Pa", PRESSURE),
        observation_column("msl_pressure", "decimal", "Pa", PRESSURE),
        # the template gives geopotential metres; pint has no such unit, and
        # gpm is numerically metres for this purpose
        observation_column("geopotential_height", "integer", "m", PRESSURE),
        station_column("thermometer_height", "decimal", "m"),
        observation_column("air_temperature", "decimal", "K", TEMPERATURE_HUMIDITY),
        observation_column("dewpoint_temperature", "decimal", "K", TEMPERATURE_HUMIDITY),
        observation_column("relative_humidity", "integer", "%", TEMPERATURE_HUMIDITY),
        station_column("method_of_ground_state_measurement", "integer"),
        observation_column("ground_state", "integer", None, GROUND_SNOW, default_aggregation="max_value"),
        station_column("method_of_snow_depth_measurement", "integer"),
        observation_column("snow_depth", "decimal", "m", GROUND_SNOW),
        precipitation_column("precipitation_intensity", "kg/m^2/h", default_aggregation="avg_value"),
        station_column("anemometer_height", "decimal", "m"),
        station_column("time_period_of_wind", "integer", "minute"),
        observation_column("wind_direction", "integer", "degree", WIND),
        observation_column("wind_speed", "decimal", "m/s", WIND),
        observation_column("maximum_wind_gust_direction_10_minutes", "integer", "degree", GUSTS),
        observation_column("maximum_wind_gust_speed_10_minutes", "decimal", "m/s", GUSTS,
                           default_aggregation="max_value"),
        observation_column("maximum_wind_gust_direction_1_hour", "integer", "degree", GUSTS),
        observation_column("maximum_wind_gust_speed_1_hour", "decimal", "m/s", GUSTS,
                           default_aggregation="max_value"),
        observation_column("maximum_wind_gust_direction_3_hours", "integer", "degree", GUSTS, window_hours=3),
        observation_column("maximum_wind_gust_speed_3_hours", "decimal", "m/s", GUSTS,
                           default_aggregation="max_value", window_hours=3),
        station_column("rain_sensor_height", "decimal", "m"),
        precipitation_column("total_precipitation_1_hour", "kg/m^2"),
        precipitation_column("total_precipitation_3_hours", "kg/m^2", window_hours=3),
        precipitation_column("total_precipitation_6_hours", "kg/m^2", window_hours=6),
        precipitation_column("total_precipitation_12_hours", "kg/m^2", window_hours=12),
        precipitation_column("total_precipitation_24_hours", "kg/m^2", window_hours=24),
    )


class Csv2BufrTemplateRegistry(Registry):
    name = "csv2bufr_template"

    def get_choices(self):
        return [(template.type, template.label) for template in self.get_all()]


csv2bufr_template_registry = Csv2BufrTemplateRegistry()
csv2bufr_template_registry.register(AwsCsv2BufrTemplate())


def get_csv2bufr_template_choices():
    return csv2bufr_template_registry.get_choices()
