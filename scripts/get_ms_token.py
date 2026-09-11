#!/usr/bin/env python3
"""Run this ONCE, locally, on your own machine.

It signs you into your Microsoft account (device code flow - no Azure portal,
no app registration needed) and grants "read/write my tasks" permission to
Microsoft's own public "Graph Command Line Tools" app.

The refresh token never leaves your machine through this script: it's
encrypted here and written to secrets/ms_token.enc. You then commit that
(encrypted) file yourself and add the printed passphrase as the
SYNC_SECRET_KEY secret in the Claude cloud environment.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from crypto_utils import encrypt  # noqa: E402

CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
SCOPE = "Tasks.ReadWrite offline_access"
DEVICE_CODE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def main():
    resp = post(DEVICE_CODE_URL, {"client_id": CLIENT_ID, "scope": SCOPE})
    if "device_code" not in resp:
        print("Fehler beim Start des Logins:", resp)
        return

    print("\n=== Microsoft-Anmeldung ===")
    print(resp["message"])
    print("(Melde dich mit deinem PRIVATEN Microsoft-Konto an, dem Konto deiner To-Do-Listen.)\n")

    interval = resp.get("interval", 5)
    device_code = resp["device_code"]
    expires_in = resp.get("expires_in", 900)
    start = time.time()

    while time.time() - start < expires_in:
        time.sleep(interval)
        token_resp = post(
            TOKEN_URL,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": CLIENT_ID,
                "device_code": device_code,
            },
        )
        if "access_token" in token_resp:
            refresh_token = token_resp["refresh_token"]
            passphrase = base64.urlsafe_b64encode(os.urandom(24)).decode()
            enc = encrypt(refresh_token, passphrase)

            out_dir = os.path.join(os.path.dirname(__file__), "..", "secrets")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, "ms_token.enc")
            with open(out_path, "wb") as f:
                f.write(enc)

            print("\nErfolgreich angemeldet.")
            print(f"Verschluesselter Token gespeichert unter: {out_path}\n")
            print("NAECHSTE SCHRITTE:")
            print("1. Trage folgenden Wert als Secret 'SYNC_SECRET_KEY' in der Claude-Cloud-Umgebung ein:\n")
            print(f"   {passphrase}\n")
            print("2. Committe und push die neue Datei secrets/ms_token.enc ins Repo:")
            print("   git add secrets/ms_token.enc")
            print('   git commit -m "Add encrypted MS token"')
            print("   git push")
            return

        err = token_resp.get("error")
        if err == "authorization_pending":
            continue
        elif err == "slow_down":
            interval += 5
            continue
        else:
            print("Fehler:", token_resp)
            return

    print("Zeitueberschreitung - bitte das Skript erneut ausfuehren.")


if __name__ == "__main__":
    main()
