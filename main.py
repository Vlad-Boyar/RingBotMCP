from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.oauth2.service_account import Credentials
from datetime import datetime
from dotenv import load_dotenv
import gspread
import httpx
import os

load_dotenv()
app = FastAPI()

# === Telegram Config ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# === Google Sheets Auth ===
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

# === Health Endpoints ===
@app.head("/")
@app.get("/")
async def root():
    return {"status": "alive"}

@app.head("/health")
@app.get("/health")
async def health_check():
    return {"status": "healthy"}

# === /log → лог в Google Sheets ===
@app.post("/log")
async def log_to_sheets(request: Request):
    try:
        data = await request.json()
        name = data.get("name", "Unknown").strip()
        question = data.get("question", "").strip()
        answer = data.get("answer", "").strip()

        if not question or not answer:
            return JSONResponse({"status": "missing data"}, status_code=400)

        now = datetime.now()
        if sheet:
            sheet.append_row([
                name,
                question,
                answer,
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S")
            ])
            return JSONResponse({"status": "logged"})
        else:
            return JSONResponse({"status": "Google Sheet not ready"}, status_code=500)

    except Exception as e:
        print("❌ /log error:", e)
        return JSONResponse({"status": "internal error"}, status_code=500)

# === /lead → отправка лида в Telegram ===
@app.post("/lead")
async def lead_to_telegram(request: Request):
    try:
        data = await request.json()
        name = data.get("name", "Unknown").strip()
        phone = data.get("phone", "").strip()
        note = data.get("note", "").strip()

        if not phone:
            return JSONResponse({"status": "missing phone"}, status_code=400)

        msg = f"🚀 *Новый интерес к RingBot!*\nИмя: {name}\nТел: {phone}"
        if note:
            msg += f"\n📌 {note}"

        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": msg,
                    "parse_mode": "Markdown"
                }
            )

        return JSONResponse({"status": "sent"})

    except Exception as e:
        print("❌ /lead error:", e)
        return JSONResponse({"status": "internal error"}, status_code=500)
