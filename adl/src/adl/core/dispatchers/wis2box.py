import csv
import logging
import time
from datetime import timedelta
from io import StringIO, BytesIO

from django.utils import timezone as dj_timezone
from minio import Minio
from minio.error import S3Error
from urllib3 import PoolManager

from adl.core.dispatchers.csv2bufr_templates import STATION, TIMESTAMP
from adl.core.utils import get_object_or_none

logger = logging.getLogger(__name__)

WIS2BOX_STORAGE_REQUEST_TIMEOUT = 60

# Interactive connection tests must stay snappy: separate, much shorter
# timeout than the upload pool
WIS2BOX_TEST_CONNECTION_TIMEOUT = 10

WIS2BOX_INCOMING_BUCKET = "wis2box-incoming"

MINIO_PATH = "incoming/"

# Create a custom HTTP client with timeout
http_client = PoolManager(timeout=timedelta(seconds=WIS2BOX_STORAGE_REQUEST_TIMEOUT).seconds, retries=False)

def get_minio_client(endpoint, access_key, secret_key, secure=False):
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, http_client=http_client, secure=secure)


def test_wis2box_connection(channel):
    """
    Probe the channel's MinIO storage: reachability, authentication, and
    presence of the wis2box incoming bucket. Never raises; always returns
    within the test-connection timeout.
    """
    start = time.monotonic()

    def latency_ms():
        return int((time.monotonic() - start) * 1000)

    try:
        http = PoolManager(timeout=WIS2BOX_TEST_CONNECTION_TIMEOUT, retries=False)
        client = Minio(
            channel.storage_endpoint,
            access_key=channel.storage_username,
            secret_key=channel.storage_password,
            http_client=http,
            secure=channel.secure,
        )
        bucket_found = client.bucket_exists(WIS2BOX_INCOMING_BUCKET)
    except Exception as e:
        return {
            "ok": False,
            "supported": True,
            "message": f"Connection failed: {e}",
            "latency_ms": latency_ms(),
        }

    if not bucket_found:
        return {
            "ok": False,
            "supported": True,
            "message": f"Connected to {channel.storage_endpoint}, "
                       f"but bucket '{WIS2BOX_INCOMING_BUCKET}' was not found",
            "latency_ms": latency_ms(),
        }

    return {
        "ok": True,
        "supported": True,
        "message": f"Connected to {channel.storage_endpoint}; "
                   f"bucket '{WIS2BOX_INCOMING_BUCKET}' is accessible",
        "latency_ms": latency_ms(),
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


def get_station_column_value(station, column_name):
    if column_name == "latitude":
        return station.location.y
    if column_name == "longitude":
        return station.location.x
    return getattr(station, column_name)


def channel_record_to_wis2box_csv(channel, record):
    """
    Build the one-row CSV for a dispatch record, in the shape of the channel's
    csv2bufr template.

    Station and timestamp columns always come from the station and the
    observation time, so a parameter mapping can never overwrite them.
    """
    from adl.core.models import Station
    station_id = record.get("station_id")
    
    if not station_id:
        logger.error("Station ID not found in data record")
        return None, None
    
    timestamp = record.get("timestamp")
    if not timestamp:
        logger.error("Timestamp not found in data record")
        return None, None
    
    station = get_object_or_none(Station, id=station_id)
    
    if not station:
        logger.error(f"Station with ID {station_id} not found")
        return None, None
    
    template = channel.get_csv2bufr_template()
    values = record.get("values", {})
    
    row_data = []
    for column in template.columns:
        if column.source == STATION:
            col_data = get_station_column_value(station, column.name)
        elif column.source == TIMESTAMP:
            col_data = getattr(timestamp, column.name)
        else:
            col_data = values.get(column.name, "")
        row_data.append(col_data)
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(template.column_names)
    writer.writerow(row_data)
    csv_content = output.getvalue()
    output.close()
    
    filename = f"WIGOS_{station.wigos_id}_{timestamp.strftime('%Y%m%dT%H%M%S')}.csv"
    
    return csv_content, filename


def upload_to_wis2box(channel, data_records, overwrite=False):
    minio_client = get_minio_client(
        endpoint=channel.storage_endpoint,
        access_key=channel.storage_username,
        secret_key=channel.storage_password,
        secure=channel.secure
    )
    
    uploaded_records_count = 0
    last_sent_obs_time = None
    
    for record in data_records:
        csv_content, filename = channel_record_to_wis2box_csv(channel, record)
        
        if not csv_content:
            logger.error("Error converting record to CSV. Skipping...")
        
        # Convert csv_content to bytes for uploading
        csv_bytes = BytesIO(csv_content.encode('utf-8'))
        
        bucket_name = "wis2box-incoming"
        object_name = f"{channel.dataset_id}/{filename}"
        
        # Upload the CSV content to MinIO
        try:
            minio_client.put_object(
                bucket_name,
                object_name,
                csv_bytes,
                length=len(csv_content),
                content_type="text/csv"
            )
            
            logger.debug(f"CSV uploaded successfully as {object_name} in bucket {bucket_name}.")
            
            logger.debug(f"Updating last sent observation time for "
                         f"station {record.get('station_id')} and channel {channel.name}")
            
            # Update the last sent observation time
            last_sent_obs_time = record.get("timestamp")
            uploaded_records_count += 1
        
        except S3Error as e:
            logger.error(f"Error uploading CSV to MinIO: {str(e)}")
            raise e
    
    logger.info(f"Uploaded {uploaded_records_count} records to {channel.name}")
    
    return uploaded_records_count, last_sent_obs_time
