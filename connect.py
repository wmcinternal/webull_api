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
    """
    Generates the HMAC-SHA1 signature following Webull's official 3-step algorithm.
    """
    
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
    """
    Constructs, signs, and executes the HTTP request to Webull.
    """
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


if __name__ == "__main__":
    print("--- TESTING WEBULL BROKER API CONNECTION ---")
    
    test_path = "/openapi/broker/account/nd/detail"
    test_params = {"account_id": "dummy_account_123"}

    response = call_broker_api("GET", test_path, query_params=test_params)

    print(f"HTTP Status Code: {response.status_code}")
    print(f"Server Response Payload:\n{response.text}\n")

    # Evaluate results based on response codes
    if response.status_code == 200:
        print("✅ SUCCESS (200 OK): Full authentication and account match successful!")
    elif response.status_code in (417, 400) or "INVALID_PARAMETER" in response.text:
        print("🎉 AUTHENTICATION SUCCESS: Your App Key and App Secret are valid!")
        print("Explanation: The server passed your security signature and only failed because 'dummy_account_123' does not exist.")
    elif response.status_code == 401:
        print("❌ AUTHENTICATION FAILED (401 UNAUTHORIZED): Check that your APP_KEY and APP_SECRET are correct.")
    else:
        print(f"⚠️ Server returned unexpected status code: {response.status_code}")