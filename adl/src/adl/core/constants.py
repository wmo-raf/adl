from django.utils.translation import gettext_lazy as _

# Adapted from https://training.wis2box.wis.wmo.int/practical-sessions/converting-csv-data-to-bufr/
# with some modifications
STATION_ATTRIBUTES = {
    "station_id": {
        "label": _("Station ID"),
        "description": _("Unique Station Identifier"),
        "type": "text",
        "data_type": "Character",
        "required": True,
    },
    "name": {
        "label": _("Station Name"),
        "description": _("Station Name"),
        "type": "text",
        "data_type": "Character",
        "required": True,
    },
    "wigos_id": {
        "label": _("WIGOS ID"),
        "description": _("WIGOS ID"),
        "type": "text",
        "data_type": "Character",
        "required": True,
    },
    "station_type": {
        "label": _("Station Type"),
        "description": _("Type of observing station, encoding using code table 0 02 001"),
        "choices": [
            (0, _("Automatic")),
            (1, _("Manned")),
            (2, _("Hybrid: both automatic and manned")),
        ],
        "type": "numeric",
        "data_type": "Integer",
        "reference_url": "https://codes.wmo.int/bufr4/b/02/001",
        "required": True,
    },
    "latitude": {
        "label": _("Latitude"),
        "description": _("Latitude of the station (to 5 decimal places)"),
        "type": "numeric",
        "data_type": "Decimal",
        "required": True,
    },
    "longitude": {
        "label": _("Longitude"),
        "description": _("Longitude of the station (to 5 decimal places)"),
        "type": "numeric",
        "data_type": "Decimal",
        "required": True,
    },
    "station_height_above_msl": {
        "label": _("Station Height Above MSL"),
        "description": _("Height of the station ground above mean sea level (to 1 decimal place)"),
        "type": "numeric",
        "data_type": "Decimal",
        "required": False,
    },
    "barometer_height_above_msl": {
        "label": _("Barometer Height Above MSL"),
        "description": _("Height of the barometer above mean sea level (to 1 decimal place), typically height "
                         "of station ground plus the height of the sensor above local ground"),
        "type": "numeric",
        "data_type": "Decimal",
        "required": False,
    },
    "thermometer_height": {
        "label": _("Thermometer Height"),
        "description": _("Height of thermometer or temperature sensor above the local ground to 2 decimal places"),
        "type": "numeric",
        "data_type": "Decimal",
        "required": False,
    },
    "anemometer_height": {
        "label": _("Anemometer Height"),
        "description": _("Height of the anemometer above local ground to 2 decimal place"),
        "type": "numeric",
        "data_type": "Decimal",
        "required": False,
    },
    "rain_sensor_height": {
        "label": _("Rain Sensor Height"),
        "description": _("Height of the rain gauge above local ground to 2 decimal place"),
        "type": "numeric",
        "data_type": "Decimal",
        "required": False,
    },
    "method_of_ground_state_measurement": {
        "label": _("Method of Ground State Measurement"),
        "description": _("Method of observing the state of the ground, encoded using code table 0 02 176"),
        "type": "numeric",
        "required": False,
        "data_type": "Integer",
        "choices": (
            (0, _("Manual observation")),
            (1, _("Video camera method")),
            (2, _("Infrared method")),
            (3, _("Laser method")),
            (14, _("Others")),
            (15, _("Missing value")),
        ),
        "reference_url": "https://codes.wmo.int/bufr4/b/02/176"
    },
    "method_of_snow_depth_measurement": {
        "label": _("Method of Snow Depth Measurement"),
        "description": _("Method of observing the snow depth encoded using code table 0 02 177"),
        "type": "numeric",
        "data_type": "Integer",
        "required": False,
        "choices": (
            (0, _("Manual observation")),
            (1, _("Ultrasonic method")),
            (2, _("Video camera method")),
            (3, _("Laser method")),
            (14, _("Others")),
            (15, _("Missing value")),
        ),
        "reference_url": "https://codes.wmo.int/bufr4/b/02/177"
    },
    "time_period_of_wind": {
        "label": _("Time Period of Wind"),
        "description": _(
            "Time period over which the wind speed and direction have been averegd. 10 minutes in normal cases or the "
            "number of minutes since a significant change occuring in the preceeding 10 minutes."),
        "type": "numeric",
        "data_type": "Integer",
        "required": False,
    }
}

OSCAR_SURFACE_REQUIRED_CSV_COLUMNS = [
    {"name": "Station", "type": "text"},
    {"name": "Station type", "type": "text"},
    {"name": "WIGOS Station Identifier(s)", "type": "text"},
    {"name": "Latitude", "type": "numeric"},
    {"name": "Longitude", "type": "numeric"},
    {"name": "Elevation", "type": "numeric"},
]

PREDEFINED_DATA_PARAMETERS = [
    {
        "name": _("Temperature"),
        "unit": {
            "name": _("Degree Celsius"),
            "symbol": "°C",
        },
        "wis2box_aws_csv_template_unit": {
            "name": _("Kelvin"),
            "description": _("For converting Temperature from Celsius to Kelvin"),
            "symbol": "K",
        },
    },
    {
        "name": _("Relative Humidity"),
        "unit": {
            "name": _("Percent"),
            "symbol": "%",
        },
    },
    {
        "name": _("Atmospheric Pressure"),
        "unit": {
            "name": _("Hectopascal"),
            "symbol": "hPa",
        },
        "wis2box_aws_csv_template_unit": {
            "name": _("Pascal"),
            "description": _("For converting Pressure from hectopascal to pascal"),
            "symbol": "Pa",
        },
    },
    {
        "name": _("Wind Speed"),
        "unit": {
            "name": _("Meters per Second"),
            "symbol": "m/s",
        },
    },
    {
        "name": _("Wind Direction"),
        "unit": {
            "name": _("Degrees"),
            "symbol": "degree",
        },
    },
    {
        "name": _("Precipitation"),
        "unit": {
            "name": _("Millimeters"),
            "symbol": "mm",
        },
        "conversion_context": "precipitation",
        "wis2box_aws_csv_template_unit": {
            "name": _("Kilogram per Square Meter"),
            "description": _("For converting Precipitation from millimeters to kilograms per square meter"),
            "symbol": "kg m-2",
        },
    }
]
