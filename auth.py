from flask import request

def get_user():
    return request.headers.get(
        "X-MS-CLIENT-PRINCIPAL-NAME",
        "unknown"
    )

def get_user_id():
    """Returns the signed-in user's Entra object ID (the 'oid' claim),
    injected by Azure App Service Easy Auth. Used for Microsoft Graph
    calls (e.g. group membership checks) where a stable ID is needed
    rather than the display name/UPN that get_user() returns."""
    return request.headers.get("X-MS-CLIENT-PRINCIPAL-ID")
