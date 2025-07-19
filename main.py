from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from dotenv import load_dotenv
import gspread
import httpx
import os

load_dotenv()
app = FastAPI()

# === Config ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
VOICE_WEBHOOK_URL = os.getenv("VOICE_WEBHOOK_URL")

# === Google Sheets Auth ===
try:
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file("service_account.json", scopes=scope)
    client = gspread.authorize(creds)
    q_sheet = client.open("RingBot").worksheet("Questions")
    calls_sheet = client.open("RingBot").worksheet("Calls")
except Exception as e:
    print("❌ Google Sheets init error:", e)
    q_sheet = None
    calls_sheet = None

# === Health check ===
@app.get("/")
@app.head("/")
async def root():
    return {"status": "alive"}

@app.get("/health")
@app.head("/health")
async def health():
    return {"status": "healthy"}

# === Log questions ===
@app.post("/log")
async def log_to_sheets(request: Request):
    try:
        data = await request.json()
        question = data.get("question", "").strip()
        if not question:
            return JSONResponse({"status": "missing question"}, status_code=400)

        now = datetime.now()
        if q_sheet:
            q_sheet.append_row([now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), question])
            return JSONResponse({"status": "logged"})
        else:
            return JSONResponse({"status": "Google Sheet not ready"}, status_code=500)
    except Exception as e:
        print("❌ /log error:", e)
        return JSONResponse({"status": "internal error"}, status_code=500)

# === Telegram lead ===
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
            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
            )

            if response.status_code != 200:
                print("❌ Telegram error:", response.status_code, response.text)
                return JSONResponse({"status": "telegram error"}, status_code=500)

        return JSONResponse({"status": "sent"})
    except Exception as e:
        print("❌ /lead error:", e)
        return JSONResponse({"status": "internal error"}, status_code=500)

# === Incoming call anti-spam filter ===
@app.post("/incoming-call")
async def incoming_call(request: Request):
    form = await request.form()
    caller = str(form.get("From", "unknown"))
    now = datetime.utcnow()

    try:
        if calls_sheet:
            calls_sheet.append_row([now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), caller])
        else:
            print("⚠️ Calls sheet not ready")

        rows = calls_sheet.get_all_values()[1:] if calls_sheet else []
        recent_calls = [
            r for r in rows
            if len(r) >= 3 and r[2] == caller and
            (now - datetime.strptime(r[0] + " " + r[1], "%Y-%m-%d %H:%M:%S")) < timedelta(hours=1)
        ]

        print(f"📞 {caller} — звонков за час: {len(recent_calls)}")
        if len(recent_calls) >= 3:
            print("🚫 BLOCKED")
            return PlainTextResponse(
                content="""<?xml version="1.0" encoding="UTF-8"?><Response><Reject/></Response>""",
                media_type="application/xml"
            )

    except Exception as e:
        print("⚠️ Error:", e)

    # Пускаем звонок дальше
    return PlainTextResponse(
        content=f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Redirect>{VOICE_WEBHOOK_URL}</Redirect>
</Response>""",
        media_type="application/xml"
    )
