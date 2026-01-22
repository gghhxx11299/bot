import os
import logging
from datetime import datetime, timedelta
from threading import Timer
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

# ======================
# CONFIGURATION
# ======================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_MAIN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
SHEET_ID = os.getenv("SHEET_ID")

GOOGLE_CREDS = {
    "type": os.getenv("GOOGLE_CREDENTIALS_TYPE"),
    "project_id": os.getenv("GOOGLE_PROJECT_ID"),
    "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
    "auth_uri": os.getenv("GOOGLE_AUTH_URI"),
    "token_uri": os.getenv("GOOGLE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL"),
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

USER_STATE = {}

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
# MESSAGES
# ======================

MESSAGES = {
    "start": {"en": "Welcome! Are you a Client, Worker, or Admin?", "am": "እንኳን በደህና መጡ!"},
    "cancel": {"en": "↩️ Back to Main Menu", "am": "↩️ ወደ ዋና ገጽ"},
    "choose_city": {"en": "📍 Choose city:", "am": "📍 ከተማ ይምረጡ፡"},
    "city_not_active": {"en": "🚧 Not in {city} yet. Choose Addis Ababa.", "am": "🚧 በ{city} አይሰራም። አዲስ አበባ ይምረጡ።"},
    "invalid_city": {"en": "⚠️ City name must be text only (no numbers). Please re-enter.", "am": "⚠️ ከተማ ስሙ ፊደል ብቻ መሆን አለበት (ቁጥር ያልተካተተ)። እንደገና ይፃፉ።"},
    "enter_bureau": {"en": "📍 Type bureau name:", "am": "📍 የቢሮ ስሙን ይፃፉ:"},
    "send_location": {"en": "📍 Share live location:", "am": "📍 ቦታዎን ያጋሩ:"},
    "booking_fee": {"en": "Pay 100 ETB and upload receipt.", "am": "100 ብር ይላክሱ እና ሲምበር ያስገቡ።"},
    "worker_welcome": {"en": "👷 Send your full name:", "am": "👷 ሙሉ ስምዎን ይላኩ:"},
    "worker_phone": {"en": "📱 Send phone number:", "am": "📱 ስልክ ቁጥርዎን ይላኩ:"},
    "worker_fyda_front": {"en": "📸 Send FRONT of your Fyda (ID):", "am": "📸 የፍይዳዎን (ID) ገጽ ፎቶ ይላኩ:"},
    "worker_fyda_back": {"en": "📸 Send BACK of your Fyda (ID):", "am": "📸 የፍይዳዎን (ID) ወለድ ፎቶ ይላኩ:"},
    "admin_approve_worker": {"en": "🆕 New worker registration!\nName: {name}\nPhone: {phone}\nApprove?", "am": "🆕 አዲስ የሰራተኛ ምዝገባ!\nስም፡ {name}\nስልክ፡ {phone}"},
    "worker_approved": {"en": "✅ Approved! You’ll receive job alerts soon.", "am": "✅ ፀድቋል! በቅርቡ የስራ ማስታወቂያ ይደርስዎታል።"},
    "worker_declined": {"en": "❌ Declined. Contact admin for details.", "am": "❌ ውድቅ ተደርጓል። ለተጨማሪ መረጃ አስተዳዳሪውን ያነጋግሩ።"},
    "order_created": {"en": "✅ Order created! Searching for workers...", "am": "✅ ትዕዛዝ ተፈጥሯል! ሰራተኛ እየፈለግን ነው..."},
    "job_post": {"en": "📍 {bureau}\n🏙️ {city}\n💰 100 ETB/hour\n[Accept]", "am": "📍 {bureau}\n🏙️ {city}\n💰 በሰዓት 100 ብር\n[ተቀበል]"},
    "worker_accepted": {"en": "✅ Worker accepted! They’ll check in soon.", "am": "✅ ሰራተኛ ተገኝቷል! በቅርቡ ያገኙዎታል።"},
    "checkin_photo": {"en": "📸 Send photo of yourself in line at {bureau}", "am": "📸 በ{bureau} ውስጥ ያለውን ፎቶ ይላኩ"},
    "checkin_location": {"en": "📍 Start live location sharing now", "am": "📍 አሁን የቀጥታ መገኛ ያጋሩ"},
    "checkin_complete": {"en": "✅ Check-in complete! Client notified.", "am": "✅ የመግቢያ ሂደት ተጠናቅቋል!"},
    "location_off_alert": {"en": "⚠️ Worker’s location is off!", "am": "⚠️ የሰራተኛው መገኛ ጠፍቷል!"},
    "turn_on_location": {"en": "Turn On Location", "am": "መገኛን አብራ"},
    "location_alert_sent": {"en": "🔔 Request sent. Worker will be notified to turn on location.", "am": "🔔 ጥያቄ ተልኳል። ሰራተኛው መገኛውን እንዲያበራ መልዕክት ይደርሰዋል።"},
    "final_hours": {"en": "How many hours did the worker wait? (Min 1, Max 12)", "am": "ለዚህ ሰራተኛ ምን ያህል ኮከብ ይሰጣሉ? (ከ1-5 ኮከቦች)"},
    "final_payment": {"en": "💼 Pay {amount} ETB to worker and upload receipt.", "am": "💼 ለሰራተኛ {amount} ብር ይላክሱ እና ሲምበር ያስገቡ።"},
    "payment_complete": {"en": "✅ Payment confirmed! Thank you.", "am": "✅ ክፍያ ተረጋግጧል! እናመሰግናለን።"},
    "commission_request": {"en": "💰 You earned {total} ETB! Send 25% ({commission}) to @YourTelegram within 3 hours.", "am": "💰 {total} ብር ሰርተዋል! የ25% ኮሚሽን ({commission}) በ3 ሰዓት ውስጥ ለ @YourTelegram ይላኩ።"},
    "commission_timeout": {"en": "⏰ 1 hour left to send your 25% commission!", "am": "⏰ የ25% ኮሚሽን ለመላክ 1 ሰዓት ብቻ ይቀራል!"},
    "commission_missed": {"en": "🚨 You missed the commission deadline. Contact admin immediately.", "am": "🚨 የኮሚሽን መክፈያ ጊዜ አልፏል። በአስቸኳይ አስተዳዳሪውን ያነጋግሩ።"},
    "request_new_worker": {"en": "🔄 Request New Worker", "am": "🔄 ሌላ ሰራተኛ ይፈለግ"},
    "reassign_reason": {"en": "Why do you want a new worker?", "am": "ሌላ ሰራተኛ ለምን ፈለጉ?"},
    "worker_reassigned": {"en": "🔁 Job reopened. A new worker will be assigned soon.", "am": "🔁 ስራው በድጋሚ ክፍት ሆኗል። በቅርቡ ሌላ ሰራተኛ ይመደባል።"},
    "dispute_button": {"en": "⚠️ Dispute", "am": "⚠️ ቅሬታ"},
    "dispute_reason": {"en": "Select dispute reason:", "am": "የቅሬታ ምክንያቱን ይምረጡ፡"},
    "reason_no_show": {"en": "Worker didn’t show", "am": "ሰራተኛው አልመጣም"},
    "reason_payment": {"en": "Payment issue", "am": "የክፍያ ችግር"},
    "reason_fake_photo": {"en": "Fake photo", "am": "ሀሰተኛ ፎቶ"},
    "dispute_submitted": {"en": "📄 Dispute submitted. Admin will review shortly.", "am": "📄 ቅሬታዎ ቀርቧል። አስተዳዳሪው በቅርቡ ይመለከተዋል።"},
    "rate_worker": {"en": "How would you rate this worker? (1–5 stars)", "am": "ለዚህ ሰራተኛ ምን ያህል ኮከብ ይሰጣሉ? (ከ1-5 ኮከቦች)"},
    "rating_thanks": {"en": "Thank you! Your feedback helps us improve.", "am": "እናመሰግናለን! የእርስዎ አስተያየት አገልግሎታችንን ለማሻሻል ይረዳናል።"},
    "user_banned": {"en": "🚫 You are banned from using Yazilign. Contact admin for details.", "am": "🚫 ከያዝልኝ አገልግሎት ታግደዋል። ለዝርዝር መረጃ አስተዳዳሪውን ያነጋግሩ።"},
    "worker_far_warning": {"en": "⚠️ Worker moved >100m from job site!", "am": "⚠️ ሠራተኛው ከሥራ ቦታ በላይ 100ሜ ተንቀሳቅሷል!"},
    "worker_far_ban": {"en": "🚨 Worker moved >500m! Order cancelled & banned.", "am": "🚨 ሠራተኛው ከሥራ ቦታ በላይ 500ሜ ተንቀሳቅሷል! ትዕዛዝ ተሰርዟል እና ታግዷል።"}
}

def get_msg(key, **kwargs):
    en_text = MESSAGES[key].get("en", "")
    am_text = MESSAGES[key].get("am", "")
    if kwargs:
        en_text = en_text.format(**kwargs)
        am_text = am_text.format(**kwargs)
    return f"{en_text}\n{am_text}"

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
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        GOOGLE_CREDS,
        ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
    return gspread.authorize(creds)

def get_worksheet(sheet_name):
    client = get_sheet_client()
    return client.open_by_key(SHEET_ID).worksheet(sheet_name)

def log_to_history(user_id, role, action, details=""):
    try:
        sheet = get_worksheet("History")
        sheet.append_row([str(datetime.now()), str(user_id), role, action, details])
    except Exception as e:
        logger.error(f"Log error: {e}")

def is_user_banned(user_id):
    try:
        sheet = get_worksheet("Users")
        records = sheet.get_all_records()
        for r in records:
            if str(r.get("User_ID")) == str(user_id) and r.get("Status") == "Banned":
                return True
    except Exception as e:
        logger.error(f"Ban check error: {e}")
    return False

def ban_user(user_id, reason=""):
    try:
        sheet = get_worksheet("Users")
        records = sheet.get_all_records()
        for i, record in enumerate(records, start=2):
            if str(record.get("User_ID")) == str(user_id):
                sheet.update_cell(i, 6, "Banned")
                break
    except Exception as e:
        logger.error(f"Ban error: {e}")

def get_or_create_user(user_id, first_name, username, role=None):
    try:
        sheet = get_worksheet("Users")
        records = sheet.get_all_records()
        for r in records:
            if str(r.get("User_ID")) == str(user_id):
                return r
        
        now = str(datetime.now())
        sheet.append_row([
            str(user_id),
            first_name,
            username or "",
            "",  # Phone_Number
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
        sheet = get_worksheet("Workers")
        records = sheet.get_all_records()
        for i, record in enumerate(records, start=2):
            if str(record.get("Worker_ID")) == str(worker_id):
                current_rating = float(record.get("Rating", 0))
                total_jobs = int(record.get("Total_Earnings", 0))
                new_rating = (current_rating * total_jobs + rating) / (total_jobs + 1)
                sheet.update_cell(i, 5, str(new_rating))
                sheet.update_cell(i, 6, str(total_jobs + 1))
                break
    except Exception as e:
        logger.error(f"Rating update error: {e}")

# ======================
# COMMISSION TIMER
# ======================

def start_commission_timer(application, order_id, worker_id, total_amount):
    commission = int(total_amount * COMMISSION_PERCENT)
    
    def final_action():
        ban_user(worker_id, reason="Missed commission")
        asyncio.run_coroutine_threadsafe(
            application.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🚨 Auto-banned Worker {worker_id} for missing commission on {order_id}"
            ),
            application.updater.dispatcher.loop
        )
    
    Timer(COMMISSION_TIMEOUT_HOURS * 3600, final_action).start()

# ======================
# LOCATION MONITOR (FIXES GHOSTING)
# ======================

async def check_worker_location(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    worker_id = job.data["worker_id"]
    order_id = job.data["order_id"]
    
    try:
        order_sheet = get_worksheet("Orders")
        order_records = order_sheet.get_all_records()
        order = None
        for rec in order_records:
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
                [[KeyboardButton("📍 Share Live Location", request_location=True)]],
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

    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return

    user_record = get_or_create_user(user_id, first_name, username)
    if not user_record:
        await update.message.reply_text("⚠️ System error. Please try again.\n⚠️ ስርዓቱ ችግር አጋጥሟል። እንደገና ይሞክሩ።")
        return

    USER_STATE[user_id] = {"state": STATE_NONE, "data": {}}

    legal_notice = (
        "ℹ️ **Yazilign Service Terms**\n\n"
        "• Workers are independent contractors\n"
        "• Pay only after service completion\n"
        "• 25% commission is mandatory\n"
        "• Fake photos/fraud = permanent ban\n"
        "• We are not liable for user disputes\n\n"
        "ℹ️ **የያዝልኝ አገልግሎት ውሎች**\n\n"
        "• ሠራተኞች ነፃ ተቋራጮች ናቸው\n"
        "• አገልግሎቱ ተጠናቅቋል ብለው ብቻ ይክፍሉ\n"
        "• 25% ኮሚሽን ግዴታ ነው\n"
        "• ሀሰተኛ ፎቶ/ጠላት = የዘላለም ቅጣት\n"
        "• ተጠቃሚ ግጭቶች ላይ ኃላፊነት የለንም"
    )

    keyboard = [["Client", "Worker"]]
    if user_id == ADMIN_CHAT_ID:
        keyboard.append(["Admin"])
    
    await update.message.reply_text(
        f"{legal_notice}\n\n{get_msg('start')}",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "User"
    username = user.username

    get_or_create_user(user_id, first_name, username)

    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return

    text = update.message.text
    state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}})
    state = state_info["state"]
    data = state_info["data"]

    # ✅ UNIVERSAL CANCEL BUTTON
    if text == "↩️ Back to Main Menu" or text == "↩️ ወደ ዋና ገጽ":
        await start(update, context)
        return

    # 👇 HEALTH CHECK FOR RENDER
    if text == "/health":
        await update.message.reply_text("OK")
        return

    if text == "Client":
        USER_STATE[user_id] = {"state": STATE_CLIENT_CITY, "data": {}}
        keyboard = [[city] for city in ALL_CITIES]
        keyboard.append(["↩️ Back to Main Menu"])
        await update.message.reply_text(
            get_msg("choose_city"),
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        )

    elif text == "Worker":
        # ✅ SHOW LOGIN OR REGISTER MENU
        keyboard = [
            ["✅ Register as New Worker"],
            ["🔑 Login as Existing Worker"],
            ["↩️ Back to Main Menu"]
        ]
        await update.message.reply_text(
            "👷 Choose an option:\n👷 ምርጫ ይምረጡ፡",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        )
        USER_STATE[user_id] = {"state": STATE_WORKER_LOGIN_OR_REGISTER, "data": {}}

    elif state == STATE_WORKER_LOGIN_OR_REGISTER:
        if text == "✅ Register as New Worker":
            USER_STATE[user_id] = {"state": STATE_WORKER_NAME, "data": {}}
            await update.message.reply_text(
                get_msg("worker_welcome"),
                reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
            )
        elif text == "🔑 Login as Existing Worker":
            # ✅ CHECK TELEGRAM ID IN WORKERS SHEET
            try:
                worker_sheet = get_worksheet("Workers")
                records = worker_sheet.get_all_records()
                worker_info = None
                for record in records:
                    if str(record.get("Telegram_ID")) == str(user_id) and record.get("Status") == "Active":
                        worker_info = record
                        break
                
                if worker_info:
                    # ✅ TAKE TO DASHBOARD
                    dashboard_text = (
                        f"👷‍♂️ **Worker Dashboard**\n\n"
                        f"Name: {worker_info['Full_Name']}\n"
                        f"Total Earnings: {worker_info['Total_Earnings']} ETB\n"
                        f"Completed Jobs: {worker_info['Total_Earnings']} jobs\n"
                        f"Rating: {worker_info['Rating'] or 'N/A'} ⭐\n"
                        f"Telebirr: {worker_info['Telebirr_number']}\n"
                        f"Bank: {worker_info['Bank_type']} ••••{str(worker_info['Account_number'])[-4:]}\n\n"
                        f"Choose an option:"
                    )
                    keyboard = [
                        ["✅ Accept Jobs"],
                        ["✏️ Update Profile"],
                        ["📊 View Earnings"],
                        ["↩️ Back to Main Menu"]
                    ]
                    await update.message.reply_text(
                        dashboard_text,
                        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
                        parse_mode="Markdown"
                    )
                    USER_STATE[user_id] = {"state": STATE_WORKER_DASHBOARD, "data": {"worker_info": worker_info}}
                else:
                    await update.message.reply_text(
                        "⚠️ No account found. Please register as a new worker.\n⚠️ ማህደር አልተገኘም። እባክዎን እንደ አዲስ ሠራተኛ ይመዝገቡ።",
                        reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
                    )
            except Exception as e:
                logger.error(f"Worker login error: {e}")
                await update.message.reply_text("⚠️ Login failed. Try again.\n⚠️ መግቢያ አልተሳካም።")

    elif state == STATE_WORKER_DASHBOARD:
        worker_info = data["worker_info"]
        if text == "✅ Accept Jobs":
            await update.message.reply_text("✅ Ready for jobs! You'll receive alerts when clients post orders.\n✅ ለስራ ዝግጁ! ደንበኞች ስራ ሲለጡ ማሳወቂያ ይደርስዎታል።")
        elif text == "✏️ Update Profile":
            keyboard = [
                ["📱 Phone", "💳 Telebirr"],
                ["🏦 Bank", "🔢 Account"],
                ["📸 Fyda Photos"],
                ["↩️ Back to Main Menu"]
            ]
            await update.message.reply_text(
                "What would you like to update?\nየትኞቹን መረጃ ማሻሽል ይፈልጋሉ?",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            )
            USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_PHONE, "data": worker_info}
        elif text == "📊 View Earnings":
            total_earnings = int(worker_info['Total_Earnings'])
            commission_paid = int(total_earnings * 0.25)
            net_income = total_earnings - commission_paid
            earnings_text = (
                f"💰 **Earnings Summary**\n\n"
                f"Total Earned: {total_earnings} ETB\n"
                f"Commission Paid: {commission_paid} ETB\n"
                f"Net Income: {net_income} ETB\n"
                f"Pending Payments: 0 ETB"
            )
            await update.message.reply_text(
                earnings_text,
                reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True),
                parse_mode="Markdown"
            )

    elif state == STATE_CLIENT_CITY:
        if re.search(r'\d', text):
            keyboard = [[city] for city in ALL_CITIES]
            keyboard.append(["↩️ Back to Main Menu"])
            await update.message.reply_text(get_msg("invalid_city"))
            await update.message.reply_text(
                get_msg("choose_city"),
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            )
            return

        if text not in ACTIVE_CITIES:
            keyboard = [[city] for city in ALL_CITIES]
            keyboard.append(["↩️ Back to Main Menu"])
            await update.message.reply_text(get_msg("city_not_active", city=text))
            await update.message.reply_text(
                get_msg("choose_city"),
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            )
            return
        data["city"] = text
        USER_STATE[user_id] = {"state": STATE_CLIENT_BUREAU, "data": data}
        await update.message.reply_text(
            get_msg("enter_bureau"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    elif state == STATE_CLIENT_BUREAU:
        data["bureau"] = text
        USER_STATE[user_id] = {"state": STATE_CLIENT_LOCATION, "data": data}
        await update.message.reply_text(
            get_msg("send_location"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Share Live Location", request_location=True)], ["↩️ Back to Main Menu"]],
                one_time_keyboard=True
            )
        )

    elif state == STATE_WORKER_NAME:
        data["name"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_PHONE, "data": data}
        await update.message.reply_text(
            get_msg("worker_phone"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    elif state == STATE_WORKER_PHONE:
        data["phone"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_TELEBIRR, "data": data}
        await update.message.reply_text(
            "📱 Enter your Telebirr number:\n📱 የቴሌቢር ቁጥርዎን ይፃፉ፡",
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    elif state == STATE_WORKER_TELEBIRR:
        data["telebirr"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_BANK, "data": data}
        keyboard = [[bank] for bank in BANKS]
        keyboard.append(["↩️ Back to Main Menu"])
        await update.message.reply_text(
            "🏦 Select your bank:\n🏦 የባንክዎን ይምረጡ፡",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        )

    elif state == STATE_WORKER_BANK:
        if text not in BANKS:
            keyboard = [[bank] for bank in BANKS]
            keyboard.append(["↩️ Back to Main Menu"])
            await update.message.reply_text(
                "⚠️ Please select from the bank list.\n⚠️ ከባንክ ዝርዝሩ ይምረጡ።",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            )
            return
        data["bank_type"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_ACCOUNT_NUMBER, "data": data}
        await update.message.reply_text(
            "🔢 Enter your account number:\n🔢 የአካውንት ቁጥርዎን ይፃፉ፡",
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    elif state == STATE_WORKER_ACCOUNT_NUMBER:
        data["account_number"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_ACCOUNT_HOLDER, "data": data}
        await update.message.reply_text(
            "👤 Enter your account holder name (as on bank):\n👤 የአካውንት ባለቤት ስም (በባንክ የሚታየው)",
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    elif state == STATE_WORKER_ACCOUNT_HOLDER:
        data["account_holder"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA_FRONT, "data": data}
        await update.message.reply_text(
            get_msg("worker_fyda_front"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    elif state == STATE_CLIENT_FINAL_HOURS:
        try:
            hours = int(text)
            if 1 <= hours <= 12:
                data["hours"] = hours
                total = HOURLY_RATE * hours
                data["total"] = total
                USER_STATE[user_id] = {"state": STATE_CLIENT_FINAL_RECEIPT, "data": data}
                await update.message.reply_text(
                    get_msg("final_payment", amount=total - 100),
                    reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
                )
            else:
                await update.message.reply_text(get_msg("final_hours"))
        except ValueError:
            await update.message.reply_text(get_msg("final_hours"))

    elif state == STATE_RATING:
        try:
            rating = int(text)
            if 1 <= rating <= 5:
                update_worker_rating(data["worker_id"], rating)
                await update.message.reply_text(get_msg("rating_thanks"))
                await start(update, context)
            else:
                await update.message.reply_text(get_msg("rate_worker"))
        except ValueError:
            await update.message.reply_text(get_msg("rate_worker"))

    # Handle profile updates
    elif text == "📱 Phone":
        USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_PHONE, "data": data}
        await update.message.reply_text(
            "📱 Enter new phone number:\n📱 የአዲስ ስልክ ቁጥር ይፃፉ፡",
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )
    elif text == "💳 Telebirr":
        USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_TELEBIRR, "data": data}
        await update.message.reply_text(
            "📱 Enter new Telebirr number:\n📱 የአዲስ ቴሌቢር ቁጥር ይፃፉ፡",
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )
    elif text == "🏦 Bank":
        USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_BANK, "data": data}
        keyboard = [[bank] for bank in BANKS]
        keyboard.append(["↩️ Back to Main Menu"])
        await update.message.reply_text(
            "🏦 Select new bank:\n🏦 የአዲስ ባንክ ይምረጡ፡",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        )
    elif text == "🔢 Account":
        USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_ACCOUNT, "data": data}
        await update.message.reply_text(
            "🔢 Enter new account number:\n🔢 የአዲስ አካውንት ቁጥር ይፃፉ፡",
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )
    elif text == "📸 Fyda Photos":
        USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_FYDA, "data": data}
        await update.message.reply_text(
            get_msg("worker_fyda_front"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    elif state == STATE_WORKER_UPDATE_PHONE:
        try:
            sheet = get_worksheet("Workers")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if str(record.get("Telegram_ID")) == str(user_id):
                    sheet.update_cell(i, 3, text)
                    break
            await update.message.reply_text("✅ Phone updated!\n✅ ስልክ ቁጥር ተሻሽሏል!")
            await start(update, context)
        except Exception as e:
            logger.error(f"Phone update error: {e}")
            await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")

    elif state == STATE_WORKER_UPDATE_TELEBIRR:
        try:
            sheet = get_worksheet("Workers")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if str(record.get("Telegram_ID")) == str(user_id):
                    sheet.update_cell(i, 8, text)
                    break
            await update.message.reply_text("✅ Telebirr updated!\n✅ ቴሌቢር ተሻሽሏል!")
            await start(update, context)
        except Exception as e:
            logger.error(f"Telebirr update error: {e}")
            await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")

    elif state == STATE_WORKER_UPDATE_BANK:
        if text not in BANKS:
            keyboard = [[bank] for bank in BANKS]
            keyboard.append(["↩️ Back to Main Menu"])
            await update.message.reply_text(
                "⚠️ Please select from the bank list.\n⚠️ ከባንክ ዝርዝሩ ይምረጡ።",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            )
            return
        try:
            sheet = get_worksheet("Workers")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if str(record.get("Telegram_ID")) == str(user_id):
                    sheet.update_cell(i, 9, text)
                    break
            await update.message.reply_text("✅ Bank updated!\n✅ ባንክ ተሻሽሏል!")
            await start(update, context)
        except Exception as e:
            logger.error(f"Bank update error: {e}")
            await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")

    elif state == STATE_WORKER_UPDATE_ACCOUNT:
        try:
            sheet = get_worksheet("Workers")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if str(record.get("Telegram_ID")) == str(user_id):
                    sheet.update_cell(i, 10, text)
                    break
            await update.message.reply_text("✅ Account updated!\n✅ አካውንት ተሻሽሏል!")
            await start(update, context)
        except Exception as e:
            logger.error(f"Account update error: {e}")
            await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")

    elif state == STATE_WORKER_UPDATE_FYDA:
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA_FRONT, "data": {}}
        await update.message.reply_text(
            get_msg("worker_fyda_front"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    # 👇 TWO-WAY HANDSHAKE FLOW
    elif state == STATE_WORKER_AT_FRONT:
        if text == "✅ I'm at the front of the line":
            order_id = data["order_id"]
            try:
                order_sheet = get_worksheet("Orders")
                records = order_sheet.get_all_records()
                for rec in records:
                    if rec.get("Order_ID") == order_id:
                        client_id = rec.get("Client_TG_ID")
                        await context.bot.send_message(
                            chat_id=int(client_id),
                            text="👷‍♂️ Your worker has reached the front of the line! Press 'Confirm Arrival' when you see them.\n👷‍♂️ ሠራተኛዎ የመስረቃ መስመር ላይ ደርሷል! ሲያዩት 'መጣ ተብሎ ያረጋግጡ' ይላኩ።",
                            reply_markup=ReplyKeyboardMarkup(
                                [["✅ Confirm Arrival"], ["↩️ Back to Main Menu"]],
                                one_time_keyboard=True
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
        if text == "✅ Confirm Arrival":
            order_id = data["order_id"]
            worker_id = data["worker_id"]
            
            # Update order status
            try:
                sheet = get_worksheet("Orders")
                records = sheet.get_all_records()
                for i, rec in enumerate(records, start=2):
                    if rec.get("Order_ID") == order_id:
                        sheet.update_cell(i, 6, "Arrived")
                        break
            except Exception as e:
                logger.error(f"Arrival update error: {e}")
            
            # Prompt for hours
            await update.message.reply_text(get_msg("final_hours"))
            USER_STATE[user_id] = {
                "state": STATE_CLIENT_FINAL_HOURS,
                "data": {"order_id": order_id, "worker_id": worker_id}
            }

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

    if state == STATE_WORKER_FYDA_FRONT:
        data["fyda_front"] = update.message.photo[-1].file_id
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA_BACK, "data": data}
        await update.message.reply_text(
            get_msg("worker_fyda_back"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    elif state == STATE_WORKER_FYDA_BACK:
        data["fyda_back"] = update.message.photo[-1].file_id
        USER_STATE[user_id]["data"] = data

        worker_telegram_id = str(update.effective_user.id)
        worker_id = str(uuid4())[:8]

        try:
            sheet = get_worksheet("Workers")
            sheet.append_row([
                worker_id,
                data["name"],
                data["phone"],
                worker_telegram_id,
                "0", "0", "Pending",
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

        caption = get_msg("admin_approve_worker", name=data["name"], phone=data["phone"])
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=data["fyda_front"],
                caption=caption,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{worker_telegram_id}_{worker_id}")],
                    [InlineKeyboardButton("❌ Decline", callback_data=f"decline_{worker_telegram_id}")]
                ])
            )
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=data["fyda_back"]
            )
            await update.message.reply_text("📄 Sent to admin.\n📄 ለአስተዳዳሪ ተልኳል።")
        except Exception as e:
            logger.error(f"Admin notify error: {e}")
            await update.message.reply_text("⚠️ Failed to notify admin. Try again.\n⚠️ አስተዳዳሪ ማሳወቅ አልተሳካም።")

    elif state == STATE_CLIENT_BOOKING_RECEIPT:
        worker_id = data.get("assigned_worker")
        if not worker_id:
            await update.message.reply_text("⚠️ No worker assigned. Please wait for a worker first.\n⚠️ ሰራተኛ አልተመደበም።")
            return

        try:
            worker_sheet = get_worksheet("Workers")
            worker_records = worker_sheet.get_all_records()
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
            f"🆕 PAYMENT VERIFICATION NEEDED\n"
            f"Client ID: {user_id}\n"
            f"Worker: {worker_info['Full_Name']}\n"
            f"Account Holder: {worker_info['Name_holder']}\n"
            f"Amount: 100 ETB"
        )
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=update.message.photo[-1].file_id,
                caption=caption,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Verify Payment", callback_data=f"verify_{user_id}_{worker_id}")],
                    [InlineKeyboardButton("❌ Reject Receipt", callback_data=f"reject_{user_id}")]
                ])
            )
            await update.message.reply_text("📄 Receipt sent to admin for verification.\n📄 ሲምበር ለአስተዳዳሪ ምርመራ ተልኳል።")
        except Exception as e:
            logger.error(f"Payment forward error: {e}")
            await update.message.reply_text("⚠️ Failed to send receipt. Try again.\n⚠️ ሲምበር ማስተላለፍ አልተሳካም።")

    elif state == STATE_CLIENT_FINAL_RECEIPT:
        total = data["total"]
        worker_id = data["worker_id"]
        commission = int(total * COMMISSION_PERCENT)

        try:
            sheet = get_worksheet("Orders")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if record.get("Order_ID") == data["order_id"]:
                    sheet.update_cell(i, 12, "Fully Paid")
                    break
        except Exception as e:
            logger.error(f"Order update error: {e}")

        await context.bot.send_message(
            chat_id=worker_id,
            text=get_msg("commission_request", total=total, commission=commission)
        )
        start_commission_timer(context.application, data["order_id"], worker_id, total)

        USER_STATE[user_id] = {"state": STATE_RATING, "data": {"worker_id": worker_id}}
        await update.message.reply_text(
            get_msg("rate_worker"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

    elif state == STATE_WORKER_CHECKIN_PHOTO:
        data["checkin_photo"] = update.message.photo[-1].file_id
        USER_STATE[user_id] = {"state": STATE_WORKER_CHECKIN_LOCATION, "data": data}
        await update.message.reply_text(
            get_msg("checkin_location"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    get_or_create_user(user_id, user.first_name or "User", user.username)

    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return

    state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}})
    state = state_info["state"]
    data = state_info["data"]

    if not update.message or not update.message.location:
        return

    if state == STATE_CLIENT_LOCATION:
        data["location"] = (update.message.location.latitude, update.message.location.longitude)
        USER_STATE[user_id]["data"] = data
        
        order_id = f"YZL-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:4].upper()}"
        try:
            sheet = get_worksheet("Orders")
            sheet.append_row([
                order_id,
                str(datetime.now()),
                str(user_id),
                data["bureau"],
                data["city"],
                "Pending",
                "",
                "1",
                str(HOURLY_RATE),
                "No",
                "0",
                "Pending",
                str(update.message.location.latitude),
                str(update.message.location.longitude)
            ])
        except Exception as e:
            logger.error(f"Order create error: {e}")
            await update.message.reply_text("⚠️ Failed to create order. Try again.\n⚠️ ትዕዛዝ ማድረግ አልተሳካም።")
            return

        await update.message.reply_text(
            "✅ Order created! Notifying workers...\n✅ ትዕዛዝ ተፈጸመ! ሠራተኞች ተሳይተዋል..."
        )

        # ✅ SEND TO EACH WORKER DIRECTLY (NO CHANNEL)
        try:
            worker_sheet = get_worksheet("Workers")
            worker_records = worker_sheet.get_all_records()
            notified_count = 0
            
            for worker in worker_records:
                if worker.get("Status") == "Active":
                    try:
                        await context.bot.send_message(
                            chat_id=int(worker["Telegram_ID"]),
                            text=get_msg("job_post", bureau=data["bureau"], city=data["city"], rate=HOURLY_RATE),
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("Accept", callback_data=f"accept_{order_id}_{user_id}")]
                            ])
                        )
                        notified_count += 1
                    except Exception as e:
                        logger.error(f"Failed to notify worker {worker['Telegram_ID']}: {e}")
            
            logger.info(f"Notified {notified_count} workers about order {order_id}")
            
        except Exception as e:
            logger.error(f"Worker notification error: {e}")
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🚨 Failed to notify workers for order {order_id}\nError: {str(e)}"
            )
            await update.message.reply_text("⚠️ Workers notified manually. Admin will assign soon.\n⚠️ ሠራተኞች በእጅ ተሳይተዋል።")

    elif state == STATE_WORKER_CHECKIN_LOCATION:
        data["checkin_location"] = (update.message.location.latitude, update.message.location.longitude)
        try:
            sheet = get_worksheet("Orders")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if record.get("Worker_ID") == str(user_id) and record.get("Status") == "Assigned":
                    sheet.update_cell(i, 6, "Checked In")
                    client_id = record.get("Client_TG_ID")
                    
                    asyncio.run_coroutine_threadsafe(
                        context.bot.send_message(
                            chat_id=int(client_id),
                            text="✅ Worker checked in! Live location active.\n✅ ሠራተኛ ተገኝቷል! የቀጥታ መገኛ አንስቶ ነው።"
                        ),
                        context.application.updater.dispatcher.loop
                    )
                    
                    order_id = record.get("Order_ID")
                    job_lat = float(record.get("Latitude", 0))
                    job_lon = float(record.get("Longitude", 0))
                    
                    distance = calculate_distance(
                        update.message.location.latitude,
                        update.message.location.longitude,
                        job_lat,
                        job_lon
                    )
                    
                    if distance > MAX_ALLOWED_DISTANCE:
                        ban_user(user_id, f"Left job site (>500m)")
                        sheet.update_cell(i, 6, "Cancelled")
                        asyncio.run_coroutine_threadsafe(
                            context.bot.send_message(
                                chat_id=int(client_id),
                                text=get_msg("worker_far_ban")
                            ),
                            context.application.updater.dispatcher.loop
                        )
                        asyncio.run_coroutine_threadsafe(
                            context.bot.send_message(
                                chat_id=user_id,
                                text=get_msg("worker_far_ban")
                            ),
                            context.application.updater.dispatcher.loop
                        )
                        logger.info(f"Auto-banned worker {user_id} for moving {distance:.0f}m from job site")
                    elif distance > MAX_WARNING_DISTANCE:
                        asyncio.run_coroutine_threadsafe(
                            context.bot.send_message(
                                chat_id=int(client_id),
                                text=get_msg("worker_far_warning")
                            ),
                            context.application.updater.dispatcher.loop
                        )
                        asyncio.run_coroutine_threadsafe(
                            context.bot.send_message(
                                chat_id=user_id,
                                text=get_msg("worker_far_warning")
                            ),
                            context.application.updater.dispatcher.loop
                        )
                        logger.info(f"Warning: worker {user_id} moved {distance:.0f}m from job site")
                    break
        except Exception as e:
            logger.error(f"Check-in update error: {e}")

        # 👇 SEND ACTION BUTTONS AFTER CHECK-IN
        keyboard = [
            ["✅ I'm at the front of the line"],
            ["↩️ Back to Main Menu"]
        ]
        await update.message.reply_text(
            "✅ Check-in complete! When you reach the front of the line, press the button below.\n✅ የመግቢያ ሂደት ተጠናቅቋል! የመስረቃ መስመር ላይ ሲደርሱ ከታች ያለውን ቁልፍ ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        )
        USER_STATE[user_id] = {"state": STATE_WORKER_AT_FRONT, "data": {"order_id": order_id}}

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

    if data == "cancel":
        USER_STATE[user_id] = {"state": STATE_NONE, "data": {}}
        await query.message.reply_text("Cancelled.\nሰርዟል።")

    elif data.startswith("approve_"):
        parts = data.split("_")
        worker_tg_id = parts[1]
        worker_db_id = parts[2]
        
        try:
            sheet = get_worksheet("Workers")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if str(record.get("Worker_ID")) == str(worker_db_id):
                    sheet.update_cell(i, 7, "Active")
                    break
        except Exception as e:
            logger.error(f"Approve error: {e}")
        
        try:
            await context.bot.send_message(chat_id=int(worker_tg_id), text=get_msg("worker_approved"))
        except Exception as e:
            logger.error(f"Message worker error: {e}")
        
        await query.edit_message_caption(caption="✅ Approved!\n✅ ተፈቅዶልናል!")

    elif data.startswith("decline_"):
        worker_tg_id = data.split("_")[1]
        try:
            sheet = get_worksheet("Workers")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if str(record.get("Telegram_ID")) == str(worker_tg_id):
                    sheet.update_cell(i, 7, "Declined")
                    break
        except Exception as e:
            logger.error(f"Decline error: {e}")
        await context.bot.send_message(chat_id=int(worker_tg_id), text=get_msg("worker_declined"))
        await query.edit_message_caption(caption="❌ Declined.\n❌ ተውግዷል።")

    elif data.startswith("accept_"):
        parts = data.split("_")
        order_id = parts[1]
        client_id = parts[2]
        
        # 🔒 ATOMIC JOB ASSIGNMENT
        try:
            sheet = get_worksheet("Orders")
            records = sheet.get_all_records()
            order = None
            row_idx = -1
            for i, record in enumerate(records):
                if record.get("Order_ID") == order_id:
                    order = record
                    row_idx = i + 2
                    break
            
            if not order or order.get("Status") != "Pending":
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ Sorry, this job was already taken by another worker.\n⚠️ ስራው ቀድሞውና ተወስቷል።"
                )
                return
        except Exception as e:
            logger.error(f"Job lock check error: {e}")
            await context.bot.send_message(chat_id=user_id, text="⚠️ Job assignment failed. Try again.")
            return
        
        # Proceed with assignment
        try:
            sheet.update_cell(row_idx, 7, str(user_id))
            sheet.update_cell(row_idx, 6, "Assigned")

            worker_sheet = get_worksheet("Workers")
            worker_records = worker_sheet.get_all_records()
            worker_info = None
            for wr in worker_records:
                if str(wr.get("Telegram_ID")) == str(user_id):
                    worker_info = wr
                    break

            if worker_info:
                contact_msg = (
                    f"👷‍♂️ Worker found!\n"
                    f"Name: {worker_info['Full_Name']}\n"
                    f"Phone: {worker_info['Phone_Number']}\n"
                    f"Telebirr: {worker_info['Telebirr_number']}\n"
                    f"Bank: {worker_info['Bank_type']} ••••{str(worker_info['Account_number'])[-4:]}"
                )
                await context.bot.send_message(chat_id=int(client_id), text=contact_msg)
                await context.bot.send_message(
                    chat_id=int(client_id),
                    text="💳 Pay 100 ETB to their Telebirr or bank, then upload payment receipt.\n💳 ለቴሌቢር ወይም ባንክ አካውንቱ 100 ብር ይላክሱ እና ሲምበር ያስገቡ።"
                )
                
                if int(client_id) not in USER_STATE:
                    USER_STATE[int(client_id)] = {"state": STATE_NONE, "data": {}}
                USER_STATE[int(client_id)]["state"] = STATE_CLIENT_BOOKING_RECEIPT
                USER_STATE[int(client_id)]["data"]["assigned_worker"] = worker_info["Worker_ID"]
            else:
                await context.bot.send_message(chat_id=int(client_id), text="⚠️ Worker details not found.\n⚠️ ዝርዝሮች አልተገኙም።")
            
            bureau = order["Bureau_Name"]
            USER_STATE[user_id] = {
                "state": STATE_WORKER_CHECKIN_PHOTO,
                "data": {"order_id": order_id, "bureau": bureau}
            }
            await context.bot.send_message(
                chat_id=user_id,
                text=get_msg("checkin_photo", bureau=bureau)
            )
            
            # 👇 START LOCATION MONITOR
            context.job_queue.run_repeating(
                check_worker_location,
                interval=300,  # 5 minutes
                first=10,
                data={"worker_id": user_id, "order_id": order_id},
                name=f"location_monitor_{order_id}"
            )
            
        except Exception as e:
            logger.error(f"Accept error: {e}")

    elif data.startswith("verify_"):
        parts = data.split("_")
        client_id = int(parts[1])
        worker_id = parts[2]

        try:
            sheet = get_worksheet("Orders")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if record.get("Client_TG_ID") == str(client_id) and record.get("Status") == "Pending":
                    sheet.update_cell(i, 6, "Verified")
                    sheet.update_cell(i, 10, "Yes")
                    break
        except Exception as e:
            logger.error(f"Verify error: {e}")

        await context.bot.send_message(chat_id=client_id, text="✅ Payment verified! Job proceeding.\n✅ ክፍያ ተረጋግጧል! ስራ ተከዋል።")
        await query.edit_message_caption(caption="✅ Verified!\n✅ ተረጋግጧል!")
    elif data.startswith("reject_"):
        client_id = int(data.split("_")[1])
        await context.bot.send_message(chat_id=client_id, text="❌ Payment rejected. Please resend correct receipt.\n❌ ክፍያ ተውግዷል። እባክዎን ትክክለኛ ሲምበር ይላኩ።")
        await query.edit_message_caption(caption="❌ Rejected.\n❌ ተውግዷል።")

    elif data == "turn_on_location":
        order_id = USER_STATE[user_id]["data"].get("order_id")
        if order_id:
            try:
                sheet = get_worksheet("Orders")
                records = sheet.get_all_records()
                for record in records:
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
# FLASK / HEALTH + WEBHOOK
# ======================

flask_app = Flask(__name__)

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok"})

# 👇 FIXED WEBHOOK ROUTE
@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
    return "OK"

# ======================
# ERROR HANDLER
# ======================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)

# ======================
# MAIN
# ======================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # 👇 ADD THIS BLOCK TO AUTO-SET WEBHOOK AND PREVENT CONFLICT
    if os.environ.get("WEBHOOK_URL"):
        import requests
        webhook_url = f"{os.environ['WEBHOOK_URL']}/{BOT_TOKEN}"
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}")
    
    from threading import Thread
    Thread(target=lambda: flask_app.run(host="0.0.0.0", port=port)).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_error_handler(error_handler)

    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=f"{webhook_url}/{BOT_TOKEN}"
        )
    else:
        application.run_polling()
    
