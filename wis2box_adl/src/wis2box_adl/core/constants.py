from django.utils.translation import gettext_lazy as _

# standardised format targeted at data from AWS stations
# and in support of the GBON reporting requirements.

# adapted from https://training.wis2box.wis.wmo.int/practical-sessions/converting-csv-data-to-bufr/

DATA_PARAMETERS_DICT = {
    "station_pressure": {
        "name": _("Station Pressure"),
        "unit": "Pa",
        "description": _("Pressure observed at the station level to the nearest 10 pascals"),
        "data_type": "float",
    },
    "msl_pressure": {
        "name": _("Mean Sea Level Pressure"),
        "unit": "Pa",
        "description": _("Pressure reduced to mean sea level to the nearest 10 pascals"),
        "data_type": "float",
    },
    "geopotential_height": {
        "name": _("Geopotential Height"),
        "unit": "gpm",
        "description": _("Geoptential height expressed in geopotential meters (gpm) to 0 decimal places"),
        "data_type": "integer",
    },
    "air_temperature": {
        "name": _("Air Temperature"),
        "unit": "Kelvin",
        "description": _("Instantaneous air temperature to 2 decimal places"),
        "data_type": "float",
        "decimal_places": 2,
    },
    "dewpoint_temperature": {
        "name": "Dew Point Temperature",
        "unit": "Kelvin",
        "description": _("Instantaneous dew point temperature to 2 decimal places"),
        "data_type": "float",
        "decimal_places": 2,
    },
    "relative_humidity": {
        "name": _("Relative Humidity"),
        "unit": "%",
        "description": _("Instantaneous relative humidity to 0 decimal place"),
        "data_type": "integer",
    },
    "ground_state": {
        "name": _("Ground State"),
        "unit": "",
        "description": _("State of the ground encoded using code table 0 20 062"),
        "data_type": "integer",
    },
    "snow_depth": {
        "name": _("Snow Depth"),
        "unit": "meters",
        "description": _("Snow depth at time of observation to 2 decimal places"),
        "data_type": "float",
        "decimal_places": 2,
    },
    "precipitation_intensity": {
        "name": _("Precipitation Intensity"),
        "unit": "kg m-2 h-1",
        "description": _("Intensity of precipitation at time of observation to 5 decimal places"),
        "data_type": "float",
        "decimal_places": 5,
    },
    "time_period_of_wind": {
        "name": _("Time Period of Wind"),
        "unit": "minutes",
        "description": _("Time period over which the wind speed and direction have been averegd. "
                         "10 minutes in normal cases or the number of minutes since a significant "
                         "change occuring in the preceeding 10 minutes."),
        "data_type": "integer",
    },
    "wind_direction": {
        "name": _("Wind Direction"),
        "unit": "degrees",
        "description": _("Wind direction (at anemometer height) averaged from the cartesian components over the "
                         "indicated time period, 0 decimal places"),
        "data_type": "integer",
    },
    "wind_speed": {
        "name": _("Wind Speed"),
        "unit": "mps",
        "description": _("Wind speed (at anemometer height) averaged from the cartesian components over the indicated "
                         "time period, 1 decimal place"),
        "data_type": "float",
        "decimal_places": 1,
    },
    "maximum_wind_gust_direction_10_minutes": {
        "name": _("Maximum Wind Gust Direction (10 minutes)"),
        "unit": "degrees",
        "description": _("Highest 3 second average over the preceeding 10 minutes, 0 decimal places"),
        "data_type": "integer",
    },
    "maximum_wind_gust_speed_10_minutes": {
        "name": _("Maximum Wind Gust Speed (10 minutes)"),
        "unit": "mps",
        "description": _("Highest 3 second average over the preceeding 10 minutes, 1 decimal place"),
        "data_type": "float",
        "decimal_places": 1,
    },
    "maximum_wind_gust_direction_1_hour": {
        "name": _("Maximum Wind Gust Direction (1 hour)"),
        "unit": "degrees",
        "description": _("Highest 3 second average over the preceeding hour, 0 decimal places"),
        "data_type": "integer",
    },
    "maximum_wind_gust_speed_1_hour": {
        "name": _("Maximum Wind Gust Speed (1 hour)"),
        "unit": "mps",
        "description": _("Highest 3 second average over the preceeding hour, 1 decimal place"),
        "data_type": "float",
        "decimal_places": 1,
    },
    "maximum_wind_gust_direction_3_hours": {
        "name": _("Maximum Wind Gust Direction (3 hours)"),
        "unit": "degrees",
        "description": _("Highest 3 second average over the preceeding 3 hours, 0 decimal places"),
        "data_type": "integer",
    },
    "maximum_wind_gust_speed_3_hours": {
        "name": _("Maximum Wind Gust Speed (3 hours)"),
        "unit": "mps",
        "description": _("Highest 3 second average over the preceeding 3 hours, 1 decimal place"),
        "data_type": "float",
        "decimal_places": 1,
    },
    "total_precipitation_1_hour": {
        "name": _("Total Precipitation (1 hour)"),
        "unit": "kg m-2",
        "description": _("Total precipitation over the past hour, 1 decimal place"),
        "data_type": "float",
        "decimal_places": 1,
    },
    "total_precipitation_3_hours": {
        "name": _("Total Precipitation (3 hours)"),
        "unit": "kg m-2",
        "description": _("Total precipitation over the past 3 hours, 1 decimal place"),
        "data_type": "float",
        "decimal_places": 1,
    },
    "total_precipitation_6_hours": {
        "name": _("Total Precipitation (6 hours)"),
        "unit": "kg m-2",
        "description": _("Total precipitation over the past 6 hours, 1 decimal place"),
        "data_type": "float",
        "decimal_places": 1,
    },
    "total_precipitation_12_hours": {
        "name": _("Total Precipitation (12 hours)"),
        "unit": "kg m-2",
        "description": _("Total precipitation over the past 12 hours, 1 decimal place"),
        "data_type": "float",
        "decimal_places": 1,
    },
    "total_precipitation_24_hours": {
        "name": _("Total Precipitation (24 hours)"),
        "unit": "kg m-2",
        "description": _("Total precipitation over the past 24 hours, 1 decimal place"),
        "data_type": "float",
        "decimal_places": 1,
    }
}

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

WIS2BOX_CSV_HEADER = [
    "wsi_series",
    "wsi_issuer",
    "wsi_issue_number",
    "wsi_local",
    "wmo_block_number",
    "wmo_station_number",
    "station_type",
    "year",
    "month",
    "day",
    "hour",
    "minute",
    "latitude",
    "longitude",
    "station_height_above_msl",
    "barometer_height_above_msl",
    "station_pressure",
    "msl_pressure",
    "geopotential_height",
    "thermometer_height",
    "air_temperature",
    "dewpoint_temperature",
    "relative_humidity",
    "method_of_ground_state_measurement",
    "ground_state",
    "method_of_snow_depth_measurement",
    "snow_depth",
    "precipitation_intensity",
    "anemometer_height",
    "time_period_of_wind",
    "wind_direction",
    "wind_speed",
    "maximum_wind_gust_direction_10_minutes",
    "maximum_wind_gust_speed_10_minutes",
    "maximum_wind_gust_direction_1_hour",
    "maximum_wind_gust_speed_1_hour",
    "maximum_wind_gust_direction_3_hours",
    "maximum_wind_gust_speed_3_hours",
    "rain_sensor_height",
    "total_precipitation_1_hour",
    "total_precipitation_3_hours",
    "total_precipitation_6_hours",
    "total_precipitation_12_hours",
    "total_precipitation_24_hours",
]
