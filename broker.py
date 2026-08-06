import os
import uuid
from datetime import datetime
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient
from apscheduler.schedulers.background import BackgroundScheduler


app=FastAPI(title="Webull API")

scheduler=BackgroundScheduler()
scheduler.start()

APP_KEY=os.getenv("WEBULL_APP_KEY")
APP_SECRET=os.getenv("WEBULL_APP_SECRET")




accounts_db = {
    "C8193691": {
        "cash_balance": 1000.00,  
        "positions": {
            "SCHX": {
                "total_shares": 0.0,
                "total_invested": 0.0
            },
            "AGG": {
                "total_shares": 0.0,
                "total_invested": 0.0
            }
        }
    }
}

trade_client=None
if APP_KEY and APP_SECRET:
    try:
                
        api_client=ApiClient(app_key=APP_KEY, app_secret=APP_SECRET, region_id="us")
        api_client.add_endpoint("us", "https://broker-api.sandbox.webull.com")
        trade_client=TradeClient(api_client)
        print("Successfully initialized Webull Sandbox SDK.")
    
    except Exception as e:
        print(f"Webull SDK init failed ({e}). Defaulting to MOCK MODE.")
else:
    print("No Webull API credentials found in environment. Running in MOCK MODE.")


class ValidateOrder(BaseModel):
    account_id: str
    symbol: str
    amount: float
    day_of_month: int =Field(..., ge=1, le=28)


def get_etf_price(symbol: str) -> float:
    ticker=yf.Ticker(symbol)
    return round(float(ticker.fast_info['lastPrice']), 2)



def execute_recurring_dca(account_id: str, symbol: str, amount: float):

    account=accounts_db.get(account_id)
    if not account:
        print(f"❌ Account {account_id} not found.")
        return

    if account["cash_balance"] < amount:
        print(f"❌ Insufficient funds for {account_id}. Balance: ${account['cash_balance']}")
        return

    current_price = get_etf_price(symbol)
    shares_bought = round(amount / current_price, 4)

    account["cash_balance"] -= amount

    if symbol not in account["positions"]:
        account["positions"][symbol] = {"total_shares": 0.0, "total_invested": 0.0}

    account["positions"][symbol]["total_shares"] += shares_bought
    account["positions"][symbol]["total_invested"] += amount

    print(f"✅ DCA Order Executed for {account_id}:")
    print(f"   Bought: {shares_bought} shares of {symbol} @ ${current_price}")
    print(f"   Remaining Cash: ${round(account['cash_balance'], 2)}")
    print(f"   Total Portfolio Shares in {symbol}: {round(account['positions'][symbol]['total_shares'], 4)}")


@app.post("/schedule-order")
async def schedule_order(order: ValidateOrder):


    if order.account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account ID not found in database.")

    job_id = f"DCA-{order.account_id}-{order.symbol.upper()}"



    scheduler.add_job(
        execute_recurring_dca,
        trigger="cron",
        day=order.day_of_month,
        hour=9,
        minute=30,
        args=[order.account_id, order.symbol.upper(), order.amount],
        id=job_id,
        replace_existing=True
    )

    return {
        "status": "RECURRING_SCHEDULED",
        "frequency": "MONTHLY",
        "execution_day": f"Day {order.day_of_month} of every month at 09:30 AM",
        "account_id": order.account_id,
        "current_cash": accounts_db[order.account_id]["cash_balance"]
    }


class ExecuteNowRequest(BaseModel):
    account_id: str
    symbol: str
    amount: float


@app.post("/execute-now")
async def execute_now(req: ExecuteNowRequest):
    if req.account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found.")

    
    execute_recurring_dca(req.account_id, req.symbol.upper(), req.amount)

    account = accounts_db[req.account_id]
    pos = account["positions"].get(req.symbol.upper(), {})

    return {
        "status": "EXECUTED",
        "account_id": req.account_id,
        "symbol": req.symbol.upper(),
        "remaining_cash": round(account["cash_balance"], 2),
        "total_shares": round(pos.get("total_shares", 0.0), 4),
        "total_invested": round(pos.get("total_invested", 0.0), 2),
    }




@app.get("/", response_class=HTMLResponse)
async def frontend():
    with open("client.html") as file:
        return file.read()