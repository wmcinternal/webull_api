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

SERVER_START_TIME=datetime.now()


@app.get("/market-status")
def market_status() -> dict:

    elapsed_seconds = (datetime.now() - SERVER_START_TIME).total_seconds()
    simulated_days_passed = int(elapsed_seconds // 5)

    current_sim_date = SERVER_START_TIME + timedelta(days=simulated_days_passed)
    
    weekday_index = current_sim_date.weekday() # 0=Mon, ..., 5=Sat, 6=Sun
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_name = days[weekday_index]


    is_open = weekday_index < 5

    return {
        "is_open": is_open,
        "day_name": day_name,
        "date_str": current_sim_date.strftime("%Y-%b-%d"),
        "display_text": f"{current_sim_date.strftime('%Y-%b-%d')} ({day_name})",
        "status": "OPEN" if is_open else "CLOSED (Weekend)"
    }





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


    if "order_history" not in account:
        account["order_history"]=[]
    
    account["order_history"].insert(0, {

        "timestamp": account["simulated_date"].strftime("%b %d, %Y %I:%M %p"),
        "type": "RECURRING DCA",
        "symbol": symbol,
        "shares": f"+{shares_bought:.4f}",
        "price": f"{current_price:.2f}",
        "total": f"-{amount:.2f}",
        "status": "FILLED"
    })


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

    if "scheduled_jobs" not in account:
        account["scheduled_jobs"]=[]

    existing_job=next((j for j in account["scheduled_jobs"] if j["symbol"]==order.symbol.upper() ), None)

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


@app.get("/account-summary")
async def get_account_summary(account_id: str):

    if account_id not in accounts_db:
        accounts_db[account_id]={
            "cash_balance": 5000.00,
            "positions":  {},
            "scheduled_jobs": [],
            "order_history": []
        }
    
    account=accounts_db[account_id]

    portfolio_value=0.0
    portfolio={}

    for symbol, pos in account["positions"].items():
        current_price=get_etf_price(symbol)
        market_value=pos["total_shares"]*current_price
        portfolio_value+=market_value
        portfolio[symbol]= {
            "total_shares": pos["total_shares"],
            "total_invested": pos["total_invested"],
            "current_price": current_price,
            "market_value": market_value
    }
    
    net_account_value=account["cash_balance"]+ portfolio_value

    return {
        "account_id": account_id,
        "net_account_value": net_account_value,
        "cash_balance": account["cash_balance"],
        "portfolio": portfolio,
        "scheduled_jobs": account.get("scheduled_jobs", []),
        "order_history": account.get("order_history", [])
    }


class CancelSchedule(BaseModel):
    account_id: str
    symbol: str


@app.post("/cancel-schedule")
async def cancel_schedule(req: CancelSchedule):

    account=accounts_db.get(req.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    
    symbol_upper=req.symbol.upper()
    job_id = f"DCA-{req.account_id}-{symbol_upper}"

    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    
    account["scheduled_jobs"]=[j for j in account.get("scheduled_jobs", []) if symbol_upper!=j["symbol"]]

    return {
        "status": "SUCCESS",
        "message": f"Cancelled recurring order for {symbol_upper}",
        "scheduled_jobs": account["scheduled_jobs"]
    }



@app.post("/execute-now")
async def execute_now(req: ExecuteNowRequest):
    return execute_recurring_dca(req.account_id, req.symbol.upper(), req.amount)




@app.get("/", response_class=HTMLResponse)
async def frontend():
    with open("client.html", encoding="utf-8") as file:
        return file.read()