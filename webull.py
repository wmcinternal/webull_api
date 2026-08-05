import os
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient

app=FASTAPI(title="Webull API")

APP_KEY=os.getenv("WEBULL_APP_KEY")
APP_SECRET=os.getenv("WEBULL_APP_SECRET")

api_client=ApiClient(app_key=APP_KEY, app_secret=APP_SECRET, regionId="us")
api_client.add_endpoint("us", "https://broker-api.sandbox.webull.com")
trade_client=TradeCLient(api_client)



@app.post("/execute-order")
async def execute_order(order):

    current_price=get_etf_price(order.symbol);
    est_shares = round(order.amount / current_price, 4)

    short_uuid = uuid.uuid4().hex[:8]
    client_order_id = f"DCA-{order.account_id}-{short_uuid}"[:32]

    new_order_item={

        "client_order_id": client_order_id,
        "symbol": order.symbol.upper(),
        "instrument_type": "EQUITY",
        "side": "BUY",
        "order_type": "MARKET_ON_OPEN",
        "entrust_type": "AMOUNT",
        "total_cash_amount": str(order.amount),
        "time_in_force": "DAY",
        "support_trading_session": "CORE"
    
    }

    try:
        response=trade_client.order_v3.place_order(
            account_id=order.account_id,
            orders=[new_order_item]
        )
        return {
            "status": "SUBMITTED",
            "client_order_id"=client_order_id,
            "estimated_shares": est_shares,
            "webull_response": response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Webull Order Error: {str(e)}")



