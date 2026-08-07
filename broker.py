import os
import uuid
from datetime import datetime, timedelta
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
        "cash_balance": 5000.00,  
        "positions": {},
        "scheduled_jobs": []
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
        return {"status": "FAILED", "reason": f"Account {account_id} not found."}

    if account["cash_balance"] < amount:
        return {
            "status": "FAILED",
            "reason": f"Insufficient funds. Balance: ${account['cash_balance']:.2f}"
        }
    
    if "simulated_date" not in account:
        account["simulated_date"] = datetime.now()
    else:
        account["simulated_date"] += timedelta(days=30)

    current_price = get_etf_price(symbol)
    shares_bought = round(amount / current_price, 4)

    account["cash_balance"] -= amount

    if symbol not in account["positions"]:
        account["positions"][symbol] = {"total_shares": 0.0, "total_invested": 0.0}

    account["positions"][symbol]["total_shares"] += shares_bought
    account["positions"][symbol]["total_invested"] += amount

    return {
        "status": "SUCCESS",
        "execution_date": account["simulated_date"].strftime("%b %d, %Y"),
        "symbol": symbol,
        "amount_spent": amount,
        "buy_price": current_price,
        "shares_bought": shares_bought,
        "remaining_cash": account["cash_balance"],
        "portfolio": account["positions"]
    }

@app.post("/schedule-order")
async def schedule_order(order: ValidateOrder):

    account=accounts_db.get(order.account_id)

    if not account:
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

    if "schedule_jobs" not in account:
        account["scheduled_jobs"]=[]

    existing_job=next((j for h in account["scheduled_jobs"] if j["symbol"]==order.symbol.upper() ), None)

    if existing_job:
        existing_job["amount"] = order.amount
        existing_job["day_of_month"] = order.day_of_month
    else:
        account["scheduled_jobs"].append({
            "symbol": order.symbol.upper(),
            "amount": order.amount,
            "day_of_month": order.day_of_month
        })


    return {
        "account_id": order.account_id,
        "status": "RECURRING_SCHEDULED",
        "symbol": order.symbol.upper(),
        "amount": order.amount,
        "execution_day": f"Day {order.day_of_month} of every month at 09:30 AM"

    }

class ExecuteAllRequest(BaseModel):
    account_id: str


@app.post("/execute-all-schedules")
async def execute_all_schedules(req: ExecuteAllRequest):
    account = accounts_db.get(req.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")

    schedules = account.get("scheduled_jobs", [])
    if not schedules:
        return {"status": "FAILED", "reason": "No active DCA schedules found. Please schedule an order first!"}

    executed_trades = []
    
    
    for job in schedules:
        result = execute_recurring_dca(req.account_id, job["symbol"], job["amount"])
        if result["status"] == "FAILED":
            return result
        executed_trades.append(result)

    last_trade_date = executed_trades[-1].get("execution_date", "N/A") if executed_trades else "N/A"

    return {
        "status": "SUCCESS",
        "execution_date": last_trade_date,
        "remaining_cash": account["cash_balance"],
        "trades_executed": executed_trades,
        "portfolio": account["positions"]
    }


class ExecuteNowRequest(BaseModel):
    account_id: str
    symbol: str
    amount: float


@app.post("/execute-now")
async def execute_now(req: ExecuteNowRequest):
    return execute_recurring_dca(req.account_id, req.symbol.upper(), req.amount)




@app.get("/", response_class=HTMLResponse)
async def frontend():
    with open("client.html", encoding="utf-8") as file:
        return file.read()