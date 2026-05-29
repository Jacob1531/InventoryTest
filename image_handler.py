from azure.storage.blob import BlobServiceClient
import os
import uuid

CONNECT_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER = "inventory-images"

def upload_inventory_image(file):
    blob_service = BlobServiceClient.from_connection_string(CONNECT_STR)
    container_client = blob_service.get_container_client(CONTAINER)

    filename = f"{uuid.uuid4()}_{file.filename}"
    blob_path = f"images/{filename}"

    blob_client = container_client.get_blob_client(blob_path)
    blob_client.upload_blob(file, overwrite=True)

    return blob_path