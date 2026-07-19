"""
notification.py
=====================================================================
Sends a "low stock" alert email to the members of an Entra ID group,
using Microsoft Graph and CERTIFICATE-based app-only authentication.

The certificate is retrieved at runtime from AZURE KEY VAULT using the
App Service's MANAGED IDENTITY. No private key is ever stored on the
App Service filesystem.

AUTHENTICATION MODEL
--------------------
1. App Service has a managed identity (system- or user-assigned).
2. That managed identity is granted read access to the certificate in
   Azure Key Vault (RBAC role "Key Vault Secrets User", or an access
   policy with Get on secrets/certificates).
3. At startup the app authenticates to Key Vault with the managed
   identity (DefaultAzureCredential) and downloads the certificate
   (private key + public cert) into MEMORY only.
4. The app then uses that certificate to authenticate to Microsoft
   Graph via the OAuth 2.0 client credentials flow (MSAL), and sends
   mail as the shared mailbox.

ENTRA / EXCHANGE PREREQUISITES (already configured):
  - App registration:            inventory-app-notifications
  - Certificate:                 public .cer uploaded to the app registration;
                                 full cert (with private key) stored in Key Vault
  - Application permissions:     Mail.Send, GroupMember.Read.All (admin-consented)
  - Sender mailbox:              dcs-inventory-alerts@diasporacs.org (shared mailbox)
  - ApplicationAccessPolicy:     restricts this app to send ONLY as the
                                 shared mailbox above (RestrictAccess)

REQUIRED ENVIRONMENT VARIABLES (already configured):
  ENTRA_TENANT_ID              Directory (tenant) ID from the app Overview page
  ENTRA_CLIENT_ID              Application (client) ID from the app Overview page
  KEY_VAULT_URL                e.g. https://<your-vault-name>.vault.azure.net/
  CERT_NAME                    Name of the certificate object in Key Vault
  ENTRA_LOW_STOCK_GROUP_ID     Object ID of the recipient group
  NOTIFICATION_SENDER_EMAIL    dcs-inventory-alerts@diasporacs.org

  (Optional - only if using a USER-assigned managed identity)
  AZURE_CLIENT_ID              Client ID of the user-assigned managed identity,
                               so DefaultAzureCredential selects the right one.

DEPENDENCIES:
  msal requests azure-identity azure-keyvault-secrets cryptography
  
=====================================================================
"""
import os
import requests
import msal
import base64
import logging

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import (Encoding, PrivateFormat, NoEncryption, pkcs12)

# Logging: use a module-level logger so the host app controls output/handlers.
logger = logging.getLogger(__name__)

# Configuration is read from environment variables so no secrets or paths are hard-coded in source. These are read once at import time.
TENANT_ID = os.getenv("ENTRA_TENANT_ID")
CLIENT_ID = os.getenv("ENTRA_CLIENT_ID")
CLIENT_SECRET = os.getenv("ENTRA_CLIENT_SECRET")
GROUP_ID = os.getenv("ENTRA_LOW_STOCK_GROUP_ID")
SENDER_EMAIL = os.getenv("NOTIFICATION_SENDER_EMAIL")
KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")        # https://<vault>.vault.azure.net/
CERT_NAME = os.getenv("CERT_NAME")                # certificate name in Key Vault

# ".default" tells Entra to issue a token carrying ALL application permissions that have been granted + admin-consented on the app registration.
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

# Base URL and tuning knobs kept as constants for easy maintenance.
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
REQUEST_TIMEOUT = 30      # seconds; prevents a hung connection from blocking forever
MAX_RETRIES = 3           # number of attempts for transient (429/503) failures

# Module-level cache for the certificate material. Key Vault retrieval is done once (lazily) and reused, so we don't hit the vault on every email send

_CERT_CACHE = None  # will hold {"private_key": <PEM str>, "thumbprint": <hex str>}

"""
Wrapper around requests that:
    - always applies a timeout (avoids indefinitely hanging calls), and
    - retries on Graph throttling (HTTP 429) and transient errors (HTTP 503),
    honoring the 'Retry-After' header when present.
Returns the final Response object (caller checks status).
"""
def _request_with_retry(method, url, **kwargs):
    kwargs.setdefault("timeout", REQUEST_TIMEOUT)
    for attempt in range(MAX_RETRIES):
        resp = requests.request(method, url, **kwargs)

        # 429 = throttled, 503 = service temporarily unavailable -> worth retrying.
        if resp.status_code in (429, 503) and attempt < MAX_RETRIES - 1:
            # Respect the server's Retry-After hint; fall back to exponential backoff.
            retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
            logger.warning(
                "Graph throttled (HTTP %s). Retrying in %ss (attempt %s/%s)",
                resp.status_code, retry_after, attempt + 1, MAX_RETRIES,
            )
            time.sleep(retry_after)
            continue

        return resp

    # If every attempt was throttled, return the last response for the caller to handle.
    return resp

"""
Download the certificate from Azure Key Vault using the App Service's
managed identity, and return the credential dict MSAL expects:
    { "private_key": <PEM private key>, "thumbprint": <SHA-1 hex> }

Notes:
    - When a certificate is created/imported in Key Vault, its full contents
    (private key + cert chain) are exposed as a SECRET with the SAME name.
    We read that secret to obtain the private key material.
    - Non-exportable Key Vault certificates cannot be retrieved this way; the
    certificate must be created as exportable for app-only cert auth.
    - The result is cached at module level so we only call the vault once.
"""
def _load_certificate_from_key_vault():
    
    global _CERT_CACHE
    if _CERT_CACHE is not None:
        return _CERT_CACHE

    # DefaultAzureCredential uses the App Service managed identity in Azure.
    # For a USER-assigned identity, set AZURE_CLIENT_ID so the right one is used.
    credential = DefaultAzureCredential()
    secret_client = SecretClient(vault_url=KEY_VAULT_URL, credential=credential)

    # Reading the certificate as a secret returns the full PKCS#12 (PFX) bundle,
    # base64-encoded, when contentType is application/x-pkcs12 (the default for
    # Key Vault-generated/imported certs). We decode and parse it with cryptography.
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

    # Serialize the private key to unencrypted PEM (held in memory only).
    private_key_pem = private_key_obj.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    ).decode("utf-8")

    # Compute the SHA-1 thumbprint MSAL uses to identify the cert to Entra.
    thumbprint = certificate_obj.fingerprint(hashes.SHA1()).hex().upper()

    _CERT_CACHE = {"private_key": private_key_pem, "thumbprint": thumbprint}
    logger.info(
        "Loaded certificate '%s' from Key Vault (thumbprint %s)",
        CERT_NAME, thumbprint,
    )
    return _CERT_CACHE

"""
Acquire an app-only Microsoft Graph access token using the CERTIFICATE
credential (client credentials flow). The certificate is pulled from
Key Vault via the managed identity; no private key is read from disk.
"""
def _get_graph_token():
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"

    # Retrieve (and cache) the certificate material from Key Vault.
    client_credential = _load_certificate_from_key_vault()

    # A ConfidentialClientApplication represents this daemon app's identity.
    # (Reusing a single instance also benefits from MSAL's in-memory token cache.)
    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=authority,
        client_credential=client_credential,
    )

    # acquire_token_for_client is the app-only call (no user context/account).
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)

    # On failure, MSAL returns an error dict rather than raising; surface details.
    if "access_token" not in result:
        raise RuntimeError(
            f"Failed to acquire Graph token: "
            f"{result.get('error')}: {result.get('error_description')}"
        )

    return result["access_token"]

"""
Return a de-duplicated, sorted list of member email addresses for the group.

Uses the 'transitiveMembers' endpoint with a '/microsoft.graph.user' type
cast so that:
    - NESTED group members are expanded (transitive), and
    - only USER objects are returned (not devices/service principals/etc.).
Results are paged (Graph returns @odata.nextLink for large groups).
"""
def _get_group_member_emails(group_id, token):
    # $top=999 reduces the number of round-trips for large groups.
    url = (f"{GRAPH_BASE}/groups/{group_id}/transitiveMembers/microsoft.graph.user"
        "?$select=mail,userPrincipalName&$top=999")
    headers = {"Authorization": f"Bearer {token}"}

    # A set naturally de-duplicates users that appear via multiple nested groups.
    emails = set()

    while url:
        resp = _request_with_retry("GET", url, headers=headers)

        # Surface the Graph error body to make permission/config issues debuggable.
        if not resp.ok:
            raise RuntimeError(
                f"Failed to list group members: {resp.status_code} {resp.text}"
            )

        data = resp.json()

        for member in data.get("value", []):
            # Prefer the routable 'mail' attribute; fall back to UPN if absent.
            email = member.get("mail")
            if not email:
                email = member.get("userPrincipalName")
                # UPN is not always a real mailbox address; log so it's visible.
                logger.warning("Member has no mailbox; falling back to UPN: %s", email)
            if email:
                emails.add(email)

        # Follow pagination until Graph stops returning a next page.
        url = data.get("@odata.nextLink")

    return sorted(emails)

"""
    Send a low-stock alert about `item` to all members of the configured group.

    `item` is expected to expose: name, category, low_stock_threshold, quantity.
    """
def send_low_stock_email(item):
    # Fail fast if any required configuration is missing.
    if not all([TENANT_ID, CLIENT_ID, KEY_VAULT_URL, CERT_NAME, GROUP_ID, SENDER_EMAIL]):
        raise RuntimeError("Missing Entra/Graph/Key Vault configuration in environment variables")

    # 1) Authenticate (cert-based, cert from Key Vault) and 2) resolve recipients.
    token = _get_graph_token()
    recipient_emails = _get_group_member_emails(GROUP_ID, token)

    # If the group is empty/misconfigured, log a warning instead of failing silently.
    if not recipient_emails:
        logger.warning("No recipients found in group %s; skipping low stock email", GROUP_ID)
        return

    # Compose the message body.
    subject = f"Low Stock Alert: {item.name}"
    body = (
        f"Item '{item.name}' (category: {item.category}) has fallen below its "
        f"low stock threshold of {item.low_stock_threshold}.\n\n"
        f"Current quantity: {item.quantity}"
    )

    # Recipients go in BCC so members are not exposed to one another, and the
    # visible 'To' is the alerts mailbox itself. saveToSentItems is a real
    # boolean (JSON false), not the string "false".
    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": SENDER_EMAIL}}],
            "bccRecipients": [
                {"emailAddress": {"address": e}} for e in recipient_emails
            ],
        },
        "saveToSentItems": False,
    }

    # sendMail runs as the shared mailbox. The ApplicationAccessPolicy in Exchange
    # ensures this app can ONLY send as SENDER_EMAIL and no other mailbox.
    url = f"{GRAPH_BASE}/users/{SENDER_EMAIL}/sendMail"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    resp = _request_with_retry("POST", url, headers=headers, json=message)

    # A successful sendMail returns HTTP 202 (Accepted) with an empty body.
    if not resp.ok:
        raise RuntimeError(f"Failed to send mail: {resp.status_code} {resp.text}")

    logger.info(
        "Low stock alert sent for '%s' to %d recipient(s)",
        item.name, len(recipient_emails),
    )
