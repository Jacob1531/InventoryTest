import os
import requests
import msal

TENANT_ID = os.getenv("ENTRA_TENANT_ID")
CLIENT_ID = os.getenv("ENTRA_CLIENT_ID")
CLIENT_SECRET = os.getenv("ENTRA_CLIENT_SECRET")
GROUP_ID = os.getenv("ENTRA_LOW_STOCK_GROUP_ID")
SENDER_EMAIL = os.getenv("NOTIFICATION_SENDER_EMAIL")

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


def _get_graph_token():
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    app = msal.ConfidentialClientApplication(CLIENT_ID, authority=authority, client_credential=CLIENT_SECRET)
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)

    if "access_token" not in result:
        raise Exception(f"Failed to acquire Graph token: {result.get('error_description')}")

    return result["access_token"]


def _get_group_member_emails(group_id, token):
    url = f"https://graph.microsoft.com/v1.0/groups/{group_id}/members?$select=mail,userPrincipalName"
    headers = {"Authorization": f"Bearer {token}"}
    emails = []

    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        for member in data.get("value", []):
            email = member.get("mail") or member.get("userPrincipalName")
            if email:
                emails.append(email)

        url = data.get("@odata.nextLink")

    return emails


def send_low_stock_email(item):
    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET, GROUP_ID, SENDER_EMAIL]):
        raise Exception("Missing Entra/Graph configuration in environment variables")

    token = _get_graph_token()
    recipient_emails = _get_group_member_emails(GROUP_ID, token)

    if not recipient_emails:
        return

    subject = f"Low Stock Alert: {item.name}"
    body = (
        f"Item '{item.name}' (category: {item.category}) has fallen below its "
        f"low stock threshold of {item.low_stock_threshold}.\n\n"
        f"Current quantity: {item.quantity}"
    )

    message = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": e}} for e in recipient_emails]
        },
        "saveToSentItems": "false"
    }

    url = f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    resp = requests.post(url, headers=headers, json=message)
    resp.raise_for_status()