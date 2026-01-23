import os
import logging
from datetime import datetime, timedelta
from threading import Lock
from uuid import uuid4
import re
from math import radians, sin, cos, sqrt, atan2
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from flask import Flask, jsonify, request
import asyncio
import sys
import json
from concurrent.futures import ThreadPoolExecutor

# ======================
# GLOBAL STATE WITH LOCK
# ======================
STATE_LOCK = Lock()
USER_STATE = {}
EXECUTOR = ThreadPoolExecutor(max_workers=10)

# ======================
# CONFIGURATION
# ======================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_MAIN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
SHEET_ID = os.getenv("SHEET_ID", "").strip()

# Google Sheets credentials from environment
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "{}")
if GOOGLE_CREDS_JSON and GOOGLE_CREDS_JSON != "{}":
    GOOGLE_CREDS = json.loads(GOOGLE_CREDS_JSON)
else:
    # Fallback to individual env vars
    GOOGLE_CREDS = {
        "type": os.getenv("GOOGLE_CREDENTIALS_TYPE", "service_account"),
        "project_id": os.getenv("GOOGLE_PROJECT_ID", ""),
        "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID", ""),
        "private_key": os.getenv("GOOGLE_PRIVATE_KEY", "").replace("\\n", "\n"),
        "client_email": os.getenv("GOOGLE_CLIENT_EMAIL", ""),
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "auth_uri": os.getenv("GOOGLE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
        "token_uri": os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
        "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_X509_CERT_URL", 
                                                 "https://www.googleapis.com/oauth2/v1/certs"),
        "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL", ""),
        "universe_domain": "googleapis.com"
    }

ACTIVE_CITIES = ["Addis Ababa"]
ALL_CITIES = [
    "Addis Ababa", "Hawassa", "Dire Dawa", "Mekelle",
    "Bahir Dar", "Adama", "Jimma", "Dessie"
]
BANKS = ["CBE", "Bank of Abyssinia"]
HOURLY_RATE = 100
COMMISSION_PERCENT = 0.25
COMMISSION_TIMEOUT_HOURS = 3
MAX_WARNING_DISTANCE = 100
MAX_ALLOWED_DISTANCE = 500
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))
USE_WEBHOOK = bool(WEBHOOK_URL)
ADMIN_TELEGRAM_USERNAME = "@YazilignAdmin"  # Replace with actual admin username

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("yazilign_bot.log")
    ]
)
logger = logging.getLogger(__name__)

# Disable verbose logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("gspread").setLevel(logging.WARNING)
logging.getLogger("oauth2client").setLevel(logging.WARNING)

# ======================
# USER STATES
# ======================
STATE_NONE = 0
STATE_CLIENT_CITY = 1
STATE_CLIENT_BUREAU = 2
STATE_CLIENT_LOCATION = 3
STATE_CLIENT_BOOKING_RECEIPT = 4
STATE_CLIENT_FINAL_HOURS = 5
STATE_CLIENT_FINAL_RECEIPT = 6
STATE_WORKER_NAME = 7
STATE_WORKER_PHONE = 8
STATE_WORKER_TELEBIRR = 9
STATE_WORKER_BANK = 10
STATE_WORKER_ACCOUNT_NUMBER = 11
STATE_WORKER_ACCOUNT_HOLDER = 12
STATE_WORKER_FYDA_FRONT = 13
STATE_WORKER_FYDA_BACK = 14
STATE_WORKER_CHECKIN_PHOTO = 15
STATE_WORKER_CHECKIN_LOCATION = 16
STATE_DISPUTE_REASON = 17
STATE_RATING = 18
STATE_CLIENT_MONITORING = 19
STATE_WORKER_UPDATE_MENU = 20
STATE_WORKER_UPDATE_PHONE = 21
STATE_WORKER_UPDATE_TELEBIRR = 22
STATE_WORKER_UPDATE_BANK = 23
STATE_WORKER_UPDATE_ACCOUNT = 24
STATE_WORKER_UPDATE_FYDA = 25
STATE_WORKER_DASHBOARD = 26
STATE_WORKER_LOGIN_OR_REGISTER = 27
STATE_WORKER_AT_FRONT = 28
STATE_CLIENT_CONFIRM_ARRIVAL = 29
STATE_WORKER_ACTIVE_JOB = 30

# ======================
# BILINGUAL MESSAGES
# ======================
def get_msg(key, **kwargs):
    messages = {
        "start": "Welcome! Are you a Client, Worker, or Admin?\nእንኳን በደህና መጡ! ደንበኛ፣ ሰራተኛ ወይስ አስተዳዳሪ ነዎት?",
        "cancel": "↩️ Back to Main Menu\n↩️ ወደ ዋና ገጽ",
        "choose_city": "📍 Choose city:\n📍 ከተማ ይምረጡ፡",
        "city_not_active": "🚧 Not in {city} yet. Choose Addis Ababa.\n🚧 በ{city} አይሰራም። አዲስ አበባ ይምረጡ።",
        "invalid_city": "⚠️ City name must be text only (no numbers). Please re-enter.\n⚠️ ከተማ ስሙ ፊደል ብቻ መሆን አለበት (ቁጥር ያልተካተተ)። እንደገና ይፃፉ።",
        "enter_bureau": "📍 Type bureau name:\n📍 የቢሮ ስሙን ይፃፉ:",
        "send_location": "📍 Share live location:\n📍 ቦታዎን ያጋሩ:",
        "booking_fee": "Pay 100 ETB and upload receipt.\n100 ብር ይላክሱ እና ሲምበር ያስገቡ።",
        "worker_welcome": "👷 Send your full name:\n👷 ሙሉ ስምዎን ይላኩ:",
        "worker_phone": "📱 Send phone number:\n📱 ስልክ ቁጥርዎን ይላኩ:",
        "worker_fyda_front": "📸 Send FRONT of your Fyda (ID):\n📸 የፍይዳዎን (ID) ገጽ ፎቶ ይላኩ:",
        "worker_fyda_back": "📸 Send BACK of your Fyda (ID):\n📸 የፍይዳዎን (ID) ወለድ ፎቶ ይላኩ:",
        "admin_approve_worker": "🆕 New worker registration!\nName: {name}\nPhone: {phone}\nApprove?\n🆕 አዲስ የሰራተኛ ምዝገባ!\nስም፡ {name}\nስልክ፡ {phone}\nፀድቀው ይወስኑ?",
        "worker_approved": "✅ Approved! You'll receive job alerts soon.\n✅ ፀድቋል! በቅርቡ የስራ ማስታወቂያ ይደርስዎታል።",
        "worker_declined": "❌ Declined. Contact admin for details.\n❌ ውድቅ ተደርጓል። ለተጨማሪ መረጃ አስተዳዳሪውን ያነጋግሩ።",
        "order_created": "✅ Order created! Searching for workers...\n✅ ትዕዛዝ ተፈጥሯል! ሰራተኛ እየፈለግን ነው...",
        "job_post": "📍 {bureau}\n🏙️ {city}\n💰 100 ETB/hour\n[Accept]\n📍 {bureau}\n🏙️ {city}\n💰 በሰዓት 100 ብር\n[ተቀበል]",
        "worker_accepted": "✅ Worker accepted! They'll check in soon.\n✅ ሰራተኛ ተገኝቷል! በቅርቡ ያገኙዎታል።",
        "checkin_photo": "📸 Send photo of yourself in line at {bureau}\n📸 በ{bureau} ውስጥ ያለውን ፎቶ ይላኩ",
        "checkin_location": "📍 Start live location sharing now\n📍 አሁን የቀጥታ መገኛ ያጋሩ",
        "checkin_complete": "✅ Check-in complete! Client notified.\n✅ የመግቢያ ሂደት ተጠናቅቋል!",
        "location_off_alert": "⚠️ Worker's location is off!\n⚠️ የሰራተኛው መገኛ ጠፍቷል!",
        "turn_on_location": "📍 Turn On Location\n📍 መገኛን አብራ",
        "location_alert_sent": "🔔 Request sent. Worker will be notified to turn on location.\n🔔 ጥያቄ ተልኳል። ሰራተኛው መገኛውን እንዲያበራ መልዕክት ይደርሰዋል።",
        "final_hours": "How many hours did the worker wait? (Min 1, Max 12)\nሰራተኛው ምን ያህል ሰዓት ቆየ? (ቢያንስ 1፣ ከፍተኛ 12)",
        "final_payment": "💼 Pay {amount} ETB to worker and upload receipt.\n💼 ለሰራተኛ {amount} ብር ይላክሱ እና ሲምበር ያስገቡ።",
        "payment_complete": "✅ Payment confirmed! Thank you.\n✅ ክፍያ ተረጋግጧል! እናመሰግናለን።",
        "commission_request": f"💰 You earned {{total}} ETB! Send 25% ({{commission}}) to {ADMIN_TELEGRAM_USERNAME} within 3 hours.\n💰 {{total}} ብር ሰርተዋል! የ25% ኮሚሽን ({{commission}}) በ3 ሰዓት ውስጥ ለ {ADMIN_TELEGRAM_USERNAME} ይላኩ።",
        "commission_timeout": f"⏰ 1 hour left to send your 25% commission to {ADMIN_TELEGRAM_USERNAME}!\n⏰ የ25% ኮሚሽን ለ{ADMIN_TELEGRAM_USERNAME} ለመላክ 1 ሰዓት ብቻ ይቀራል!",
        "commission_missed": f"🚨 You missed the commission deadline. Contact {ADMIN_TELEGRAM_USERNAME} immediately.\n🚨 የኮሚሽን መክፈያ ጊዜ አልፏል። በአስቸኳይ {ADMIN_TELEGRAM_USERNAME} ያነጋግሩ።",
        "request_new_worker": "🔄 Request New Worker\n🔄 ሌላ ሰራተኛ ይፈለግ",
        "reassign_reason": "Why do you want a new worker?\nሌላ ሰራተኛ ለምን ፈለጉ?",
        "worker_reassigned": "🔁 Job reopened. A new worker will be assigned soon.\n🔁 ስራው በድጋሚ ክፍት ሆኗል። በቅርቡ ሌላ ሰራተኛ ይመደባል።",
        "dispute_button": "⚠️ Dispute\n⚠️ ቅሬታ",
        "dispute_reason": "Select dispute reason:\nየቅሬታ ምክንያቱን ይምረጡ፡",
        "reason_no_show": "Worker didn't show\nሰራተኛው አልመጣም",
        "reason_payment": "Payment issue\nየክፍያ ችግር",
        "reason_fake_photo": "Fake photo\nሀሰተኛ ፎቶ",
        "dispute_submitted": "📄 Dispute submitted. Admin will review shortly.\n📄 ቅሬታዎ ቀርቧል። አስተዳዳሪው በቅርቡ ይመለከተዋል።",
        "rate_worker": "How would you rate this worker? (1-5 stars)\nለዚህ ሰራተኛ ምን ያህል ኮከብ ይሰጣሉ? (ከ1-5 ኮከቦች)",
        "rating_thanks": "Thank you! Your feedback helps us improve.\nእናመሰግናለን! የእርስዎ አስተያየት አገልግሎታችንን ለማሻሻል ይረዳናል።",
        "user_banned": f"🚫 You are banned from using Yazilign. Contact {ADMIN_TELEGRAM_USERNAME} for details.\n🚫 ከያዝልኝ አገልግሎት ታግደዋል። ለዝርዝር መረጃ {ADMIN_TELEGRAM_USERNAME} ያነጋግሩ።",
        "worker_far_warning": "⚠️ Worker moved >100m from job site!\n⚠️ ሠራተኛው ከሥራ ቦታ በላይ 100ሜ ተንቀሳቅሷል!",
        "worker_far_ban": "🚨 Worker moved >500m! Order cancelled & banned.\n🚨 ሠራተኛው ከሥራ ቦታ በላይ 500ሜ ተንቀሳቅሷል! ትዕዛዝ ተሰርዟል እና ታግዷል።",
        "menu_client_worker": "Client\nደንበኛ\n\nWorker\nሰራተኛ",
        "menu_login_register": "✅ Register as New Worker\n✅ አዲስ ሰራተኛ መመዝገቢያ\n\n🔑 Login as Existing Worker\n🔑 የሚገኝ ሰራተኛ መግቢያ\n\n↩️ Back to Main Menu\n↩️ ወደ ዋና ገጽ",
        "menu_worker_dashboard": "✅ Accept Jobs\n✅ ስራ ተቀበል\n\n✏️ Update Profile\n✏️ መግለጫ አዘምን\n\n📊 View Earnings\n📊 ገቢ ይመልከቱ\n\n↩️ Back to Main Menu\n↩️ ወደ ዋና ገጽ",
        "menu_update_options": "📱 Phone\n📱 ስልክ\n\n💳 Telebirr\n💳 ቴሌቢር\n\n🏦 Bank\n🏦 ባንክ\n\n🔢 Account\n🔢 አካውንት\n\n📸 Fyda Photos\n📸 የፍይዳ ፎቶዎች\n\n↩️ Back to Main Menu\n↩️ ወደ ዋና ገጽ",
        "menu_confirm_arrival": "✅ Confirm Arrival\n✅ መጣ ተብሎ ያረጋግጡ\n\n↩️ Back to Main Menu\n↩️ ወደ ዋና ገጽ",
        "menu_front_of_line": "✅ I'm at the front of the line\n✅ የመስረቃ መስመር ላይ ነኝ\n\n↩️ Back to Main Menu\n↩️ ወደ ዋና ገጽ",
        "admin_contact": ADMIN_TELEGRAM_USERNAME
    }
    
    msg = messages.get(key, key)
    if kwargs:
        msg = msg.format(**kwargs)
    return msg

# ======================
# LOCATION CALCULATION
# ======================
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

# ======================
# GOOGLE SHEETS
# ======================
def get_sheet_client():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            GOOGLE_CREDS,
            ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        )
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"Failed to authenticate with Google Sheets: {e}")
        raise

def get_worksheet(sheet_name):
    try:
        client = get_sheet_client()
        spreadsheet = client.open_by_key(SHEET_ID)
        worksheet = spreadsheet.worksheet(sheet_name)
        return worksheet
    except gspread.exceptions.WorksheetNotFound:
        logger.error(f"Worksheet '{sheet_name}' not found")
        raise
    except Exception as e:
        logger.error(f"Error getting worksheet '{sheet_name}': {e}")
        raise

def get_worksheet_data(sheet_name):
    try:
        worksheet = get_worksheet(sheet_name)
        all_values = worksheet.get_all_values()
        
        if not all_values:
            return []
        
        headers = all_values[0]
        data = []
        
        for row in all_values[1:]:
            row_dict = {}
            for i, header in enumerate(headers):
                if i < len(row):
                    row_dict[header] = row[i]
                else:
                    row_dict[header] = ""
            data.append(row_dict)
        
        return data
    except Exception as e:
        logger.error(f"Error getting worksheet data '{sheet_name}': {e}")
        return []

def update_worksheet_cell(sheet_name, row, col, value):
    try:
        worksheet = get_worksheet(sheet_name)
        worksheet.update_cell(row, col, value)
        return True
    except Exception as e:
        logger.error(f"Error updating cell in '{sheet_name}': {e}")
        return False

def log_to_history(user_id, role, action, details=""):
    try:
        sheet = get_worksheet("History")
        sheet.append_row([str(datetime.now()), str(user_id), role, action, details])
    except Exception as e:
        logger.error(f"Log error: {e}")

def is_user_banned(user_id):
    try:
        records = get_worksheet_data("Users")
        for r in records:
            if str(r.get("User_ID")) == str(user_id) and r.get("Status") == "Banned":
                return True
    except Exception as e:
        logger.error(f"Ban check error: {e}")
    return False

def ban_user(user_id, reason=""):
    try:
        worksheet = get_worksheet("Users")
        all_values = worksheet.get_all_values()
        
        if not all_values:
            return
        
        headers = all_values[0]
        
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 0 and str(row[0]) == str(user_id):
                for j, header in enumerate(headers):
                    if header == "Status":
                        if j < len(row):
                            worksheet.update_cell(i, j + 1, "Banned")
                        else:
                            if j >= len(row):
                                for _ in range(j - len(row) + 1):
                                    row.append("")
                            worksheet.update_cell(i, j + 1, "Banned")
                        break
                break
    except Exception as e:
        logger.error(f"Ban error: {e}")

def get_or_create_user(user_id, first_name, username, role=None):
    try:
        records = get_worksheet_data("Users")
        for r in records:
            if str(r.get("User_ID")) == str(user_id):
                return r
        
        worksheet = get_worksheet("Users")
        now = str(datetime.now())
        worksheet.append_row([
            str(user_id),
            first_name,
            username or "",
            "",
            role or "Client",
            "Active",
            now,
            now
        ])
        return {"User_ID": user_id, "Role": role or "Client", "Status": "Active"}
    except Exception as e:
        logger.error(f"User creation error: {e}")
        return None

def update_worker_rating(worker_id, rating):
    try:
        worksheet = get_worksheet("Workers")
        all_values = worksheet.get_all_values()
        
        if not all_values or len(all_values) < 2:
            return
        
        headers = all_values[0]
        
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 0 and str(row[0]) == str(worker_id):
                rating_col = None
                earnings_col = None
                
                for j, header in enumerate(headers):
                    if header == "Rating":
                        rating_col = j
                    elif header == "Total_Earnings":
                        earnings_col = j
                
                if rating_col is not None and earnings_col is not None:
                    current_rating = float(row[rating_col]) if rating_col < len(row) and row[rating_col] else 0
                    current_earnings = int(row[earnings_col]) if earnings_col < len(row) and row[earnings_col] else 0
                    
                    total_jobs = current_earnings or 1
                    new_rating = (current_rating * total_jobs + rating) / (total_jobs + 1)
                    
                    worksheet.update_cell(i, rating_col + 1, str(new_rating))
                    worksheet.update_cell(i, earnings_col + 1, str(total_jobs + 1))
                break
    except Exception as e:
        logger.error(f"Rating update error: {e}")

# ======================
# COMMISSION TIMER
# ======================
def start_commission_timer(order_id, worker_id, total_amount):
    commission = int(total_amount * COMMISSION_PERCENT)
    logger.info(f"Started commission timer for worker {worker_id}, order {order_id}, commission: {commission} ETB")
    # Implement commission timer logic here
    return

# ======================
# LOCATION MONITOR
# ======================
async def check_worker_location(context: ContextTypes.DEFAULT_TYPE):
    try:
        job = context.job
        worker_id = job.data["worker_id"]
        order_id = job.data["order_id"]
        
        orders = get_worksheet_data("Orders")
        order = None
        for rec in orders:
            if rec.get("Order_ID") == order_id:
                order = rec
                break
        if not order or order.get("Status") != "Assigned":
            job.schedule_removal()
            return
        
        await context.bot.send_message(
            chat_id=int(worker_id),
            text="📍 Please share your current live location to confirm you're at the bureau.\n📍 እባክዎን በቢሮው ውስጥ እንደሆኑ የቀጥታ መገኛዎን ያጋሩ።",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Share Live Location\n📍 ቦታዎን ያጋሩ", request_location=True)]],
                one_time_keyboard=True
            )
        )
    except Exception as e:
        logger.error(f"Location ping error: {e}")

# ======================
# TELEGRAM HANDLERS
# ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "User"
    username = user.username
    
    logger.info(f"Start command from user {user_id} ({first_name})")
    
    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return
    
    user_record = get_or_create_user(user_id, first_name, username)
    if not user_record:
        await update.message.reply_text("⚠️ System error. Please try again.\n⚠️ ስርዓቱ ችግር አጋጥሟል። እንደገና ይሞክሩ።")
        return
    
    # Clear any existing state
    USER_STATE[user_id] = {"state": STATE_NONE, "data": {}}
    
    legal_notice = (
        "ℹ️ **Yazilign Service Terms**\n"
        "• Workers are independent contractors\n"
        "• Pay only after service completion\n"
        "• 25% commission is mandatory\n"
        "• Fake photos/fraud = permanent ban\n"
        "• We are not liable for user disputes\n"
        "ℹ️ **የያዝልኝ አገልግሎት ውሎች**\n"
        "• ሠራተኞች ነፃ ተቋራጮች ናቸው\n"
        "• አገልግሎቱ ተጠናቅቋል ብለው ብቻ ይክፈሉ\n"
        "• 25% ኮሚሽን ግዴታ ነው\n"
        "• ሀሰተኛ ፎቶ/ጠላት = የዘላለም ቅጣት\n"
        "• ተጠቃሚ ግጭቶች ላይ ኃላፊነት የለንም"
    )
    
    keyboard = [["Client\nደንበኛ", "Worker\nሰራተኛ"]]
    if user_id == ADMIN_CHAT_ID:
        keyboard.append(["Admin\nአስተዳዳሪ"])
    
    await update.message.reply_text(
        f"{legal_notice}\n\n{get_msg('start')}",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "User"
    username = user.username
    text = update.message.text
    
    logger.info(f"Message from {user_id}: {text}")
    
    get_or_create_user(user_id, first_name, username)
    
    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return
    
    state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}})
    state = state_info["state"]
    data = state_info["data"]
    
    # Handle "Back to Main Menu" from any state
    if "Back to Main Menu" in text or "ወደ ዋና ገጽ" in text:
        USER_STATE[user_id] = {"state": STATE_NONE, "data": {}}
        await start(update, context)
        return
    
    if text == "/health":
        await update.message.reply_text("✅ Bot is healthy and running")
        return
    
    if text == "/test":
        await update.message.reply_text(f"✅ Bot test successful!\nUser ID: {user_id}\nTime: {datetime.now()}")
        return
    
    if text == "/start":
        await start(update, context)
        return
    
    # Check if text contains our bilingual options (handle both languages)
    if "Client" in text or "ደንበኛ" in text:
        USER_STATE[user_id] = {"state": STATE_CLIENT_CITY, "data": {}}
        keyboard = [[f"{city}\n{city}" if city != "Addis Ababa" else f"{city}\nአዲስ አበባ"] for city in ALL_CITIES]
        keyboard.append([get_msg("cancel")])
        await update.message.reply_text(
            get_msg("choose_city"),
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif "Worker" in text or "ሰራተኛ" in text:
        keyboard = [
            ["✅ Register as New Worker\n✅ አዲስ ሰራተኛ መመዝገቢያ"],
            ["🔑 Login as Existing Worker\n🔑 የሚገኝ ሰራተኛ መግቢያ"],
            [get_msg("cancel")]
        ]
        await update.message.reply_text(
            "👷 Choose an option:\n👷 ምርጫ ይምረጡ፡",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        USER_STATE[user_id] = {"state": STATE_WORKER_LOGIN_OR_REGISTER, "data": {}}
    
    elif ("Admin" in text or "አስተዳዳሪ" in text) and user_id == ADMIN_CHAT_ID:
        await update.message.reply_text(
            "👑 Admin Panel\n👑 የአስተዳዳሪ ፓነል\n"
            "Commands:\nትዕዛዞች፡\n"
            "/stats - Show statistics\n/ስታትስ - ስታቲስቲክስ አሳይ\n"
            "/users - List all users\n/ተጠቃሚዎች - ሁሉንም ተጠቃሚዎች አሰር\n"
            "/orders - List all orders\n/ትዕዛዞች - ሁሉንም ትዕዛዞች አሰር\n"
            "/workers - List all workers\n/ሰራተኞች - ሁሉንም ሰራተኞች አሰር\n"
            "/broadcast - Send message to all users\n/ማስተላለፊያ - ለሁሉም ተጠቃሚዎች መልዕክት ላክ"
        )
    
    elif state == STATE_WORKER_LOGIN_OR_REGISTER:
        if "Register" in text or "መመዝገቢያ" in text:
            USER_STATE[user_id] = {"state": STATE_WORKER_NAME, "data": {}}
            await update.message.reply_text(
                get_msg("worker_welcome"),
                reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
            )
        
        elif "Login" in text or "መግቢያ" in text:
            try:
                worker_info = None
                records = get_worksheet_data("Workers")
                for record in records:
                    if str(record.get("Telegram_ID")) == str(user_id) and record.get("Status") == "Active":
                        worker_info = record
                        break
                
                if worker_info:
                    account_number = str(worker_info.get("Account_number", ""))
                    last_four = account_number[-4:] if len(account_number) >= 4 else account_number
                    dashboard_text = (
                        f"👷‍♂️ **Worker Dashboard**\n👷‍♂️ **የሰራተኛ ዳሽቦርድ**\n"
                        f"Name/ስም: {worker_info.get('Full_Name', 'N/A')}\n"
                        f"Total Earnings/ጠቅላላ ገቢ: {worker_info.get('Total_Earnings', '0')} ETB\n"
                        f"Completed Jobs/የተጠናቀቁ ስራዎች: {worker_info.get('Total_Earnings', '0')} jobs\n"
                        f"Rating/ደረጃ: {worker_info.get('Rating', 'N/A')} ⭐\n"
                        f"Telebirr/ቴሌቢር: {worker_info.get('Telebirr_number', 'N/A')}\n"
                        f"Bank/ባንክ: {worker_info.get('Bank_type', 'N/A')} ••••{last_four}\n"
                        f"Choose an option:\nምርጫ ይምረጡ፡"
                    )
                    keyboard = [
                        ["✅ Accept Jobs\n✅ ስራ ተቀበል"],
                        ["✏️ Update Profile\n✏️ መግለጫ አዘምን"],
                        ["📊 View Earnings\n📊 ገቢ ይመልከቱ"],
                        [get_msg("cancel")]
                    ]
                    await update.message.reply_text(
                        dashboard_text,
                        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
                        parse_mode="Markdown"
                    )
                    USER_STATE[user_id] = {"state": STATE_WORKER_DASHBOARD, "data": {"worker_info": worker_info}}
                else:
                    await update.message.reply_text(
                        "⚠️ No account found. Please register as a new worker.\n⚠️ ማህደር አልተገኘም። እባክዎን እንደ አዲስ ሠራተኛ ይመዝገቡ።",
                        reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
                    )
            except Exception as e:
                logger.error(f"Worker login error: {e}")
                await update.message.reply_text("⚠️ Login failed. Try again.\n⚠️ መግቢያ አልተሳካም።")
    
    elif state == STATE_WORKER_DASHBOARD:
        worker_info = data.get("worker_info", {})
        if "Accept Jobs" in text or "ስራ ተቀበል" in text:
            await update.message.reply_text(
                "✅ Ready for jobs! You'll receive alerts when clients post orders.\n✅ ለስራ ዝግጁ! ደንበኞች ስራ ሲለጡ ማሳወቂያ ይደርስዎታል።",
                reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
            )
            USER_STATE[user_id] = {"state": STATE_NONE, "data": {}}
        
        elif "Update Profile" in text or "መግለጫ አዘምን" in text:
            keyboard = [
                ["📱 Phone\n📱 ስልክ", "💳 Telebirr\n💳 ቴሌቢር"],
                ["🏦 Bank\n🏦 ባንክ", "🔢 Account\n🔢 አካውንት"],
                ["📸 Fyda Photos\n📸 የፍይዳ ፎቶዎች"],
                [get_msg("cancel")]
            ]
            await update.message.reply_text(
                "What would you like to update?\nየትኞቹን መረጃ ማሻሽል ይፈልጋሉ?",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_MENU, "data": worker_info}
        
        elif "View Earnings" in text or "ገቢ ይመልከቱ" in text:
            total_earnings = int(worker_info.get('Total_Earnings', 0))
            commission_paid = int(total_earnings * 0.25)
            net_income = total_earnings - commission_paid
            earnings_text = (
                f"💰 **Earnings Summary**\n💰 **የገቢ ማጠቃለያ**\n"
                f"Total Earned/ጠቅላላ ገቢ: {total_earnings} ETB\n"
                f"Commission Paid/የተከፈለ ኮሚሽን: {commission_paid} ETB\n"
                f"Net Income/ንጹህ ገቢ: {net_income} ETB\n"
                f"Pending Payments/በጥበቃ ላይ ያሉ ክፍያዎች: 0 ETB"
            )
            await update.message.reply_text(
                earnings_text,
                reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True),
                parse_mode="Markdown"
            )
    
    elif state == STATE_WORKER_UPDATE_MENU:
        if "Phone" in text or "ስልክ" in text:
            USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_PHONE, "data": data}
            await update.message.reply_text(
                "📱 Enter new phone number:\n📱 የአዲስ ስልክ ቁጥር ይፃፉ፡",
                reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
            )
        elif "Telebirr" in text or "ቴሌቢር" in text:
            USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_TELEBIRR, "data": data}
            await update.message.reply_text(
                "📱 Enter new Telebirr number:\n📱 የአዲስ ቴሌቢር ቁጥር ይፃፉ፡",
                reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
            )
        elif "Bank" in text or "ባንክ" in text:
            USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_BANK, "data": data}
            keyboard = [[f"{bank}\n{bank}"] for bank in BANKS]
            keyboard.append([get_msg("cancel")])
            await update.message.reply_text(
                "🏦 Select new bank:\n🏦 የአዲስ ባንክ ይምረጡ፡",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
        elif "Account" in text or "አካውንት" in text:
            USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_ACCOUNT, "data": data}
            await update.message.reply_text(
                "🔢 Enter new account number:\n🔢 የአዲስ አካውንት ቁጥር ይፃፉ፡",
                reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
            )
        elif "Fyda Photos" in text or "የፍይዳ ፎቶዎች" in text:
            USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_FYDA, "data": data}
            await update.message.reply_text(
                get_msg("worker_fyda_front"),
                reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
            )
    
    elif state == STATE_CLIENT_CITY:
        # Extract city name (remove Amharic part if present)
        city_name = text.split('\n')[0].strip()
        
        if re.search(r'\d', city_name):
            keyboard = [[f"{city}\n{city}" if city != "Addis Ababa" else f"{city}\nአዲስ አበባ"] for city in ALL_CITIES]
            keyboard.append([get_msg("cancel")])
            await update.message.reply_text(get_msg("invalid_city"))
            await update.message.reply_text(
                get_msg("choose_city"),
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return
        
        if city_name not in ACTIVE_CITIES:
            keyboard = [[f"{city}\n{city}" if city != "Addis Ababa" else f"{city}\nአዲስ አበባ"] for city in ALL_CITIES]
            keyboard.append([get_msg("cancel")])
            await update.message.reply_text(get_msg("city_not_active", city=city_name))
            await update.message.reply_text(
                get_msg("choose_city"),
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return
        
        data["city"] = city_name
        USER_STATE[user_id] = {"state": STATE_CLIENT_BUREAU, "data": data}
        await update.message.reply_text(
            get_msg("enter_bureau"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_CLIENT_BUREAU:
        data["bureau"] = text.split('\n')[0].strip()
        USER_STATE[user_id] = {"state": STATE_CLIENT_LOCATION, "data": data}
        await update.message.reply_text(
            get_msg("send_location"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Share Live Location\n📍 ቦታዎን ያጋሩ", request_location=True)], [get_msg("cancel")]],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
    
    elif state == STATE_WORKER_NAME:
        data["name"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_PHONE, "data": data}
        await update.message.reply_text(
            get_msg("worker_phone"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_PHONE:
        data["phone"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_TELEBIRR, "data": data}
        await update.message.reply_text(
            "📱 Enter your Telebirr number:\n📱 የቴሌቢር ቁጥርዎን ይፃፉ፡",
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_TELEBIRR:
        data["telebirr"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_BANK, "data": data}
        keyboard = [[f"{bank}\n{bank}"] for bank in BANKS]
        keyboard.append([get_msg("cancel")])
        await update.message.reply_text(
            "🏦 Select your bank:\n🏦 የባንክዎን ይምረጡ፡",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_BANK:
        bank_name = text.split('\n')[0].strip()
        if bank_name not in BANKS:
            keyboard = [[f"{bank}\n{bank}"] for bank in BANKS]
            keyboard.append([get_msg("cancel")])
            await update.message.reply_text(
                "⚠️ Please select from the bank list.\n⚠️ ከባንክ ዝርዝሩ ይምረጡ።",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return
        
        data["bank_type"] = bank_name
        USER_STATE[user_id] = {"state": STATE_WORKER_ACCOUNT_NUMBER, "data": data}
        await update.message.reply_text(
            "🔢 Enter your account number:\n🔢 የአካውንት ቁጥርዎን ይፃፉ፡",
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_ACCOUNT_NUMBER:
        data["account_number"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_ACCOUNT_HOLDER, "data": data}
        await update.message.reply_text(
            "👤 Enter your account holder name (as on bank):\n👤 የአካውንት ባለቤት ስም (በባንክ የሚታየው)",
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_ACCOUNT_HOLDER:
        data["account_holder"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA_FRONT, "data": data}
        await update.message.reply_text(
            get_msg("worker_fyda_front"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_UPDATE_PHONE:
        try:
            worksheet = get_worksheet("Workers")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
                return
            
            headers = all_values[0]
            phone_col = None
            
            for j, header in enumerate(headers):
                if header == "Phone_Number":
                    phone_col = j
                    break
            
            if phone_col is None:
                await update.message.reply_text("⚠️ Phone column not found.\n⚠️ የስልክ አምድ አልተገኘም።")
                return
            
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(user_id):
                    worksheet.update_cell(i, phone_col + 1, text)
                    break
            
            await update.message.reply_text("✅ Phone updated!\n✅ ስልክ ቁጥር ተሻሽሏል!")
            await start(update, context)
        except Exception as e:
            logger.error(f"Phone update error: {e}")
            await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
    
    elif state == STATE_WORKER_UPDATE_TELEBIRR:
        try:
            worksheet = get_worksheet("Workers")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
                return
            
            headers = all_values[0]
            telebirr_col = None
            
            for j, header in enumerate(headers):
                if header == "Telebirr_number":
                    telebirr_col = j
                    break
            
            if telebirr_col is None:
                await update.message.reply_text("⚠️ Telebirr column not found.\n⚠️ ቴሌቢር አምድ አልተገኘም።")
                return
            
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(user_id):
                    worksheet.update_cell(i, telebirr_col + 1, text)
                    break
            
            await update.message.reply_text("✅ Telebirr updated!\n✅ ቴሌቢር ተሻሽሏል!")
            await start(update, context)
        except Exception as e:
            logger.error(f"Telebirr update error: {e}")
            await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
    
    elif state == STATE_WORKER_UPDATE_BANK:
        bank_name = text.split('\n')[0].strip()
        if bank_name not in BANKS:
            keyboard = [[f"{bank}\n{bank}"] for bank in BANKS]
            keyboard.append([get_msg("cancel")])
            await update.message.reply_text(
                "⚠️ Please select from the bank list.\n⚠️ ከባንክ ዝርዝሩ ይምረጡ።",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return
        
        try:
            worksheet = get_worksheet("Workers")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
                return
            
            headers = all_values[0]
            bank_col = None
            
            for j, header in enumerate(headers):
                if header == "Bank_type":
                    bank_col = j
                    break
            
            if bank_col is None:
                await update.message.reply_text("⚠️ Bank column not found.\n⚠️ ባንክ አምድ አልተገኘም።")
                return
            
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(user_id):
                    worksheet.update_cell(i, bank_col + 1, bank_name)
                    break
            
            await update.message.reply_text("✅ Bank updated!\n✅ ባንክ ተሻሽሏል!")
            await start(update, context)
        except Exception as e:
            logger.error(f"Bank update error: {e}")
            await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
    
    elif state == STATE_WORKER_UPDATE_ACCOUNT:
        try:
            worksheet = get_worksheet("Workers")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
                return
            
            headers = all_values[0]
            account_col = None
            
            for j, header in enumerate(headers):
                if header == "Account_number":
                    account_col = j
                    break
            
            if account_col is None:
                await update.message.reply_text("⚠️ Account column not found.\n⚠️ አካውንት አምድ አልተገኘም።")
                return
            
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(user_id):
                    worksheet.update_cell(i, account_col + 1, text)
                    break
            
            await update.message.reply_text("✅ Account updated!\n✅ አካውንት ተሻሽሏል!")
            await start(update, context)
        except Exception as e:
            logger.error(f"Account update error: {e}")
            await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
    
    elif state == STATE_CLIENT_FINAL_HOURS:
        try:
            hours = int(text.split('\n')[0].strip())
            if 1 <= hours <= 12:
                data["hours"] = hours
                total = HOURLY_RATE * hours
                data["total"] = total
                USER_STATE[user_id] = {"state": STATE_CLIENT_FINAL_RECEIPT, "data": data}
                await update.message.reply_text(
                    get_msg("final_payment", amount=total - 100),
                    reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
                )
            else:
                await update.message.reply_text(get_msg("final_hours"))
        except ValueError:
            await update.message.reply_text(get_msg("final_hours"))
    
    elif state == STATE_RATING:
        try:
            rating = int(text.split('\n')[0].strip())
            if 1 <= rating <= 5:
                update_worker_rating(data["worker_id"], rating)
                await update.message.reply_text(get_msg("rating_thanks"))
                await start(update, context)
            else:
                await update.message.reply_text(get_msg("rate_worker"))
        except ValueError:
            await update.message.reply_text(get_msg("rate_worker"))
    
    elif state == STATE_WORKER_AT_FRONT:
        if "I'm at the front" in text or "የመስረቃ መስመር ላይ" in text:
            order_id = data["order_id"]
            try:
                orders = get_worksheet_data("Orders")
                for rec in orders:
                    if rec.get("Order_ID") == order_id:
                        client_id = rec.get("Client_TG_ID")
                        await context.bot.send_message(
                            chat_id=int(client_id),
                            text="👷‍♂️ Your worker has reached the front of the line! Press 'Confirm Arrival' when you see them.\n👷‍♂️ ሠራተኛዎ የመስረቃ መስመር ላይ ደርሷል! ሲያዩት 'መጣ ተብሎ ያረጋግጡ' ይላኩ።",
                            reply_markup=ReplyKeyboardMarkup(
                                [["✅ Confirm Arrival\n✅ መጣ ተብሎ ያረጋግጡ"], [get_msg("cancel")]],
                                one_time_keyboard=True,
                                resize_keyboard=True
                            )
                        )
                        USER_STATE[int(client_id)] = {
                            "state": STATE_CLIENT_CONFIRM_ARRIVAL,
                            "data": {"order_id": order_id, "worker_id": user_id}
                        }
                        break
            except Exception as e:
                logger.error(f"Arrival notify error: {e}")
    
    elif state == STATE_CLIENT_CONFIRM_ARRIVAL:
        if "Confirm Arrival" in text or "መጣ ተብሎ" in text:
            order_id = data["order_id"]
            worker_id = data["worker_id"]
            try:
                worksheet = get_worksheet("Orders")
                all_values = worksheet.get_all_values()
                
                if not all_values:
                    await update.message.reply_text("⚠️ Error updating order.\n⚠️ ትዕዛዝ ማሻሻል ላይ ስህተት።")
                    return
                
                headers = all_values[0]
                status_col = None
                
                for j, header in enumerate(headers):
                    if header == "Status":
                        status_col = j
                        break
                
                if status_col is None:
                    await update.message.reply_text("⚠️ Status column not found.\n⚠️ ሁኔታ አምድ አልተገኘም።")
                    return
                
                for i, row in enumerate(all_values[1:], start=2):
                    if len(row) > 0 and row[0] == order_id:
                        worksheet.update_cell(i, status_col + 1, "Arrived")
                        break
            except Exception as e:
                logger.error(f"Arrival update error: {e}")
            
            await update.message.reply_text(get_msg("final_hours"))
            USER_STATE[user_id] = {
                "state": STATE_CLIENT_FINAL_HOURS,
                "data": {"order_id": order_id, "worker_id": worker_id}
            }
    
    else:
        await update.message.reply_text(
            "Please use the menu buttons.\nእባክዎን የምና ቁልፎችን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    get_or_create_user(user_id, user.first_name or "User", user.username)
    
    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return
    
    state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}})
    state = state_info["state"]
    data = state_info["data"]
    
    if not update.message.photo:
        return
    
    photo_file_id = update.message.photo[-1].file_id
    
    if state == STATE_WORKER_FYDA_FRONT:
        data["fyda_front"] = photo_file_id
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA_BACK, "data": data}
        await update.message.reply_text(
            get_msg("worker_fyda_back"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_FYDA_BACK:
        data["fyda_back"] = photo_file_id
        worker_telegram_id = str(user_id)
        worker_id = str(uuid4())[:8]
        
        try:
            worksheet = get_worksheet("Workers")
            worksheet.append_row([
                worker_id,
                data.get("name", ""),
                data.get("phone", ""),
                worker_telegram_id,
                "0",
                "0",
                "Pending",
                data.get("telebirr", ""),
                data.get("bank_type", ""),
                data.get("account_number", ""),
                data.get("account_holder", "")
            ])
            logger.info(f"✅ Worker registered: {worker_id}, Telegram ID: {worker_telegram_id}")
        except Exception as e:
            logger.error(f"Worker save error: {e}")
            await update.message.reply_text("⚠️ Failed to register. Try again.\n⚠️ ምዝገባ አልተሳካም።")
            return
        
        caption = get_msg("admin_approve_worker", name=data.get("name", ""), phone=data.get("phone", ""))
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=data["fyda_front"],
                caption=caption,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve\n✅ ፀድቅ", callback_data=f"approve_{worker_telegram_id}_{worker_id}")],
                    [InlineKeyboardButton("❌ Decline\n❌ ውድቅ", callback_data=f"decline_{worker_telegram_id}")]
                ])
            )
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=data["fyda_back"],
                caption="Back of Fyda\nየፍይዳ የኋላ ጎን"
            )
            await update.message.reply_text("📄 Sent to admin for approval.\n📄 ለአስተዳዳሪ ለፀድቂያ ተልኳል።")
            USER_STATE[user_id] = {"state": STATE_NONE, "data": {}}
        except Exception as e:
            logger.error(f"Admin notify error: {e}")
            await update.message.reply_text("⚠️ Failed to notify admin. Try again.\n⚠️ አስተዳዳሪ ማሳወቅ አልተሳካም።")
    
    elif state == STATE_CLIENT_BOOKING_RECEIPT:
        worker_id = data.get("assigned_worker")
        if not worker_id:
            await update.message.reply_text("⚠️ No worker assigned. Please wait for a worker first.\n⚠️ ሰራተኛ አልተመደበም።")
            return
        
        try:
            worker_records = get_worksheet_data("Workers")
            worker_info = None
            for wr in worker_records:
                if str(wr.get("Worker_ID")) == str(worker_id):
                    worker_info = wr
                    break
            if not worker_info:
                await update.message.reply_text("⚠️ Worker not found.\n⚠️ ሰራተኛ አልተገኘም።")
                return
        except Exception as e:
            logger.error(f"Worker fetch error: {e}")
            await update.message.reply_text("⚠️ Error fetching worker.\n⚠️ ሰራተኛ ማግኘት ላይ ችግር ተፈጥሯል።")
            return
        
        caption = (
            f"🆕 PAYMENT VERIFICATION NEEDED\n🆕 የክፍያ ማረጋገጫ ያስፈልጋል\n"
            f"Client ID/ደንበኛ መታወቂያ: {user_id}\n"
            f"Worker/ሰራተኛ: {worker_info.get('Full_Name', 'N/A')}\n"
            f"Account Holder/አካውንት ባለቤት: {worker_info.get('Name_holder', 'N/A')}\n"
            f"Amount/መጠን: 100 ETB"
        )
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=photo_file_id,
                caption=caption,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Verify Payment\n✅ ክፍያ አረጋግጥ", callback_data=f"verify_{user_id}_{worker_id}")],
                    [InlineKeyboardButton("❌ Reject Receipt\n❌ ሲምበር ውድቅ", callback_data=f"reject_{user_id}")]
                ])
            )
            await update.message.reply_text("📄 Receipt sent to admin for verification.\n📄 ሲምበር ለአስተዳዳሪ ምርመራ ተልኳል።")
        except Exception as e:
            logger.error(f"Payment forward error: {e}")
            await update.message.reply_text("⚠️ Failed to send receipt. Try again.\n⚠️ ሲምበር ማስተላለፍ አልተሳካም።")
    
    elif state == STATE_CLIENT_FINAL_RECEIPT:
        total = data.get("total", 0)
        worker_id = data.get("worker_id")
        order_id = data.get("order_id")
        
        if not worker_id or not order_id:
            await update.message.reply_text("⚠️ Error processing payment.\n⚠️ ክፍያ ማስኬድ ላይ ስህተት።")
            return
        
        commission = int(total * COMMISSION_PERCENT)
        
        try:
            worksheet = get_worksheet("Orders")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                await update.message.reply_text("⚠️ Error updating order.\n⚠️ ትዕዛዝ ማሻሻል ላይ ስህተት።")
                return
            
            headers = all_values[0]
            payment_status_col = None
            
            for j, header in enumerate(headers):
                if header == "Payment_Status":
                    payment_status_col = j
                    break
            
            if payment_status_col is not None:
                for i, row in enumerate(all_values[1:], start=2):
                    if len(row) > 0 and row[0] == order_id:
                        worksheet.update_cell(i, payment_status_col + 1, "Fully Paid")
                        break
        except Exception as e:
            logger.error(f"Order update error: {e}")
        
        try:
            await context.bot.send_message(
                chat_id=int(worker_id),
                text=get_msg("commission_request", total=total, commission=commission)
            )
        except Exception as e:
            logger.error(f"Commission notification error: {e}")
        
        start_commission_timer(order_id, worker_id, total)
        
        USER_STATE[user_id] = {"state": STATE_RATING, "data": {"worker_id": worker_id}}
        await update.message.reply_text(
            get_msg("rate_worker"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_CHECKIN_PHOTO:
        data["checkin_photo"] = photo_file_id
        USER_STATE[user_id] = {"state": STATE_WORKER_CHECKIN_LOCATION, "data": data}
        await update.message.reply_text(
            get_msg("checkin_location"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Share Live Location\n📍 ቦታዎን ያጋሩ", request_location=True)], [get_msg("cancel")]],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
    
    elif state == STATE_WORKER_UPDATE_FYDA:
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA_FRONT, "data": {}}
        await update.message.reply_text(
            get_msg("worker_fyda_front"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    else:
        await update.message.reply_text(
            "I don't understand what to do with this photo. Please use the menu.\nይህን ፎቶ ምን ማድረግ እንዳለብኝ አላውቅም። እባክዎን ምናውን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    get_or_create_user(user_id, user.first_name or "User", user.username)
    
    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return
    
    if not update.message or not update.message.location:
        return
    
    state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}})
    state = state_info["state"]
    data = state_info["data"]
    
    location = update.message.location
    lat = location.latitude
    lon = location.longitude
    
    logger.info(f"Location from {user_id}: {lat}, {lon}")
    
    if state == STATE_CLIENT_LOCATION:
        data["location"] = (lat, lon)
        USER_STATE[user_id]["data"] = data
        order_id = f"YZL-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:4].upper()}"
        
        logger.info(f"Creating new order {order_id} for client {user_id}")
        
        try:
            worksheet = get_worksheet("Orders")
            worksheet.append_row([
                order_id,
                str(datetime.now()),
                str(user_id),
                data.get("bureau", ""),
                data.get("city", ""),
                "Pending",
                "",
                "1",
                str(HOURLY_RATE),
                "No",
                "0",
                "Pending",
                str(lat),
                str(lon)
            ])
            logger.info(f"Order {order_id} created successfully")
        except Exception as e:
            logger.error(f"Order create error: {e}", exc_info=True)
            await update.message.reply_text("⚠️ Failed to create order. Try again.\n⚠️ ትዕዛዝ ማድረግ አልተሳካም።")
            return
        
        await update.message.reply_text(
            "✅ Order created! Notifying workers...\n✅ ትዕዛዝ ተፈጸመ! ሠራተኞች ተሳይተዋል..."
        )
        
        try:
            worker_records = get_worksheet_data("Workers")
            notified_count = 0
            active_workers = 0
            
            for worker in worker_records:
                if worker.get("Status") == "Active":
                    active_workers += 1
                    try:
                        await context.bot.send_message(
                            chat_id=int(worker.get("Telegram_ID", 0)),
                            text=get_msg("job_post", bureau=data.get("bureau", ""), city=data.get("city", "")),
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("Accept\nተቀበል", callback_data=f"accept_{order_id}_{user_id}")]
                            ])
                        )
                        notified_count += 1
                        logger.info(f"Notified worker {worker.get('Telegram_ID')} about order {order_id}")
                    except Exception as e:
                        logger.error(f"Failed to notify worker {worker.get('Telegram_ID')}: {e}")
            
            logger.info(f"Notified {notified_count}/{active_workers} active workers about order {order_id}")
            
            if notified_count == 0:
                await update.message.reply_text(
                    "⚠️ No active workers available at the moment. Please wait or try again later.\n⚠️ በአሁኑ ጊዜ ምንም ንቁ ሠራተኞች የሉም። እባክዎን ይጠብቁ ወይም ቆይተው እንደገና ይሞክሩ።"
                )
                
        except Exception as e:
            logger.error(f"Worker notification error: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🚨 Failed to notify workers for order {order_id}\nError: {str(e)}"
            )
            await update.message.reply_text("⚠️ Error notifying workers. Admin will handle it.\n⚠️ ሰራተኞች ማሳወቅ ላይ ስህተት። አስተዳዳሪው ያስተናግዳል።")
    
    elif state == STATE_WORKER_CHECKIN_LOCATION:
        data["checkin_location"] = (lat, lon)
        
        try:
            worksheet = get_worksheet("Orders")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                await update.message.reply_text("⚠️ Error checking in.\n⚠️ ምዝገባ ላይ ስህተት።")
                return
            
            headers = all_values[0]
            status_col = None
            client_id_col = None
            worker_id_col = None
            latitude_col = None
            longitude_col = None
            
            for j, header in enumerate(headers):
                if header == "Status":
                    status_col = j
                elif header == "Client_TG_ID":
                    client_id_col = j
                elif header == "Worker_ID":
                    worker_id_col = j
                elif header == "Latitude":
                    latitude_col = j
                elif header == "Longitude":
                    longitude_col = j
            
            order_id = None
            for i, row in enumerate(all_values[1:], start=2):
                if (worker_id_col is not None and worker_id_col < len(row) and 
                    str(row[worker_id_col]) == str(user_id) and 
                    status_col is not None and status_col < len(row) and 
                    row[status_col] == "Assigned"):
                    
                    order_id = row[0] if len(row) > 0 else None
                    
                    if status_col is not None:
                        worksheet.update_cell(i, status_col + 1, "Checked In")
                    
                    if client_id_col is not None and client_id_col < len(row):
                        client_id = row[client_id_col]
                        try:
                            await context.bot.send_message(
                                chat_id=int(client_id),
                                text="✅ Worker checked in! Live location active.\n✅ ሠራተኛ ተገኝቷል! የቀጥታ መገኛ አንስቶ ነው።"
                            )
                        except Exception as e:
                            logger.error(f"Client notification error: {e}")
                    
                    if (latitude_col is not None and latitude_col < len(row) and 
                        longitude_col is not None and longitude_col < len(row) and
                        row[latitude_col] and row[longitude_col]):
                        
                        try:
                            job_lat = float(row[latitude_col])
                            job_lon = float(row[longitude_col])
                            
                            distance = calculate_distance(lat, lon, job_lat, job_lon)
                            
                            if distance > MAX_ALLOWED_DISTANCE:
                                ban_user(user_id, f"Left job site (>500m)")
                                if status_col is not None:
                                    worksheet.update_cell(i, status_col + 1, "Cancelled")
                                
                                if client_id_col is not None and client_id_col < len(row):
                                    client_id = row[client_id_col]
                                    try:
                                        await context.bot.send_message(
                                            chat_id=int(client_id),
                                            text=get_msg("worker_far_ban")
                                        )
                                    except Exception as e:
                                        logger.error(f"Client ban notification error: {e}")
                                
                                try:
                                    await context.bot.send_message(
                                        chat_id=user_id,
                                        text=get_msg("worker_far_ban")
                                    )
                                except Exception as e:
                                    logger.error(f"Worker ban notification error: {e}")
                                
                                logger.info(f"Auto-banned worker {user_id} for moving {distance:.0f}m from job site")
                                return
                                
                            elif distance > MAX_WARNING_DISTANCE:
                                if client_id_col is not None and client_id_col < len(row):
                                    client_id = row[client_id_col]
                                    try:
                                        await context.bot.send_message(
                                            chat_id=int(client_id),
                                            text=get_msg("worker_far_warning")
                                        )
                                    except Exception as e:
                                        logger.error(f"Client warning notification error: {e}")
                                
                                try:
                                    await context.bot.send_message(
                                        chat_id=user_id,
                                        text=get_msg("worker_far_warning")
                                    )
                                except Exception as e:
                                    logger.error(f"Worker warning notification error: {e}")
                                
                                logger.info(f"Warning: worker {user_id} moved {distance:.0f}m from job site")
                                
                        except (ValueError, TypeError) as e:
                            logger.error(f"Distance calculation error: {e}")
                    
                    break
        
        except Exception as e:
            logger.error(f"Check-in update error: {e}")
        
        if order_id:
            keyboard = [
                ["✅ I'm at the front of the line\n✅ የመስረቃ መስመር ላይ ነኝ"],
                [get_msg("cancel")]
            ]
            await update.message.reply_text(
                "✅ Check-in complete! When you reach the front of the line, press the button below.\n✅ የመግቢያ ሂደት ተጠናቅቋል! የመስረቃ መስመር ላይ ሲደርሱ ከታች ያለውን ቁልፍ ይጫኑ።",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            USER_STATE[user_id] = {"state": STATE_WORKER_AT_FRONT, "data": {"order_id": order_id}}
        else:
            await update.message.reply_text(
                "⚠️ Could not find your assigned order. Please contact admin.\n⚠️ የተመደበልዎ ትዕዛዝ ሊገኝ አልቻለም። አስተዳዳሪውን ያነጋግሩ።"
            )
    
    else:
        await update.message.reply_text(
            "Location received, but I'm not sure what to do with it. Please use the menu.\nመገኛዎ ተቀበልኩ፣ ነገር ግን ምን ማድረግ እንዳለብኝ አላውቅም። እባክዎን ምናውን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup([[get_msg("cancel")]], one_time_keyboard=True, resize_keyboard=True)
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    first_name = user.first_name or "User"
    username = user.username
    get_or_create_user(user_id, first_name, username)
    
    if is_user_banned(user_id):
        await query.message.reply_text(get_msg("user_banned"))
        return
    
    data = query.data
    
    logger.info(f"Callback from {user_id}: {data}")
    
    if data.startswith("accept_"):
        parts = data.split("_")
        if len(parts) < 3:
            await query.edit_message_text("⚠️ Invalid job data.\n⚠️ የማያገለግል የስራ መረጃ።")
            return
        
        order_id = parts[1]
        client_id = parts[2]
        
        logger.info(f"Worker {user_id} attempting to accept order {order_id}")
        
        try:
            worksheet = get_worksheet("Orders")
            all_values = worksheet.get_all_values()
            
            if not all_values or len(all_values) < 2:
                await query.edit_message_text("⚠️ No orders found.\n⚠️ ምንም ትዕዛዞች አልተገኙም።")
                return
            
            headers = all_values[0]
            
            order = None
            row_idx = -1
            status_col_idx = None
            
            for j, header in enumerate(headers):
                if header == "Status":
                    status_col_idx = j
                    break
            
            if status_col_idx is None:
                for j, header in enumerate(headers):
                    if "status" in header.lower():
                        status_col_idx = j
                        break
            
            order_id_col_idx = None
            for j, header in enumerate(headers):
                if header == "Order_ID":
                    order_id_col_idx = j
                    break
            
            if order_id_col_idx is None:
                for j, header in enumerate(headers):
                    if "order" in header.lower() and "id" in header.lower():
                        order_id_col_idx = j
                        break
            
            for i, row in enumerate(all_values[1:], start=2):
                if order_id_col_idx is not None and order_id_col_idx < len(row) and row[order_id_col_idx] == order_id:
                    order = {}
                    for j, header in enumerate(headers):
                        if j < len(row):
                            order[header] = row[j]
                        else:
                            order[header] = ""
                    row_idx = i
                    logger.info(f"Found order at row {row_idx}: {order}")
                    break
            
            if not order:
                for i, row in enumerate(all_values[1:], start=2):
                    if len(row) > 0 and row[0] == order_id:
                        order = {}
                        for j, header in enumerate(headers):
                            if j < len(row):
                                order[header] = row[j]
                            else:
                                order[header] = ""
                        row_idx = i
                        logger.info(f"Found order in first column at row {row_idx}: {order}")
                        break
            
            if not order:
                await query.edit_message_text(
                    f"⚠️ Order {order_id} not found.\n⚠️ ትዕዛዝ {order_id} አልተገኘም።"
                )
                return
            
            current_status = order.get("Status", "")
            current_status_clean = str(current_status).strip().lower()
            available_statuses = ["pending", "available", "open", ""]
            
            if current_status_clean not in available_statuses:
                logger.info(f"Order {order_id} not available. Status: '{current_status}'")
                await query.edit_message_text(
                    "⚠️ Sorry, this job was already taken by another worker.\n⚠️ ስራው ቀድሞውና ተወስቷል።"
                )
                return
                
        except Exception as e:
            logger.error(f"Job lock check error: {e}", exc_info=True)
            await query.edit_message_text(
                "⚠️ Job assignment failed. Please try again.\n⚠️ ስራ መቀበል ላይ ስህተት ተፈጥሯል። እንደገና ይሞክሩ።"
            )
            return
        
        try:
            worker_id_col = None
            for j, header in enumerate(headers):
                if header == "Worker_ID":
                    worker_id_col = j
                    break
            
            if worker_id_col is not None:
                worksheet.update_cell(row_idx, worker_id_col + 1, str(user_id))
                logger.info(f"Updated Worker_ID at cell ({row_idx}, {worker_id_col + 1}) to {user_id}")
            else:
                worksheet.update_cell(row_idx, 7, str(user_id))
                logger.info(f"Updated Worker_ID at cell ({row_idx}, 7) to {user_id}")
            
            if status_col_idx is not None:
                worksheet.update_cell(row_idx, status_col_idx + 1, "Assigned")
                logger.info(f"Updated Status at cell ({row_idx}, {status_col_idx + 1}) to 'Assigned'")
            else:
                worksheet.update_cell(row_idx, 6, "Assigned")
                logger.info(f"Updated Status at cell ({row_idx}, 6) to 'Assigned'")
            
            worker_info = None
            try:
                worker_records = get_worksheet_data("Workers")
                for wr in worker_records:
                    if str(wr.get("Telegram_ID")) == str(user_id):
                        worker_info = wr
                        break
            except Exception as e:
                logger.error(f"Error getting worker info: {e}")
            
            if worker_info:
                account_number = str(worker_info.get("Account_number", ""))
                last_four = account_number[-4:] if len(account_number) >= 4 else account_number
                
                contact_msg = (
                    f"👷‍♂️ Worker found!\n👷‍♂️ ሰራተኛ ተገኝቷል!\n"
                    f"Name/ስም: {worker_info.get('Full_Name', 'N/A')}\n"
                    f"Phone/ስልክ: {worker_info.get('Phone_Number', 'N/A')}\n"
                    f"Telebirr/ቴሌቢር: {worker_info.get('Telebirr_number', 'N/A')}\n"
                    f"Bank/ባንክ: {worker_info.get('Bank_type', 'N/A')} ••••{last_four}"
                )
                await context.bot.send_message(chat_id=int(client_id), text=contact_msg)
                await context.bot.send_message(
                    chat_id=int(client_id),
                    text="💳 Pay 100 ETB to their Telebirr or bank, then upload payment receipt.\n💳 ለቴሌቢር ወይም ባንክ አካውንቱ 100 ብር ይላክሱ እና ሲምበር ያስገቡ።"
                )
                
                if int(client_id) not in USER_STATE:
                    USER_STATE[int(client_id)] = {"state": STATE_NONE, "data": {}}
                USER_STATE[int(client_id)]["state"] = STATE_CLIENT_BOOKING_RECEIPT
                USER_STATE[int(client_id)]["data"]["assigned_worker"] = worker_info.get("Worker_ID", "")
            else:
                await context.bot.send_message(
                    chat_id=int(client_id), 
                    text="⚠️ Worker details not found.\n⚠️ ዝርዝሮች አልተገኙም።"
                )
            
            bureau = order.get("Bureau_Name", "")
            USER_STATE[user_id] = {
                "state": STATE_WORKER_CHECKIN_PHOTO,
                "data": {"order_id": order_id, "bureau": bureau}
            }
            
            await context.bot.send_message(
                chat_id=user_id,
                text=get_msg("checkin_photo", bureau=bureau)
            )
            
            context.job_queue.run_repeating(
                check_worker_location,
                interval=300,
                first=10,
                data={"worker_id": user_id, "order_id": order_id},
                name=f"location_monitor_{order_id}"
            )
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ You've accepted the job at {bureau}! Please proceed to check-in.\n✅ በ{bureau} ያለውን ስራ ተቀበለዋል! እባክዎን ወደ ምዝገባ ይሂዱ።"
            )
            
            await context.bot.send_message(
                chat_id=int(client_id),
                text=f"✅ A worker has accepted your job at {bureau}! They will check in soon.\n✅ በ{bureau} ያለውን ስራዎ ሠራተኛ ተብሏል! በቅርቡ ያገኙዎታል።"
            )
            
            try:
                await query.edit_message_text(
                    text=f"✅ You've accepted this job!\n✅ ይህን ስራ ተቀብለዋል!\n📍 Bureau/ቢሮ: {bureau}\n⏰ Please proceed to check-in.\n⏰ እባክዎን ወደ ምዝገባ ይሂዱ።",
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"Error updating message: {e}")
            
            logger.info(f"Worker {user_id} successfully accepted order {order_id} at {bureau}")
            
        except Exception as e:
            logger.error(f"Accept error: {e}", exc_info=True)
            await query.edit_message_text(
                "⚠️ Error accepting job. Please contact admin.\n⚠️ ስራ መቀበል ላይ ስህተት ተፈጥሯል። አስተዳዳሪውን ያነጋግሩ።"
            )
    
    elif data.startswith("approve_"):
        parts = data.split("_")
        if len(parts) < 3:
            return
        
        worker_tg_id = parts[1]
        worker_db_id = parts[2]
        
        try:
            worksheet = get_worksheet("Workers")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                return
            
            headers = all_values[0]
            status_col = None
            
            for j, header in enumerate(headers):
                if header == "Status":
                    status_col = j
                    break
            
            if status_col is None:
                return
            
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and row[0] == worker_db_id:
                    worksheet.update_cell(i, status_col + 1, "Active")
                    break
            
            await context.bot.send_message(
                chat_id=int(worker_tg_id), 
                text=get_msg("worker_approved")
            )
            await query.edit_message_caption(caption="✅ Approved!\n✅ ተፈቅዶልናል!")
            
        except Exception as e:
            logger.error(f"Approve error: {e}")
    
    elif data.startswith("decline_"):
        if len(data.split("_")) < 2:
            return
        
        worker_tg_id = data.split("_")[1]
        
        try:
            worksheet = get_worksheet("Workers")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                return
            
            headers = all_values[0]
            status_col = None
            
            for j, header in enumerate(headers):
                if header == "Status":
                    status_col = j
                    break
            
            if status_col is None:
                return
            
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(worker_tg_id):
                    worksheet.update_cell(i, status_col + 1, "Declined")
                    break
            
            await context.bot.send_message(
                chat_id=int(worker_tg_id), 
                text=get_msg("worker_declined")
            )
            await query.edit_message_caption(caption="❌ Declined.\n❌ ተውግዷል።")
            
        except Exception as e:
            logger.error(f"Decline error: {e}")
    
    elif data.startswith("verify_"):
        parts = data.split("_")
        if len(parts) < 3:
            return
        
        client_id = int(parts[1])
        worker_id = parts[2]
        
        try:
            worksheet = get_worksheet("Orders")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                return
            
            headers = all_values[0]
            status_col = None
            payment_verified_col = None
            
            for j, header in enumerate(headers):
                if header == "Status":
                    status_col = j
                elif header == "Payment_Verified":
                    payment_verified_col = j
            
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[2]) == str(client_id) and row[5] == "Pending":
                    if status_col is not None:
                        worksheet.update_cell(i, status_col + 1, "Verified")
                    if payment_verified_col is not None:
                        worksheet.update_cell(i, payment_verified_col + 1, "Yes")
                    break
            
            await context.bot.send_message(
                chat_id=client_id, 
                text="✅ Payment verified! Job proceeding.\n✅ ክፍያ ተረጋግጧል! ስራ ተከዋል።"
            )
            await query.edit_message_caption(caption="✅ Verified!\n✅ ተረጋግጧል!")
            
        except Exception as e:
            logger.error(f"Verify error: {e}")
    
    elif data.startswith("reject_"):
        if len(data.split("_")) < 2:
            return
        
        client_id = int(data.split("_")[1])
        
        await context.bot.send_message(
            chat_id=client_id, 
            text="❌ Payment rejected. Please resend correct receipt.\n❌ ክፍያ ተውግዷል። እባክዎን ትክክለኛ ሲምበር ይላኩ።"
        )
        await query.edit_message_caption(caption="❌ Rejected.\n❌ ተውግዷል።")
    
    elif data == "turn_on_location":
        try:
            state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}})
            order_id = state_info["data"].get("order_id")
            if order_id:
                orders = get_worksheet_data("Orders")
                for record in orders:
                    if record.get("Order_ID") == order_id:
                        worker_id = record.get("Worker_ID")
                        await context.bot.send_message(
                            chat_id=int(worker_id),
                            text="🔔 Client requested live location. Please turn it on now.\n🔔 ደንበኛው የቀጥታ መገኛ ጠየቀ። አሁን ያብሩ።"
                        )
                        await query.message.reply_text(get_msg("location_alert_sent"))
                        break
        except Exception as e:
            logger.error(f"Location alert error: {e}")

# ======================
# ADMIN COMMANDS
# ======================
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        return
    
    try:
        users = get_worksheet_data("Users")
        workers = get_worksheet_data("Workers")
        orders = get_worksheet_data("Orders")
        
        active_users = len([u for u in users if u.get("Status") == "Active"])
        active_workers = len([w for w in workers if w.get("Status") == "Active"])
        pending_orders = len([o for o in orders if o.get("Status") in ["Pending", "Assigned"]])
        completed_orders = len([o for o in orders if o.get("Status") in ["Completed", "Arrived"]])
        
        stats_text = (
            f"📊 **Yazilign Statistics**\n"
            f"👥 Total Users: {len(users)}\n"
            f"✅ Active Users: {active_users}\n"
            f"👷 Total Workers: {len(workers)}\n"
            f"✅ Active Workers: {active_workers}\n"
            f"📦 Total Orders: {len(orders)}\n"
            f"⏳ Pending Orders: {pending_orders}\n"
            f"✅ Completed Orders: {completed_orders}\n"
            f"💰 Total Revenue: {completed_orders * HOURLY_RATE} ETB"
        )
        
        await update.message.reply_text(stats_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text("⚠️ Error fetching statistics")

# ======================
# ERROR HANDLER
# ======================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)

# ======================
# FLASK APP WITH WEBHOOK
# ======================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return jsonify({
        "status": "Yazilign Bot is running", 
        "timestamp": datetime.now().isoformat(),
        "version": "2.0",
        "mode": "webhook" if USE_WEBHOOK else "polling"
    })

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

@flask_app.route("/ping")
def ping():
    logger.info("Ping endpoint called")
    return jsonify({"status": "pong", "time": str(datetime.now())})

@flask_app.route("/status")
def status():
    return jsonify({
        "bot_token_exists": bool(BOT_TOKEN),
        "admin_id": ADMIN_CHAT_ID,
        "sheet_id": bool(SHEET_ID),
        "webhook_url": WEBHOOK_URL,
        "user_state_count": len(USER_STATE),
        "active_cities": ACTIVE_CITIES
    })

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    """Webhook endpoint for Telegram"""
    if request.method == "POST":
        try:
            update = Update.de_json(request.get_json(force=True), bot_app.bot)
            
            # Process update in thread pool to avoid blocking
            future = EXECUTOR.submit(
                asyncio.run_coroutine_threadsafe,
                bot_app.process_update(update),
                bot_app._loop
            )
            future.result(timeout=10)
            
            return jsonify({"status": "ok"})
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "ok"})

# ======================
# MAIN APPLICATION SETUP
# ======================
def setup_bot_application():
    """Set up the Telegram bot application"""
    # Validate required environment variables
    required_vars = ["TELEGRAM_BOT_TOKEN_MAIN", "ADMIN_CHAT_ID", "SHEET_ID"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing environment variables: {missing_vars}")
        sys.exit(1)
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is empty or invalid")
        sys.exit(1)
    
    # Create application
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .pool_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("test", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_error_handler(error_handler)
    
    logger.info("Bot application set up successfully")
    return application

async def setup_webhook(application: Application):
    """Set up webhook for the bot"""
    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL.rstrip('/')}/webhook"
        logger.info(f"Setting webhook to: {webhook_url}")
        
        try:
            # First, delete any existing webhook
            await application.bot.delete_webhook()
            logger.info("Deleted existing webhook")
            
            # Set new webhook
            await application.bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES
            )
            logger.info("Webhook set successfully")
            
            # Verify webhook
            webhook_info = await application.bot.get_webhook_info()
            logger.info(f"Webhook info: {webhook_info.url}")
            logger.info(f"Webhook pending updates: {webhook_info.pending_update_count}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
            raise
    else:
        logger.warning("WEBHOOK_URL not set, using polling instead")

async def cleanup_existing_webhook():
    """Clean up any existing webhook before starting"""
    try:
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        
        # Get current webhook info
        webhook_info = await bot.get_webhook_info()
        logger.info(f"Current webhook: {webhook_info.url}")
        
        if webhook_info.url:
            logger.info("Deleting existing webhook...")
            await bot.delete_webhook()
            logger.info("✅ Webhook deleted successfully")
        
        return True
    except Exception as e:
        logger.error(f"Error cleaning up webhook: {e}")
        return False

def run_bot_with_polling():
    """Run bot with polling (for development)"""
    application = setup_bot_application()
    
    logger.info("Starting bot with polling...")
    
    # Run bot with polling
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
        stop_signals=None,
        poll_interval=0.5,
        timeout=20
    )

def run_bot_with_webhook():
    """Run bot with webhook (for production)"""
    global bot_app
    
    bot_app = setup_bot_application()
    
    # Get event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Set up webhook
    loop.run_until_complete(setup_webhook(bot_app))
    
    # Initialize the bot (without polling)
    bot_app.initialize()
    
    logger.info(f"Starting Flask server on port {PORT}")
    
    # Run Flask
    flask_app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

def main():
    """Main entry point"""
    logger.info("=" * 50)
    logger.info("Starting Yazilign Bot...")
    logger.info(f"Bot Token: {'*' * 20}{BOT_TOKEN[-4:] if BOT_TOKEN else 'NONE'}")
    logger.info(f"Admin ID: {ADMIN_CHAT_ID}")
    logger.info(f"Sheet ID: {SHEET_ID[:10]}...")
    logger.info(f"Webhook URL: {WEBHOOK_URL}")
    logger.info(f"Port: {PORT}")
    logger.info("=" * 50)
    
    # Clean up any existing webhook first
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(cleanup_existing_webhook())
    
    # Force polling for now to debug
    logger.info("Using polling mode for now...")
    run_bot_with_polling()

if __name__ == "__main__":
    main()
