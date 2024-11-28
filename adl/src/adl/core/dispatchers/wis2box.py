import logging
from datetime import timedelta, datetime

from minio import Minio
from urllib3 import PoolManager

LOGGER = logging.getLogger(__name__)

WIS2BOX_STORAGE_REQUEST_TIMEOUT = 60

MINIO_PATH = "incoming/"

# Create a custom HTTP client with timeout
http_client = PoolManager(timeout=timedelta(seconds=WIS2BOX_STORAGE_REQUEST_TIMEOUT).seconds, retries=False)

# create minio client
minio_client = Minio(http_client=http_client, secure=False)


def upload_to_wis2box(ingestion_record_id, event_id, overwrite=False, hourly_aggregate=False):
    from adl.core.models import DataIngestionRecord
    
    uploaded = False
    ingestion_record = DataIngestionRecord.objects.get(id=ingestion_record_id)
    
    if ingestion_record.uploaded_to_wis2box and not overwrite:
        logging.warning(f"Data ingestion record {ingestion_record_id} has already been uploaded to WIS2BOX")
        uploaded = True
        return uploaded
    
    logging.info(f"Uploading data record {ingestion_record_id} to WIS2BOX")
    
    try:
        filename = ingestion_record.filename
        object_name = f"{MINIO_PATH}{filename}"
        file_path = ingestion_record.file.path
        
        all_hourly_records = []
        
        if ingestion_record.is_hourly_aggregate and ingestion_record.hourly_aggregate_file:
            file_path = ingestion_record.hourly_aggregate_file.path
            
            # get other ingestion_records that are related to this hourly aggregate
            start_datetime = datetime(ingestion_record.time.year,
                                      ingestion_record.time.month,
                                      ingestion_record.time.day,
                                      ingestion_record.time.hour).replace(tzinfo=ingestion_record.time.tzinfo)
            
            end_datetime = start_datetime + timedelta(hours=1)
            all_hourly_records = DataIngestionRecord.objects.filter(time__gte=start_datetime, time__lt=end_datetime)
        
        # publish message
        minio_client.fput_object(bucket_name="wis2box-incoming", object_name=object_name, file_path=file_path)
        
        if all_hourly_records:
            # mark all hourly records as uploaded to WIS2BOX
            all_hourly_records.update(uploaded_to_wis2box=True, event=event_id)
        else:
            # mark the single ingestion record as published to WIS2BOX
            ingestion_record.uploaded_to_wis2box = True
            ingestion_record.event = event_id
            ingestion_record.save()
        
        logging.info(f"Data record {ingestion_record_id} uploaded to WIS2BOX successfully")
    except Exception as e:
        logging.error(f"Error uploading data record {ingestion_record_id} to WIS2BOX: {e}")
