import csv
import logging
from datetime import timedelta
from io import StringIO

from django.utils import timezone as dj_timezone
from minio import Minio
from urllib3 import PoolManager

from adl.core.utils import get_object_or_none

logger = logging.getLogger(__name__)

WIS2BOX_STORAGE_REQUEST_TIMEOUT = 60

MINIO_PATH = "incoming/"

# Create a custom HTTP client with timeout
http_client = PoolManager(timeout=timedelta(seconds=WIS2BOX_STORAGE_REQUEST_TIMEOUT).seconds, retries=False)

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


def get_minio_client(endpoint, access_key, secret_key, secure=False):
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, http_client=http_client, secure=secure)


def get_wis2box_csv_station_metadata(station):
    return {
        "wsi_series": station.wsi_series,
        "wsi_issuer": station.wsi_issuer,
        "wsi_issue_number": station.wsi_issue_number,
        "wsi_local": station.wsi_local,
        "wmo_block_number": station.wmo_block_number,
        "wmo_station_number": station.wmo_station_number,
        "station_type": station.station_type,
        "latitude": station.location.y,
        "longitude": station.location.x,
        "station_height_above_msl": station.station_height_above_msl,
        "barometer_height_above_msl": station.barometer_height_above_msl,
        "anemometer_height": station.anemometer_height,
        "rain_sensor_height": station.rain_sensor_height,
        "method_of_ground_state_measurement": station.method_of_ground_state_measurement,
        "method_of_snow_depth_measurement": station.method_of_snow_depth_measurement,
        "time_period_of_wind": station.time_period_of_wind,
    }


def hourly_aggregate_data_records(channel, data_records):
    stations = {}
    for record in data_records:
        station_id = record.get("station_id")
        if station_id not in stations:
            stations[station_id] = []
        stations[station_id].append(record)
    
    current_time = dj_timezone.localtime()
    
    hourly_data_records = []
    
    # iterate over stations
    for station_id, records in stations.items():
        # group station records by day by hour
        data = {}
        for record in records:
            timestamp = record.get("timestamp")
            
            if not timestamp:
                logger.error("Timestamp not found in data record. Skipping...")
                continue
            
            # skip if record time is today and record hour is equal to current hour
            # we want to aggregate data from full hours. If record hour is equal to current hour,
            # we do not know if we have all the data for the current hour
            if timestamp == current_time.date() and timestamp == current_time.hour:
                logger.info(f"Skipping record record for station {station_id} as it is for the current hour")
                continue
            
            key = timestamp.strftime("%Y-%m-%d")
            
            if key not in data:
                data[key] = {}
            
            hour_key = timestamp.strftime("%H")
            if hour_key not in data[key]:
                data[key][hour_key] = []
            
            data[key][hour_key].append(record)
            
            for day, hourly_data in data.items():
                for hour, hourly_records in hourly_data.items():
                    latest_record = None
                    for h_record in hourly_records:
                        if not latest_record or h_record.get("timestamp") > latest_record.get("timestamp"):
                            latest_record = h_record
                    
                    if latest_record:
                        hourly_data_records.append(latest_record)
    
    return hourly_data_records


def upload_to_wis2box(channel, data_records, overwrite=False, hourly_aggregate=False):
    from adl.core.models import Station
    
    for record in data_records:
        station_id = record.get("station_id")
        
        if not station_id:
            logger.error("Station ID not found in data record. Skipping...")
            continue
        
        timestamp = record.get("timestamp")
        if not timestamp:
            logger.error("Timestamp not found in data record. Skipping...")
            continue
        
        station = get_object_or_none(Station, id=station_id)
        
        if not station:
            logger.error(f"Station with ID {station_id} not found. Skipping...")
            continue
        
        csv_metadata = get_wis2box_csv_station_metadata(station)
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(WIS2BOX_CSV_HEADER)
        
        row_data = []
        values = record.get("values", {})
        
        date_info = {
            "year": timestamp.year,
            "month": timestamp.month,
            "day": timestamp.day,
            "hour": timestamp.hour,
            "minute": timestamp.minute,
        }
        
        data = {
            **csv_metadata,
            **date_info,
            **values
        }
        
        for col in WIS2BOX_CSV_HEADER:
            col_data = data.get(col, "")
            row_data.append(col_data)
        
        writer.writerow(row_data)
        csv_content = output.getvalue()
        output.close()
        
        print(csv_content)
    
    uploaded = False
    # obs_record = DataIngestionRecord.objects.get(id=ingestion_record_id)
    #
    # if ingestion_record.uploaded_to_wis2box and not overwrite:
    #     logging.warning(f"Data ingestion record {ingestion_record_id} has already been uploaded to WIS2BOX")
    #     uploaded = True
    #     return uploaded
    #
    # logging.info(f"Uploading data record {ingestion_record_id} to WIS2BOX")
    #
    # try:
    #     filename = ingestion_record.filename
    #     object_name = f"{MINIO_PATH}{filename}"
    #     file_path = ingestion_record.file.path
    #
    #     all_hourly_records = []
    #
    #     if ingestion_record.is_hourly_aggregate and ingestion_record.hourly_aggregate_file:
    #         file_path = ingestion_record.hourly_aggregate_file.path
    #
    #         # get other ingestion_records that are related to this hourly aggregate
    #         start_datetime = datetime(ingestion_record.time.year,
    #                                   ingestion_record.time.month,
    #                                   ingestion_record.time.day,
    #                                   ingestion_record.time.hour).replace(tzinfo=ingestion_record.time.tzinfo)
    #
    #         end_datetime = start_datetime + timedelta(hours=1)
    #         all_hourly_records = DataIngestionRecord.objects.filter(time__gte=start_datetime, time__lt=end_datetime)
    #
    #     # publish message
    #     minio_client.fput_object(bucket_name="wis2box-incoming", object_name=object_name, file_path=file_path)
    #
    #     if all_hourly_records:
    #         # mark all hourly records as uploaded to WIS2BOX
    #         all_hourly_records.update(uploaded_to_wis2box=True, event=event_id)
    #     else:
    #         # mark the single ingestion record as published to WIS2BOX
    #         ingestion_record.uploaded_to_wis2box = True
    #         ingestion_record.event = event_id
    #         ingestion_record.save()
    #
    #     logging.info(f"Data record {ingestion_record_id} uploaded to WIS2BOX successfully")
    # except Exception as e:
    #     logging.error(f"Error uploading data record {ingestion_record_id} to WIS2BOX: {e}")
