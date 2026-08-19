import os
import uuid
import json
from datetime import datetime, timedelta
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from apscheduler.schedulers.background import BackgroundScheduler
from database import init_db, load_db, save_db

from connect import (

    instant_funding,
    instant_withdrawal,
    get_account_balance,
    get_account_positions,
    place_limit_order,
    place_order_by_amount,
    place_order_by_qty,
    create_virtual_account

)

init_db()
accounts_db=load_db()

MASTER_ACCOUNT_ID=""


APP_KEY=os.getenv("WEBULL_APP_KEY")
APP_SECRET=os.getenv("WEBULL_APP_SECRET")

app=FastAPI(title="Webull API")

scheduler=BackgroundScheduler()
scheduler.start()


SERVER_START_TIME=datetime.now()



@app.get("/market-status")
def market_status() -> dict:

    elapsed_seconds = (datetime.now() - SERVER_START_TIME).total_seconds()
    simulated_days_passed = int(elapsed_seconds // 5)

    current_sim_date = SERVER_START_TIME + timedelta(days=simulated_days_passed)
    
    weekday_index = current_sim_date.weekday()   
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

class SellOrderReq(BaseModel):
    account_id: str
    symbol: str
    shares: float


@app.get("/account-summary")
async def get_account_summary(account_id: str):

    if account_id not in accounts_db:
        print(f"Client '{account_id}' not found. Creating new Webull Virtual Account...")
        
        create_resp = create_virtual_account(MASTER_ACCOUNT_ID, "Client", account_id, "000000000")
        
        if create_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Webull Account Creation Failed: {create_resp.text}")

       
        new_va_data = create_resp.json()
        new_va_id = new_va_data.get("account_id")
        
        accounts_db[account_id] = {
            "va_id": new_va_id,
            "scheduled_jobs": [],
            "order_history": []
        }
        save_db(accounts_db) # Save the new row to the JSON file immediately!
        print(f"✅ Assigned Webull VA {new_va_id} to Client {account_id}")
        
    
    va_id = accounts_db[account_id]["va_id"]
    
    
    balance_resp = get_account_balance(va_id)
    if balance_resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Webull Balance Check Failed: {balance_resp.text}")
    
    bal_data = balance_resp.json()
    
    usd_cash = 0.0
    for asset in bal_data.get("account_currency_assets", []):
        if asset.get("currency") == "USD":
            usd_cash = float(asset.get("cash_balance", 0.0))


    pos_resp = get_account_positions(va_id)
    if pos_resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Webull Positions Check Failed: {pos_resp.text}")


    pos_data = pos_resp.json()
    portfolio = {}
    portfolio_value = 0.0


    positions_list = pos_data if isinstance(pos_data, list) else pos_data.get("positions", [])
    for pos in positions_list:
    
        symbol = pos.get("ticker", pos.get("symbol", "UNKNOWN"))
        shares = float(pos.get("quantity", 0.0))
        market_val = float(pos.get("market_value", 0.0))
        
        portfolio_value += market_val
        portfolio[symbol] = {
            "total_shares": shares,
            "total_invested": market_val, 
            "current_price": float(pos.get("last_price", 0.0)),
            "market_value": market_val
        }

    net_account_value = usd_cash + portfolio_value

    return {
        "account_id": account_id,
        "net_account_value": net_account_value,
        "cash_balance": usd_cash,
        "portfolio": portfolio,
        "scheduled_jobs": accounts_db[account_id].get("scheduled_jobs", []),
        "order_history": accounts_db[account_id].get("order_history", [])
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


class CashOperationReq(BaseModel):
    account_id: str
    amount: float


@app.post("/deposit")
async def deposit(req: CashOperationReq):

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be greater than $0.")

    if req.account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found in database. Load summary first.")

    va_id=accounts_db[req.account_id]["va_id"]

    resp=instant_funding(va_id, req.amount, "USD")

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Webull Error: {resp.text}")

    return {"status": "SUCCESS", "message": f"Successfully deposited ${req.amount} via Webull!"}



@app.post("/withdraw")
async def withdraw(req: CashOperationReq):

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Withdrawal amount must be greater than $0.")

    if req.account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found in database.")
        
    va_id = accounts_db[req.account_id]["va_id"]

    resp=instant_withdrawal(va_id, req.amount, "USD")

    if resp.status_code!=200:
        raise HTTPException(status_code=400, detail=f"Webull Error: {resp.text}")

    return {"status": "SUCCESS", "message": f"Successfully withdrew ${req.amount} via Webull!"}




@app.post("/execute-now")
async def execute_now(req: ExecuteNowRequest):

    if req.amount < 5.00:
        raise HTTPException(status_code=400, detail="Minimum buy order size is $5.00 USD.")

    if req.account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found. Load summary first.")
        
    va_id = accounts_db[req.account_id]["va_id"]
    symbol_upper = req.symbol.strip().upper()

    resp = place_order_by_amount(va_id, symbol_upper, req.amount, side="BUY")

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Webull Order Failed: {resp.text}")

    return {"status": "SUCCESS", "message": f"Successfully placed BUY order for ${req.amount} of {symbol_upper}!"}



@app.post("/sell-stock")
async def sell_stock(req: SellOrderReq):

    if req.shares < 0.0001:
        raise HTTPException(status_code=400, detail="Minimum sell order quantity is 0.0001 shares.")

    if req.account_id not in accounts_db:
        raise HTTPException(status_code=404, detail="Account not found. Load summary first.")
        
    va_id = accounts_db[req.account_id]["va_id"]
    symbol_upper = req.symbol.strip().upper()

    resp = place_order_by_qty(va_id, symbol_upper, req.shares, side="SELL")

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Webull Sell Failed: {resp.text}")

    return {"status": "SUCCESS", "message": f"Successfully placed SELL order for {req.shares} shares of {symbol_upper}!"}



@app.get("/", response_class=HTMLResponse)
async def frontend():
    with open("client.html", encoding="utf-8") as file:
        return file.read()