"""
file_handler.py
=====================================================================
Handles uploaded file submissions (the "Files" section) - storage in
Azure Blob Storage and generating time-limited download URLs. Mirrors
services/image_handler.py's pattern, but for arbitrary document types
rather than images only.

REQUIRED SETUP: a blob container named "submitted-files" must exist
in the storage account referenced by AZURE_STORAGE_CONNECTION_STRING -
same account as inventory-images, just a separate container. This
code does not create the container automatically (same convention as
image_handler.py).
=====================================================================
"""
from azure.storage.blob import generate_blob_sas, BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from datetime import datetime, timedelta, timezone
import os
import uuid

CONTAINER = "submitted-files"

# Broad blocklist rather than a narrow allowlist: file submissions are
# meant to accept ordinary document types (PDF, DOCX, XLSX, images, etc.)
# without anyone having to guess which extensions to add next. This just
# blocks the common executable/script types that have no legitimate
# reason to be a "form submission."
BLOCKED_EXTENSIONS = (
    ".exe", ".bat", ".cmd", ".sh", ".msi", ".dll",
    ".scr", ".ps1", ".vbs", ".jar", ".app", ".com",
)


def is_allowed_submission_filename(filename):
    if not filename:
        return False
    return not filename.lower().endswith(BLOCKED_EXTENSIONS)


def upload_submission_file(file):
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

    if not connect_str:
        raise Exception("Missing AZURE_STORAGE_CONNECTION_STRING")

    blob_service = BlobServiceClient.from_connection_string(connect_str)
    container_client = blob_service.get_container_client(CONTAINER)

    filename = f"{uuid.uuid4()}_{file.filename}"
    blob_path = f"files/{filename}"

    blob_client = container_client.get_blob_client(blob_path)
    blob_client.upload_blob(file, overwrite=True)

    return blob_path


def generate_file_url(blob_path):
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    blob_service = BlobServiceClient.from_connection_string(connect_str)

    account_name = blob_service.account_name

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=CONTAINER,
        blob_name=blob_path,
        account_key=blob_service.credential.account_key,
        permission="r",
        expiry=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    )

    return f"https://{account_name}.blob.core.windows.net/{CONTAINER}/{blob_path}?{sas_token}"


def delete_submission_file(blob_path):
    """Deletes a submission's blob from storage. Treats 'already gone' as
    success (nothing left to clean up) rather than an error, since the
    caller's goal - the blob not existing - is already satisfied either
    way. Any other failure (auth, network) is left to propagate, since
    the caller should not delete the database row if the blob deletion
    genuinely failed - that would orphan a blob with no record pointing
    to it."""
    connect_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    blob_service = BlobServiceClient.from_connection_string(connect_str)
    container_client = blob_service.get_container_client(CONTAINER)

    blob_client = container_client.get_blob_client(blob_path)
    try:
        blob_client.delete_blob()
    except ResourceNotFoundError:
        pass
