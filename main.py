from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from dotenv import load_dotenv
import gspread
import httpx
import hashlib
import hmac
import json
import os
import re

load_dotenv()
app = FastAPI()

# === Config ===
TELEGRAM_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
VOICE_WEBHOOK_URL  = os.getenv("VOICE_WEBHOOK_URL")
HMAC_SECRET        = os.getenv("ELEVENLABS_WEBHOOK_SECRET") 

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Google Sheets Auth ===
def open_sheet(name, worksheet):
    try:
        scope  = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds  = Credentials.from_service_account_file(
            "service_account.json", scopes=scope
        )
        client = gspread.authorize(creds)
        sheet  = client.open(name)
        try:
            return sheet.worksheet(worksheet)
        except gspread.WorksheetNotFound:
           
            rows = 1
            cols = 10
            return sheet.add_worksheet(title=worksheet, rows=str(rows), cols=str(cols))
    except Exception as e:
        print(f"❌ Google Sheets init error ({worksheet}):", e)
        return None

leads_sheet = open_sheet("RingBot", "Leads")
calls_sheet = open_sheet("RingBot", "Calls")
log_sheet   = open_sheet("RingBot", "CallsLog")  

# === Health check ===
@app.get("/")
@app.head("/")
async def root():
    return {"status": "alive"}

@app.get("/health")
@app.head("/health")
async def health():
    return {"status": "healthy"}

from fastapi import Form, Request
from fastapi.responses import JSONResponse

@app.post("/lead")
async def lead_to_telegram(
    name: str = Form(...),
    company: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    note: str = Form("")
):
    try:
        if not name or not company:
            return JSONResponse(
                {"status": "missing fields"},
                status_code=400
            )

        msg = (
            f"🚀 *New RingBot Lead!*\n"
            f"👤 Name: {name}\n"
            f"🏢 Company: {company}\n"
            f"📞 Phone: {phone}"
        )
        if email:
            msg += f"\n📧 Email: {email}"
        if note:
            msg += f"\n📝 Note: {note}"

        # === Send to Telegram ===
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": msg,
                    "parse_mode": "Markdown"
                },
            )

            if response.status_code != 200:
                print("❌ Telegram error:", response.status_code, response.text)
                return JSONResponse({"status": "telegram error"}, status_code=500)

        # === Log to Google Sheet ===
        now = datetime.utcnow()
        if leads_sheet:
            try:
                leads_sheet.append_row([
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    name,
                    company,
                    phone,
                    email,
                    note
                ])
            except Exception as e:
                print("❌ Leads sheet append error:", e)

        return PlainTextResponse("sent")

    except Exception as e:
        print("❌ /lead error:", e)
        return JSONResponse({"status": "internal error"}, status_code=500)

@app.post("/incoming-call")
async def incoming_call(request: Request):
    form = await request.form()
    caller = form.get("From", "unknown")
    now = datetime.utcnow()

    try:
        # логгируем звонок
        if calls_sheet:
            calls_sheet.append_row([now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"), caller])

        rows = calls_sheet.get_all_values()[1:]
        recent_calls = [
            r for r in rows
            if len(r) >= 5 and r[4] == caller and
            (now - datetime.strptime(r[0] + " " + r[1], "%Y-%m-%d %H:%M:%S")) < timedelta(hours=1)
        ]

        print(f"📞 {caller} — calls per hour: {len(recent_calls)}")
        if len(recent_calls) >= 5:
            print("🚫 BLOCKED")
            return PlainTextResponse(
                content="""<?xml version="1.0" encoding="UTF-8"?><Response><Reject/></Response>""",
                media_type="application/xml"
            )

    except Exception as e:
        print("⚠️ Error logging:", e)

    return PlainTextResponse(
        content=f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Redirect>https://api.us.elevenlabs.io/twilio/inbound_call</Redirect>
</Response>""",
        media_type="application/xml"
    )

@app.post("/post-call")
async def post_call(request: Request):
    raw_body = await request.body()
    signature_header = request.headers.get("ElevenLabs-Signature", "")

    try:
        signature_parts = {
            part.split("=")[0]: part.split("=")[1]
            for part in signature_header.split(",") if "=" in part
        }
        timestamp = signature_parts.get("t", "")
        received_sig = signature_parts.get("v0", "")
    except Exception:
        return JSONResponse({"status": "bad signature format"}, status_code=400)

    signed_payload = f"{timestamp}.{raw_body.decode()}".encode()
    calc_sig = hmac.new(
        HMAC_SECRET.encode(),
        msg=signed_payload,
        digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calc_sig, received_sig):
        return JSONResponse({"status": "invalid signature"}, status_code=401)

    try:
        payload = json.loads(raw_body.decode())
    except json.JSONDecodeError:
        return JSONResponse({"status": "bad json"}, status_code=400)

    data        = payload.get("data", {})
    call_id     = data.get("conversation_id", "unknown")
    metadata    = data.get("metadata", {})
    duration    = metadata.get("call_duration_secs", 0) 
    transcript  = data.get("transcript", [])
    caller      = metadata.get("phone_call", {}).get("external_number", "unknown")
    num_replies = sum(
        1 for rep in transcript
        if isinstance(rep, dict) and rep.get("message")
    )

    text_lines = [
        f"{rep['role']}: {rep['message']}"
        for rep in transcript
        if isinstance(rep, dict) and rep.get("message")
    ]
    flat_text = "\n".join(text_lines)

    now = datetime.utcnow()
    try:
        if log_sheet:
            log_sheet.append_row(
                [
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S"),
                    caller,
                    call_id,
                    duration,
                    num_replies,
                    flat_text,
                ],
                value_input_option="RAW",
            )
        else:
            print("⚠️ CallsLog sheet not ready")
    except Exception as e:
        print("❌ Sheet append error:", e)
        return JSONResponse({"status": "sheet error"}, status_code=500)

    return JSONResponse({"status": "logged"})