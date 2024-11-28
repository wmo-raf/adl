# This file is heavily inspired by the MetPy (metpy.units) library, which is licensed under the BSD 3-Clause License.

import contextlib
import re

import pint

_base_unit_of_dimensionality = {
    '[pressure]': 'Pa',
    '[temperature]': 'K',
    '[dimensionless]': '',
    '[length]': 'm',
    '[speed]': 'm s**-1'
}


def _fix_udunits_powers(string):
    """Replace UDUNITS-style powers (m2 s-2) with exponent symbols (m**2 s**-2)."""
    return _UDUNIT_POWER.sub('**', string)


def _fix_udunits_div(string):
    return 's**-1' if string == '/s' else string


# Fix UDUNITS-style powers, percent signs, and ill-defined units
_UDUNIT_POWER = re.compile(r'(?<=[A-Za-z\)])(?![A-Za-z\)])'
                           r'(?<![0-9\-][eE])(?<![0-9\-])(?=[0-9\-])')
_unit_preprocessors = [_fix_udunits_powers, lambda string: string.replace('%', 'percent'),
                       _fix_udunits_div]


def setup_registry(reg):
    """Set up a given registry with MetPy's default tweaks and settings."""
    reg.autoconvert_offset_to_baseunit = True

    # For Pint 0.18.0, need to deal with the fact that the wrapper isn't forwarding on setting
    # the attribute.
    with contextlib.suppress(AttributeError):
        reg.get().autoconvert_offset_to_baseunit = True

    for pre in _unit_preprocessors:
        if pre not in reg.preprocessors:
            reg.preprocessors.append(pre)

    # Define commonly encountered units not defined by pint
    reg.define('degrees_north = degree = degrees_N = degreesN = degree_north = degree_N '
               '= degreeN')
    reg.define('degrees_east = degree = degrees_E = degreesE = degree_east = degree_E '
               '= degreeE')
    reg.define('dBz = 1e-18 m^3; logbase: 10; logfactor: 10 = dBZ')

    # Alias geopotential meters (gpm) to just meters
    reg.define('@alias meter = gpm')

    # custom contexts

    # Define a context for precipitation
    precipitation = pint.Context('precipitation')

    # Precipitation amount
    # 1 mm of rainfall = 1 kg/m² for water
    # Forward transformation (mm -> kg/m²)
    precipitation.add_transformation('[length]', '[mass] / [length] ** 2',
                                     lambda reg, x: x * reg('kg/m^2') / reg('mm'))

    # Reverse transformation (kg/m² -> mm)
    precipitation.add_transformation('[mass] / [length] ** 2', '[length]',
                                     lambda reg, x: x * reg('mm') / reg('kg/m^2'))

    # Precipitation Rate
    # Forward transformation (mm/h -> kg/m²/h)
    precipitation.add_transformation('[length] / [time]', '[mass] / [length] ** 2 / [time]',
                                     lambda reg, x: x * reg('kg/m^2/h') / reg('mm/h'))

    # Reverse transformation (kg/m²/h -> mm/h)
    precipitation.add_transformation('[mass] / [length] ** 2 / [time]', '[length] / [time]',
                                     lambda reg, x: x * reg('mm/h') / reg('kg/m^2/h'))

    reg.add_context(precipitation)

    return reg


# Make our modifications using pint's application registry--which allows us to better
# interoperate with other libraries using Pint.
units = setup_registry(pint.get_application_registry())

TEMPERATURE_UNITS = [
    'degree_Celsius',
    'celsius',
    'degC',
    'degreeC',
    '°C',
    'degree_Fahrenheit',
    'fahrenheit',
    'degF',
    'degreeF',
    '°F',
    'degree_Kelvin',
    'kelvin',
    'degK',
    'degreeK',
    'K',
    '°K',
    'degree_Rankine',
    'rankine',
    'degR',
    'degreeR',
    '°R'
]
