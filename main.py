from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import os

app = FastAPI()

# === Авторизация Google Sheets ===
try:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file("service_account.json", scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open("RingBot").sheet1
except Exception as e:
    print("❌ Google Sheets init error:", e)
    sheet = None

# === Telegram уведомление (заглушка) ===
def notify_telegram(name: str, phone: str):
    print(f"📲 New lead: {name} ({phone})")
    # Тут можно отправить запрос через requests.post к твоему Telegram-боту

@app.get("/")
async def root():
    return {"status": "alive"}

# === Webhook ===
@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        print("👉 Incoming data:", data)

        name = data.get("name", "").strip()
        phone = data.get("phone", "").strip()

        if not name or not phone:
            return JSONResponse({"status": "missing data"}, status_code=400)

        now = datetime.now()
        if sheet:
            sheet.append_row([name, phone, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")])
            notify_telegram(name, phone)
            return JSONResponse({"status": "success"})
        else:
            return JSONResponse({"status": "Google Sheet not ready"}, status_code=500)

    except Exception as e:
        print("❌ Webhook error:", e)
        return JSONResponse({"status": "internal error"}, status_code=500)
