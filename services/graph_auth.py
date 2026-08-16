"""
graph_auth.py
=====================================================================
Shared Microsoft Graph app-only authentication (CERTIFICATE-based
client credentials flow), used by any feature in this app that needs
to call Graph. Currently used by:
  - services/notifications.py   (low-stock email alerts)
  - services/group_access.py    (Database Settings group restriction)

The certificate is retrieved at runtime from Azure Key Vault using the
App Service's managed identity - see services/notifications.py's
module docstring for the full auth model and Entra/Key Vault
prerequisites, which are shared by everything in this file.

REQUIRED ENVIRONMENT VARIABLES (already configured for notifications):
  ENTRA_TENANT_ID     Directory (tenant) ID from the app Overview page
  ENTRA_CLIENT_ID     Application (client) ID from the app Overview page
  KEY_VAULT_URL       e.g. https://<your-vault-name>.vault.azure.net/
  CERT_NAME           Name of the certificate object in Key Vault
=====================================================================
"""
import os
import base64
import logging
import time

import requests
import msal

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import (Encoding, PrivateFormat, NoEncryption, pkcs12)

logger = logging.getLogger(__name__)

TENANT_ID = os.getenv("ENTRA_TENANT_ID")
CLIENT_ID = os.getenv("ENTRA_CLIENT_ID")
KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")
CERT_NAME = os.getenv("CERT_NAME")

# ".default" tells Entra to issue a token carrying ALL application permissions
# that have been granted + admin-consented on the app registration.
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
REQUEST_TIMEOUT = 30      # seconds; prevents a hung connection from blocking forever
MAX_RETRIES = 3           # number of attempts for transient (429/503) failures

# Module-level cache for the certificate material - Key Vault retrieval is
# done once (lazily) and reused, so we don't hit the vault on every call.
_CERT_CACHE = None  # will hold {"private_key": <PEM str>, "thumbprint": <hex str>}


def request_with_retry(method, url, **kwargs):
    """Wrapper around requests that always applies a timeout and retries on
    Graph throttling (429) and transient errors (503), honoring the
    'Retry-After' header when present. Returns the final Response object
    (caller checks status)."""
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    resp = None
    for attempt in range(MAX_RETRIES):
        resp = requests.request(method, url, **kwargs)

        if resp.status_code in (429, 503) and attempt < MAX_RETRIES - 1:
            retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
            logger.warning(
                "Graph throttled (HTTP %s). Retrying in %ss (attempt %s/%s)",
                resp.status_code, retry_after, attempt + 1, MAX_RETRIES,
            )
            time.sleep(retry_after)
            continue

        return resp

    return resp


def _load_certificate_from_key_vault():
    """Downloads the certificate from Azure Key Vault using the App
    Service's managed identity, and returns the credential dict MSAL
    expects: { "private_key": <PEM private key>, "thumbprint": <SHA-1 hex> }.
    Cached at module level so the vault is only called once."""
    global _CERT_CACHE
    if _CERT_CACHE is not None:
        return _CERT_CACHE

    # DefaultAzureCredential uses the App Service managed identity in Azure.
    # For a USER-assigned identity, set AZURE_CLIENT_ID so the right one is used.
    credential = DefaultAzureCredential()
    secret_client = SecretClient(vault_url=KEY_VAULT_URL, credential=credential)

    cert_secret = secret_client.get_secret(CERT_NAME)
    pfx_bytes = base64.b64decode(cert_secret.value)

    # Key Vault does not password-protect the exported PFX (password is None).
    private_key_obj, certificate_obj, _ = pkcs12.load_key_and_certificates(
        pfx_bytes, password=None
    )

    if private_key_obj is None or certificate_obj is None:
        raise RuntimeError(
            "Key Vault certificate did not contain a private key. "
            "Ensure the certificate is exportable and includes the private key."
        )

    private_key_pem = private_key_obj.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    ).decode("utf-8")

    thumbprint = certificate_obj.fingerprint(hashes.SHA1()).hex().upper()

    _CERT_CACHE = {"private_key": private_key_pem, "thumbprint": thumbprint}
    logger.info(
        "Loaded certificate '%s' from Key Vault (thumbprint %s)",
        CERT_NAME, thumbprint,
    )
    return _CERT_CACHE


def get_graph_token():
    """Acquires an app-only Microsoft Graph access token using the
    CERTIFICATE credential (client credentials flow)."""
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"

    client_credential = _load_certificate_from_key_vault()

    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=authority,
        client_credential=client_credential,
    )

    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)

    if "access_token" not in result:
        raise RuntimeError(
            f"Failed to acquire Graph token: "
            f"{result.get('error')}: {result.get('error_description')}"
        )

    return result["access_token"]
