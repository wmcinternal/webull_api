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


def create_virtual_account(belong_account_id, first_name, last_name, tax_id):

    test_path = "/broker/accounts/virtual-accounts/create"

    payload = {
        "client_request_id": uuid.uuid4().hex.upper()[:32], 
        "belong_account_id": belong_account_id, 
        "account_type": "CASH",
        "trading_permissions": ["US_STOCK_NORMAL"],
        "w8ben_info": {
            "treaty_country": "HK",
            "tax_id": tax_id,
            "sign_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "first_name": first_name,
            "middle_name": "NA",
            "last_name": last_name,
            "home_address": {
              "country": "HK",
              "state": "Hong Kong",
              "city": "Central",
              "street_address": "1 Queen's Road",
              "postal_code": "999077"
            },
            "mail_address": {
              "country": "HK",
              "state": "Hong Kong",
              "city": "Central",
              "street_address": "1 Queen's Road",
              "postal_code": "999077"
            }
        }
    }


    response = call_broker_api("POST", test_path, body=payload)
    return response
    
def deposit_to_va(master_id, va_id, amount, currency="USD"):

    path = "/broker/journals/cash-journals/create"

    payload = {
        "client_request_id": uuid.uuid4().hex.upper()[:32], 
        "from_account": master_id,
        "to_account": va_id,
        "currency": currency,
        "amount": str(amount)  
    }

    response=call_broker_api("POST", path, body=payload)
    return response


def get_virtual_account_details(va_id):

    path = "/broker/accounts/virtual-accounts/get"

    query_params = {"account_id": va_id}

    response= call_broker_api("GET", path, query_params=query_params)
    return response


def get_account_balance(account_id):

    path = "/broker/assets/balances/get"
    query_params = {"account_id": account_id}

    response = call_broker_api("GET", path, query_params=query_params)
    return response


def instant_funding(account_id, amount, currency="USD"):

    path="/broker/funding/instant-funding/create"

    payload = {
        "client_request_id": uuid.uuid4().hex.upper()[:32], 
        "account_id": account_id,
        "type": "DEPOSIT",
        "currency": currency,
        "amount": str(amount)
    }

    response = call_broker_api("POST", path, body=payload)
    return response



def get_account_positions(account_id):

    path= "/broker/assets/positions/list"

    query_params= {"account_id": account_id}

    response=call_broker_api("GET", path, query_params=query_params)
    return response



def instant_withdrawal(account_id, amount, currency="USD"):

    path = "/broker/funding/instant-funding/create"

    payload = {
        "client_request_id": uuid.uuid4().hex.upper()[:32], 
        "account_id": account_id,
        "type": "WITHDRAWAL",  # This is the only line that changes!
        "currency": currency,
        "amount": str(amount)
    }

    response = call_broker_api("POST", path, body=payload)
    return response



def place_order_by_amount(account_id, symbol, amount, side="BUY", market="US"):

    path="/broker/orders/place"

    payload={
        "account_id": account_id,
        "new_orders": [
            {
                "combo_type": "NORMAL",
                "client_order_id": uuid.uuid4().hex.upper()[:32],
                "instrument_type": "EQUITY",
                "market": market,
                "symbol": symbol.upper(),
                "order_type": "MARKET",
                "entrust_type": "AMOUNT", # Tells Webull we are trading by dollar amount
                "total_cash_amount": str(amount),
                "support_trading_session": "ALL_DAY",
                "time_in_force": "DAY",
                "side": side.upper()
            }
        ]
    }

    return call_broker_api("POST", path, body=payload)


def place_order_by_qty(account_id, symbol, quantity, side="SELL", market="US"):

    path="/broker/orders/place"

    payload = {
        "account_id": account_id,
        "new_orders": [
            {
                "combo_type": "NORMAL",
                "client_order_id": uuid.uuid4().hex.upper()[:32],
                "instrument_type": "EQUITY",
                "market": market,
                "symbol": symbol.upper(),
                "order_type": "MARKET",
                "entrust_type": "QTY", # Tells Webull we are trading by share count
                "quantity": str(quantity),
                "support_trading_session": "CORE",
                "time_in_force": "DAY",
                "side": side.upper()
            }
        ]
    }

    return call_broker_api("POST", path, body=payload)

def place_limit_order(account_id, symbol, quantity, limit_price, side="BUY", market="US"):
    
    path = "/broker/orders/place"
    
    payload = {
        "account_id": account_id,
        "new_orders": [
            {
                "combo_type": "NORMAL",
                "client_order_id": uuid.uuid4().hex.upper()[:32],
                "instrument_type": "EQUITY",
                "market": market,
                "symbol": symbol.upper(),
                "order_type": "LIMIT",
                "entrust_type": "QTY", 
                "quantity": str(quantity),
                "limit_price": str(limit_price),
                "support_trading_session": "ALL_DAY", 
                "time_in_force": "DAY",
                "side": side.upper()
            }
        ]
    }
    
    return call_broker_api("POST", path, body=payload)

if __name__=="__main__":

    ALICE_VA_ID = "0380EFNIKU8CP0K8C9B4000000"

    print("--- 1. CHECKING ALICE'S CURRENT WALLET ---")
    balance_resp = get_account_balance(ALICE_VA_ID)
    
    if balance_resp.status_code == 200:
        print(json.dumps(balance_resp.json(), indent=2))
    else:
        print(f"❌ Balance Check Failed:\n{balance_resp.text}")
        
    print("\n--- 2. ATTEMPTING ANOTHER DEPOSIT ---")
    deposit_resp = instant_funding(ALICE_VA_ID, "50000.00", "USD")
    if deposit_resp.status_code == 200:
        print(json.dumps(deposit_resp.json(), indent=2))
    else:
        print(f"❌ Deposit Failed:\n{deposit_resp.text}")