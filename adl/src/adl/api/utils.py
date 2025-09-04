from collections import defaultdict

from dateutil import parser as dateparser


# Helper function to validate ISO datetime format
def validate_iso_datetime(param_name, value):
    if value:
        try:
            return dateparser.isoparse(value)
        except ValueError:
            raise ValueError(f"Invalid {param_name} date format. Use ISO format (e.g., 2023-10-01T00:00:00Z).")
    return None


def _group_records_by_time(records, station_id, connection_id):
    """Group observation records by time."""
    grouped_data = defaultdict(lambda: {"data": {}})
    for record in records:
        time_key = record.time.isoformat()
        grouped_data[time_key].update({
            "station_id": station_id,
            "connection_id": connection_id,
            "time": time_key,
        })
        grouped_data[time_key]["data"][record.parameter_id] = record.value
    return list(grouped_data.values())
