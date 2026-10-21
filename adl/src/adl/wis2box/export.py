"""
Planning a wis2box station bulk-insert export from ADL.

ADL stations that are not yet on wis2box are matched to OSCAR by WIGOS id.
ADL contributes only that id: wis2box treats OSCAR as authoritative, so every
other column comes from the OSCAR record, mapped to the WMDR codes wis2box
validates against.
"""

import csv
from dataclasses import dataclass, field
from io import StringIO

from .wmdr_codelists import FACILITY_TYPES, WMO_REGIONS, TERRITORY_NAMES

ELIGIBLE = "eligible"
NOT_IN_OSCAR = "not_in_oscar"
INVALID_OSCAR_DATA = "invalid_oscar_data"

# CSV column -> (OSCAR record key, WMDR label -> code lookup)
_CODED_COLUMNS = {
    "facility_type": ("stationTypeName", FACILITY_TYPES),
    "territory_name": ("territory", TERRITORY_NAMES),
    "wmo_region": ("region", WMO_REGIONS),
}

_COORDINATE_COLUMNS = ("latitude", "longitude", "elevation")

# Header and order of wis2box's station list CSV
WIS2BOX_STATION_CSV_COLUMNS = [
    "station_name",
    "wigos_station_identifier",
    "traditional_station_identifier",
    "facility_type",
    "latitude",
    "longitude",
    "elevation",
    "barometer_height",
    "territory_name",
    "wmo_region",
]


@dataclass
class ExportRow:
    station: object
    status: str
    reason: str = ""
    values: dict = field(default_factory=dict)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _traditional_station_identifier(wigos_id):
    """The WMO block + station number, which only 20000-issued ids carry."""
    parts = wigos_id.split("-")
    if len(parts) == 4 and parts[1] == "20000":
        return parts[3]
    return ""


def _oscar_values(wigos_id, record):
    """
    The CSV values for one OSCAR record, and a list of reasons wis2box would
    reject them (empty when the row is publishable).
    """
    values = {
        "station_name": record.get("name"),
        "wigos_station_identifier": wigos_id,
        "traditional_station_identifier": _traditional_station_identifier(wigos_id),
        "latitude": record.get("latitude"),
        "longitude": record.get("longitude"),
        "elevation": record.get("elevation"),
    }
    problems = []

    for column, (oscar_key, codes) in _CODED_COLUMNS.items():
        label = record.get(oscar_key)
        values[column] = codes.get(label)
        if values[column] is None:
            problems.append(f"{column}: OSCAR value {label!r} is not a WMDR code")

    # wis2box requires numeric coordinates for every fixed facility type
    if (values["facility_type"] or "").lower().endswith("fixed"):
        for column in _COORDINATE_COLUMNS:
            if not _is_number(values[column]):
                problems.append(f"{column}: missing in OSCAR")

    return values, problems


def _index_by_wigos_id(oscar_records):
    """
    Key each OSCAR record by every WIGOS id it carries, so an ADL station
    registered under a secondary identifier still matches.
    """
    index = {}
    for record in oscar_records:
        identifiers = [i.get("wigosStationIdentifier") for i in record.get("wigosStationIdentifiers") or []]
        for wigos_id in [record.get("wigosId"), *identifiers]:
            if wigos_id:
                index.setdefault(wigos_id, record)
    return index


def plan_wis2box_export(adl_stations, wis2box_wigos_ids, oscar_records):
    """
    One ``ExportRow`` per ADL station that wis2box does not yet hold.
    """
    oscar_by_wigos = _index_by_wigos_id(oscar_records)

    rows = []
    for station in adl_stations:
        wigos_id = station.station_id
        if wigos_id in wis2box_wigos_ids:
            continue

        record = oscar_by_wigos.get(wigos_id)
        if record is None:
            rows.append(ExportRow(station=station, status=NOT_IN_OSCAR, reason="Not found in OSCAR"))
            continue

        values, problems = _oscar_values(wigos_id, record)
        if problems:
            rows.append(ExportRow(station=station, status=INVALID_OSCAR_DATA, reason="; ".join(problems)))
            continue

        rows.append(ExportRow(station=station, status=ELIGIBLE, values=values))

    return rows


def build_wis2box_station_csv(rows, barometer_heights):
    """
    The station list CSV for ``wis2box metadata station publish-collection``.

    ``barometer_heights`` maps each row's WIGOS id to its barometer height,
    which OSCAR search results do not carry.
    """
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=WIS2BOX_STATION_CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        wigos_id = row.values["wigos_station_identifier"]
        writer.writerow({**row.values, "barometer_height": barometer_heights[wigos_id]})
    return buffer.getvalue()
