
from azure.storage.blob import generate_blob_sas, BlobServiceClient
from datetime import datetime, timedelta
import os
import uuid

CONTAINER = "inventory-images"

def generate_image_url(blob_path):
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    blob_service = BlobServiceClient.from_connection_string(connect_str)

    account_name = blob_service.account_name

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name="inventory-images",
        blob_name=blob_path,
        account_key=blob_service.credential.account_key,
        permission="r",
        expiry=datetime.utcnow() + timedelta(hours=1)
    )

    return f"https://{account_name}.blob.core.windows.net/inventory-images/{blob_path}?{sas_token}"

def upload_inventory_image(file):
    CONNECT_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

    if not connect_str:
        raise Exception("Missing AZURE_STORAGE_CONNECTION_STRING")


    blob_service = BlobServiceClient.from_connection_string(CONNECT_STR)
    container_client = blob_service.get_container_client(CONTAINER)

    filename = f"{uuid.uuid4()}_{file.filename}"
    blob_path = f"images/{filename}"

    blob_client = container_client.get_blob_client(blob_path)
    blob_client.upload_blob(file, overwrite=True)

    return blob_path