import logging

from django.conf import settings
from minio import Minio

LOGGER = logging.getLogger(__name__)

WIS2BOX_CENTRE_ID = getattr(settings, "WIS2BOX_CENTRE_ID", None)
WIS2BOX_STORAGE_ENDPOINT = getattr(settings, "WIS2BOX_STORAGE_ENDPOINT", None)
WIS2BOX_STORAGE_USERNAME = getattr(settings, "WIS2BOX_STORAGE_USERNAME", None)
WIS2BOX_STORAGE_PASSWORD = getattr(settings, "WIS2BOX_STORAGE_PASSWORD", None)

MINIO_PATH = f"/{WIS2BOX_CENTRE_ID}/data/core/weather/surface-based-observations/synop/"

# create minio client
minio_client = Minio(endpoint=WIS2BOX_STORAGE_ENDPOINT,
                     access_key=WIS2BOX_STORAGE_USERNAME,
                     secret_key=WIS2BOX_STORAGE_PASSWORD,
                     secure=False)


def upload_to_wis2box(ingestion_record_id, overwrite=False):
    from wis2box_adl.core.models import DataIngestionRecord
    ingestion_record = DataIngestionRecord.objects.get(id=ingestion_record_id)

    if ingestion_record.uploaded_to_wis2box and not overwrite:
        logging.warning(f"Data ingestion record {ingestion_record_id} has already been uploaded to WIS2BOX")
        return

    logging.info(f"Uploading data record {ingestion_record_id} to WIS2BOX")

    try:
        filename = ingestion_record.wis2box_filename
        object_name = f"{MINIO_PATH}{filename}"
        file_path = ingestion_record.file.path

        # publish message
        minio_client.fput_object(bucket_name="wis2box-incoming", object_name=object_name, file_path=file_path)

        # mark the ingestion record as published to WIS2BOX
        ingestion_record.uploaded_to_wis2box = True
        ingestion_record.save()

        logging.info(f"Data record {ingestion_record_id} uploaded to WIS2BOX successfully")
    except Exception as e:
        raise e
