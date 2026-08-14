import hashlib
import hmac
import base64
import json
import uuid
import urllib.parse
from datetime import datetime, timezone
import requests
import os

APP_KEY = os.getenv("WEBULL_APP_KEY")
APP_SECRET = os.getenv("WEBULL_APP_SECRET")

HOST = "broker-api.sandbox.webull.hk"
BASE_URL = f"https://{HOST}"


def generate_signature(path, query_params, body_string, app_key, app_secret, host, timestamp, nonce):
    

    signing_headers = {
        "x-app-key": app_key,
        "x-timestamp": timestamp,
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-version": "1.0",
        "x-signature-nonce": nonce,
        "host": host,
    }

    
    all_params = {}
    all_params.update(query_params)
    all_params.update(signing_headers)

    
    str1 = "&".join(f"{k}={all_params[k]}" for k in sorted(all_params.keys()))

    
    if body_string:
        str2 = hashlib.md5(body_string.encode("utf-8")).hexdigest().upper()
        str3 = f"{path}&{str1}&{str2}"
    else:
        str3 = f"{path}&{str1}"

    
    encoded_string = urllib.parse.quote(str3, safe="")

    signing_key = f"{app_secret}&"

    signature = base64.b64encode(
        hmac.new(signing_key.encode("utf-8"), encoded_string.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")

    return signature


def call_broker_api(method, path, query_params=None, body=None):
    
    query_params = query_params or {}
    
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = uuid.uuid4().hex

    body_string = json.dumps(body, separators=(",", ":")) if body else None

    signature = generate_signature(
        path, query_params, body_string,
        APP_KEY, APP_SECRET, HOST, timestamp, nonce
    )

    headers = {
        "x-app-key": APP_KEY,
        "x-timestamp": timestamp,
        "x-signature": signature,
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-version": "1.0",
        "x-signature-nonce": nonce,
        "x-version": "v2",
    }

    url = f"{BASE_URL}{path}"

    print(f"Connecting to: {url}")
    print(f"Generated Timestamp: {timestamp}")
    print(f"Generated Nonce: {nonce}\n")

    if method.upper() == "GET":
        resp = requests.get(url, headers=headers, params=query_params)
    else:
        headers["Content-Type"] = "application/json"
        resp = requests.post(url, headers=headers, data=body_string)

    return resp

    


if __name__=="__main__":

    print("--- CREATING VIRTUAL ACCOUNT ---")

    test_path = "/openapi/broker/account/nd/create"

    master_id="3bf3596d86454f1fa0bbe7d3a8281887"

    payload = {
        "client_request_id": uuid.uuid4().hex.upper()[:32], 
        "belong_account_id": "985245368152788992",
        "account_type": "CASH",
        "trading_permissions": ["US_STOCK_NORMAL"],
        "w8ben_info": {
            "treaty_country": "US",
            "tax_id": "123-45-6789",
            "sign_date": "2026-08-14",
            "first_name": "Test",
            "middle_name": "hello",
            "last_name": "User",
            "home_address": {
              "country": "US",
              "state": "NY",
              "city": "New York",
              "street_address": "1 Wall Street",
              "postal_code": "10005"
            },
            "mail_address": {
              "country": "US",
              "state": "NY",
              "city": "New York",
              "street_address": "1 Wall Street",
              "postal_code": "10005"
            }
        }
    }

    response=call_broker_api("POST", test_path, body=payload)

    print(f"HTTP Status Code: {response.status_code}")

    if response.status_code == 200:

        print("\n✅ SUCCESS! Here is your account list:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"\n❌ FAILED. Server Response:\n{response.text}")

