"""Minimal Microsoft Graph client for Microsoft To Do (delegated, device-code auth).

Uses Microsoft's own public "Microsoft Graph Command Line Tools" client ID, so
no Azure app registration is required. Auth is a plain user sign-in (device
code flow), consented once locally via get_ms_token.py.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from crypto_utils import decrypt, encrypt

MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID", "14d82eec-204b-4c2f-b7e8-296a70dab67e")
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPE = "Tasks.ReadWrite offline_access"
LINK_APP_NAME = "GCalToDoSync"

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "..", "secrets", "ms_token.enc")


def _http(method, url, headers=None, form_data=None, json_body=None):
    headers = dict(headers or {})
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form_data is not None:
        body = urllib.parse.urlencode(form_data).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"error": raw.decode(errors="replace")}


def _load_refresh_token():
    passphrase = os.environ["SYNC_SECRET_KEY"]
    with open(TOKEN_FILE, "rb") as f:
        return decrypt(f.read(), passphrase)


def _save_refresh_token(token):
    passphrase = os.environ["SYNC_SECRET_KEY"]
    with open(TOKEN_FILE, "wb") as f:
        f.write(encrypt(token, passphrase))


def get_access_token():
    refresh_token = _load_refresh_token()
    status, resp = _http(
        "POST",
        TOKEN_URL,
        form_data={
            "client_id": MS_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": SCOPE,
        },
    )
    if status != 200:
        raise RuntimeError(f"Token refresh failed ({status}): {resp}")
    if "refresh_token" in resp:
        _save_refresh_token(resp["refresh_token"])
    return resp["access_token"]


def _graph(method, path, access_token, data=None):
    status, resp = _http(
        method,
        f"{GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        json_body=data,
    )
    if status >= 400:
        raise RuntimeError(f"Graph {method} {path} failed ({status}): {resp}")
    return resp


def _list_all(path, access_token):
    items = []
    while path:
        resp = _graph("GET", path, access_token)
        items.extend(resp.get("value", []))
        next_link = resp.get("@odata.nextLink")
        path = next_link.replace(GRAPH_BASE, "") if next_link else None
    return items


def list_lists(access_token):
    return _list_all("/me/todo/lists?$top=50", access_token)


def list_tasks(list_id, access_token):
    return _list_all(f"/me/todo/lists/{list_id}/tasks?$top=100", access_token)


def linked_event_id(task):
    for res in task.get("linkedResources") or []:
        if res.get("applicationName") == LINK_APP_NAME:
            return res.get("externalId")
    return None


def create_task(list_id, title, due_date, access_token, linked_event_id_value=None):
    payload = {"title": title}
    if due_date:
        payload["dueDateTime"] = {"dateTime": f"{due_date}T00:00:00.0000000", "timeZone": "UTC"}
    if linked_event_id_value:
        payload["linkedResources"] = [
            {
                "applicationName": LINK_APP_NAME,
                "displayName": "Google Calendar",
                "externalId": linked_event_id_value,
            }
        ]
    return _graph("POST", f"/me/todo/lists/{list_id}/tasks", access_token, data=payload)


def update_task(list_id, task_id, access_token, title=None, due_date=None, status=None):
    payload = {}
    if title is not None:
        payload["title"] = title
    if due_date is not None:
        payload["dueDateTime"] = {"dateTime": f"{due_date}T00:00:00.0000000", "timeZone": "UTC"}
    if status is not None:
        payload["status"] = status
    return _graph("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", access_token, data=payload)


def add_linked_resource(list_id, task_id, event_id, access_token):
    # linkedResources is a navigation property - Graph rejects it inside a
    # task PATCH ("Update on linkedResource navigation property is not
    # supported"). It has to be posted to its own sub-collection endpoint.
    payload = {
        "applicationName": LINK_APP_NAME,
        "displayName": "Google Calendar",
        "externalId": event_id,
    }
    return _graph(
        "POST", f"/me/todo/lists/{list_id}/tasks/{task_id}/linkedResources", access_token, data=payload
    )


def delete_task(list_id, task_id, access_token):
    return _graph("DELETE", f"/me/todo/lists/{list_id}/tasks/{task_id}", access_token)
