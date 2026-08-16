"""
notification.py
=====================================================================
Sends a "low stock" alert email to the members of an Entra ID group,
using Microsoft Graph and CERTIFICATE-based app-only authentication.

The certificate is retrieved at runtime from AZURE KEY VAULT using the
App Service's MANAGED IDENTITY. No private key is ever stored on the
App Service filesystem.

Shared Graph authentication (certificate retrieval + token acquisition
+ the retrying request helper) lives in services/graph_auth.py, since
services/group_access.py (the Database Settings group restriction)
also needs to call Graph using the same app registration.

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
import logging

from services.graph_auth import get_graph_token, request_with_retry, GRAPH_BASE, TENANT_ID, CLIENT_ID, KEY_VAULT_URL, CERT_NAME

# Logging: use a module-level logger so the host app controls output/handlers.
logger = logging.getLogger(__name__)

# Configuration specific to the low-stock email feature.
GROUP_ID = os.getenv("ENTRA_LOW_STOCK_GROUP_ID")
SENDER_EMAIL = os.getenv("NOTIFICATION_SENDER_EMAIL")


def _get_group_member_emails(group_id, token):
    # $top=999 reduces the number of round-trips for large groups.
    url = (f"{GRAPH_BASE}/groups/{group_id}/transitiveMembers/microsoft.graph.user"
        "?$select=mail,userPrincipalName&$top=999")
    headers = {"Authorization": f"Bearer {token}"}

    # A set naturally de-duplicates users that appear via multiple nested groups.
    emails = set()

    while url:
        resp = request_with_retry("GET", url, headers=headers)

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
    token = get_graph_token()
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

    resp = request_with_retry("POST", url, headers=headers, json=message)

    # A successful sendMail returns HTTP 202 (Accepted) with an empty body.
    if not resp.ok:
        raise RuntimeError(f"Failed to send mail: {resp.status_code} {resp.text}")

    logger.info(
        "Low stock alert sent for '%s' to %d recipient(s)",
        item.name, len(recipient_emails),
    )
