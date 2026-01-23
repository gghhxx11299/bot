import os
import logging
from datetime import datetime, timedelta
from threading import Timer, Thread
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
import signal
import sys

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
    "worker_approved": {"en": "✅ Approved! You'll receive job alerts soon.", "am": "✅ ፀድቋል! በቅርቡ የስራ ማስታወቂያ ይደርስዎታል።"},
    "worker_declined": {"en": "❌ Declined. Contact admin for details.", "am": "❌ ውድቅ ተደርጓል። ለተጨማሪ መረጃ አስተዳዳሪውን ያነጋግሩ።"},
    "order_created": {"en": "✅ Order created! Searching for workers...", "am": "✅ ትዕዛዝ ተፈጥሯል! ሰራተኛ እየፈለግን ነው..."},
    "job_post": {"en": "📍 {bureau}\n🏙️ {city}\n💰 100 ETB/hour\n[Accept]", "am": "📍 {bureau}\n🏙️ {city}\n💰 በሰዓት 100 ብር\n[ተቀበል]"},
    "worker_accepted": {"en": "✅ Worker accepted! They'll check in soon.", "am": "✅ ሰራተኛ ተገኝቷል! በቅርቡ ያገኙዎታል።"},
    "checkin_photo": {"en": "📸 Send photo of yourself in line at {bureau}", "am": "📸 በ{bureau} ውስጥ ያለውን ፎቶ ይላኩ"},
    "checkin_location": {"en": "📍 Start live location sharing now", "am": "📍 አሁን የቀጥታ መገኛ ያጋሩ"},
    "checkin_complete": {"en": "✅ Check-in complete! Client notified.", "am": "✅ የመግቢያ ሂደት ተጠናቅቋል!"},
    "location_off_alert": {"en": "⚠️ Worker's location is off!", "am": "⚠️ የሰራተኛው መገኛ ጠፍቷል!"},
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
    "reason_no_show": {"en": "Worker didn't show", "am": "ሰራተኛው አልመጣም"},
    "reason_payment": {"en": "Payment issue", "am": "የክፍያ ችግር"},
    "reason_fake_photo": {"en": "Fake photo", "am": "ሀሰተኛ ፎቶ"},
    "dispute_submitted": {"en": "📄 Dispute submitted. Admin will review shortly.", "am": "📄 ቅሬታዎ ቀርቧል። አስተዳዳሪው በቅርቡ ይመለከተዋል።"},
    "rate_worker": {"en": "How would you rate this worker? (1-5 stars)", "am": "ለዚህ ሰራተኛ ምን ያህል ኮከብ ይሰጣሉ? (ከ1-5 ኮከቦች)"},
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
    """Get worksheet with handling for duplicate headers."""
    try:
        client = get_sheet_client()
        worksheet = client.open_by_key(SHEET_ID).worksheet(sheet_name)
        return worksheet
    except Exception as e:
        logger.error(f"Error getting worksheet '{sheet_name}': {e}")
        raise

def get_worksheet_data(sheet_name):
    """Get worksheet data as list of dictionaries, handling duplicate headers."""
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
    """Update a cell in worksheet."""
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
                # Find Status column
                for j, header in enumerate(headers):
                    if header == "Status":
                        if j < len(row):
                            worksheet.update_cell(i, j + 1, "Banned")
                        else:
                            # If column doesn't exist in this row, extend it
                            if j >= len(row):
                                for _ in range(j - len(row) + 1):
                                    row.append("")
                            worksheet.update(f"{chr(65+j)}{i}", "Banned")
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
        
        # User not found, create new
        worksheet = get_worksheet("Users")
        now = str(datetime.now())
        worksheet.append_row([
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
        worksheet = get_worksheet("Workers")
        all_values = worksheet.get_all_values()
        
        if not all_values or len(all_values) < 2:
            return
        
        headers = all_values[0]
        
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > 0 and str(row[0]) == str(worker_id):
                # Find Rating and Total_Earnings columns
                rating_col = None
                earnings_col = None
                
                for j, header in enumerate(headers):
                    if header == "Rating":
                        rating_col = j
                    elif header == "Total_Earnings":
                        earnings_col = j
                
                if rating_col is not None and earnings_col is not None:
                    # Get current values
                    current_rating = float(row[rating_col]) if rating_col < len(row) and row[rating_col] else 0
                    current_earnings = int(row[earnings_col]) if earnings_col < len(row) and row[earnings_col] else 0
                    
                    # Calculate new rating
                    total_jobs = current_earnings or 1
                    new_rating = (current_rating * total_jobs + rating) / (total_jobs + 1)
                    
                    # Update cells
                    worksheet.update_cell(i, rating_col + 1, str(new_rating))
                    worksheet.update_cell(i, earnings_col + 1, str(total_jobs + 1))
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
        try:
            # Create new event loop for async operation
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Use the same bot instance from application
            async def send_alert():
                try:
                    await application.bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"🚨 Auto-banned Worker {worker_id} for missing commission on {order_id}"
                    )
                except Exception as e:
                    logger.error(f"Commission alert error: {e}")
            
            loop.run_until_complete(send_alert())
            loop.close()
        except Exception as e:
            logger.error(f"Commission timer error: {e}")
    
    # Start timer
    timer = Timer(COMMISSION_TIMEOUT_HOURS * 3600, final_action)
    timer.daemon = True
    timer.start()
    return timer

# ======================
# LOCATION MONITOR
# ======================
async def check_worker_location(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    worker_id = job.data["worker_id"]
    order_id = job.data["order_id"]
    try:
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
        "ℹ️ **Yazilign Service Terms**\n"
        "• Workers are independent contractors\n"
        "• Pay only after service completion\n"
        "• 25% commission is mandatory\n"
        "• Fake photos/fraud = permanent ban\n"
        "• We are not liable for user disputes\n"
        "ℹ️ **የያዝልኝ አገልግሎት ውሎች**\n"
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
        f"{legal_notice}\n{get_msg('start')}",
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
    
    if text == "↩️ Back to Main Menu" or text == "↩️ ወደ ዋና ገጽ":
        await start(update, context)
        return
    
    if text == "/health":
        await update.message.reply_text("OK")
        return
    
    if text == "/start":
        await start(update, context)
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
    
    elif text == "Admin" and user_id == ADMIN_CHAT_ID:
        await update.message.reply_text(
            "👑 Admin Panel\n"
            "Commands:\n"
            "/stats - Show statistics\n"
            "/users - List all users\n"
            "/orders - List all orders\n"
            "/workers - List all workers"
        )
    
    elif state == STATE_WORKER_LOGIN_OR_REGISTER:
        if text == "✅ Register as New Worker":
            USER_STATE[user_id] = {"state": STATE_WORKER_NAME, "data": {}}
            await update.message.reply_text(
                get_msg("worker_welcome"),
                reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
            )
        
        elif text == "🔑 Login as Existing Worker":
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
                        f"👷‍♂️ **Worker Dashboard**\n"
                        f"Name: {worker_info.get('Full_Name', 'N/A')}\n"
                        f"Total Earnings: {worker_info.get('Total_Earnings', '0')} ETB\n"
                        f"Completed Jobs: {worker_info.get('Total_Earnings', '0')} jobs\n"
                        f"Rating: {worker_info.get('Rating', 'N/A')} ⭐\n"
                        f"Telebirr: {worker_info.get('Telebirr_number', 'N/A')}\n"
                        f"Bank: {worker_info.get('Bank_type', 'N/A')} ••••{last_four}\n"
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
        worker_info = data.get("worker_info", {})
        if text == "✅ Accept Jobs":
            await update.message.reply_text(
                "✅ Ready for jobs! You'll receive alerts when clients post orders.\n✅ ለስራ ዝግጁ! ደንበኞች ስራ ሲለጡ ማሳወቂያ ይደርስዎታል።",
                reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
            )
            USER_STATE[user_id] = {"state": STATE_NONE, "data": {}}
        
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
            USER_STATE[user_id] = {"state": STATE_WORKER_UPDATE_MENU, "data": worker_info}
        
        elif text == "📊 View Earnings":
            total_earnings = int(worker_info.get('Total_Earnings', 0))
            commission_paid = int(total_earnings * 0.25)
            net_income = total_earnings - commission_paid
            earnings_text = (
                f"💰 **Earnings Summary**\n"
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
    
    elif state == STATE_WORKER_UPDATE_MENU:
        if text == "📱 Phone":
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
    
    elif state == STATE_WORKER_UPDATE_PHONE:
        try:
            worksheet = get_worksheet("Workers")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
                return
            
            headers = all_values[0]
            phone_col = None
            
            # Find phone column
            for j, header in enumerate(headers):
                if header == "Phone_Number":
                    phone_col = j
                    break
            
            if phone_col is None:
                await update.message.reply_text("⚠️ Phone column not found.\n⚠️ የስልክ አምድ አልተገኘም።")
                return
            
            # Update phone for the worker
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(user_id):  # Telegram_ID is usually column D (index 3)
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
            
            # Find Telebirr column
            for j, header in enumerate(headers):
                if header == "Telebirr_number":
                    telebirr_col = j
                    break
            
            if telebirr_col is None:
                await update.message.reply_text("⚠️ Telebirr column not found.\n⚠️ ቴሌቢር አምድ አልተገኘም።")
                return
            
            # Update Telebirr for the worker
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(user_id):  # Telegram_ID is usually column D (index 3)
                    worksheet.update_cell(i, telebirr_col + 1, text)
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
            worksheet = get_worksheet("Workers")
            all_values = worksheet.get_all_values()
            
            if not all_values:
                await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
                return
            
            headers = all_values[0]
            bank_col = None
            
            # Find bank column
            for j, header in enumerate(headers):
                if header == "Bank_type":
                    bank_col = j
                    break
            
            if bank_col is None:
                await update.message.reply_text("⚠️ Bank column not found.\n⚠️ ባንክ አምድ አልተገኘም።")
                return
            
            # Update bank for the worker
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(user_id):  # Telegram_ID is usually column D (index 3)
                    worksheet.update_cell(i, bank_col + 1, text)
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
            
            # Find account column
            for j, header in enumerate(headers):
                if header == "Account_number":
                    account_col = j
                    break
            
            if account_col is None:
                await update.message.reply_text("⚠️ Account column not found.\n⚠️ አካውንት አምድ አልተገኘም።")
                return
            
            # Update account for the worker
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(user_id):  # Telegram_ID is usually column D (index 3)
                    worksheet.update_cell(i, account_col + 1, text)
                    break
            
            await update.message.reply_text("✅ Account updated!\n✅ አካውንት ተሻሽሏል!")
            await start(update, context)
        except Exception as e:
            logger.error(f"Account update error: {e}")
            await update.message.reply_text("⚠️ Failed to update. Try again.\n⚠️ ማሻሻል አልተሳካም።")
    
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
    
    elif state == STATE_WORKER_AT_FRONT:
        if text == "✅ I'm at the front of the line":
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
            try:
                worksheet = get_worksheet("Orders")
                all_values = worksheet.get_all_values()
                
                if not all_values:
                    await update.message.reply_text("⚠️ Error updating order.\n⚠️ ትዕዛዝ ማሻሻል ላይ ስህተት።")
                    return
                
                headers = all_values[0]
                status_col = None
                
                # Find status column
                for j, header in enumerate(headers):
                    if header == "Status":
                        status_col = j
                        break
                
                if status_col is None:
                    await update.message.reply_text("⚠️ Status column not found.\n⚠️ ሁኔታ አምድ አልተገኘም።")
                    return
                
                # Update status for the order
                for i, row in enumerate(all_values[1:], start=2):
                    if len(row) > 0 and row[0] == order_id:  # Order_ID is column A (index 0)
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
        # Default response for unrecognized input
        await update.message.reply_text(
            "Please use the menu buttons.\nእባክዎን የምና ቁልፎችን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
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
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
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
                "0",  # Total_Earnings
                "0",  # Rating
                "Pending",  # Status
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
            # Send front photo
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=data["fyda_front"],
                caption=caption,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{worker_telegram_id}_{worker_id}")],
                    [InlineKeyboardButton("❌ Decline", callback_data=f"decline_{worker_telegram_id}")]
                ])
            )
            # Send back photo
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=data["fyda_back"],
                caption="Back of Fyda"
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
            f"🆕 PAYMENT VERIFICATION NEEDED\n"
            f"Client ID: {user_id}\n"
            f"Worker: {worker_info.get('Full_Name', 'N/A')}\n"
            f"Account Holder: {worker_info.get('Name_holder', 'N/A')}\n"
            f"Amount: 100 ETB"
        )
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=photo_file_id,
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
            
            # Find payment status column
            for j, header in enumerate(headers):
                if header == "Payment_Status":
                    payment_status_col = j
                    break
            
            if payment_status_col is not None:
                # Update payment status for the order
                for i, row in enumerate(all_values[1:], start=2):
                    if len(row) > 0 and row[0] == order_id:  # Order_ID is column A (index 0)
                        worksheet.update_cell(i, payment_status_col + 1, "Fully Paid")
                        break
        except Exception as e:
            logger.error(f"Order update error: {e}")
        
        # Send commission request to worker
        try:
            await context.bot.send_message(
                chat_id=int(worker_id),
                text=get_msg("commission_request", total=total, commission=commission)
            )
        except Exception as e:
            logger.error(f"Commission notification error: {e}")
        
        # Start commission timer
        start_commission_timer(context.application, order_id, worker_id, total)
        
        # Ask for rating
        USER_STATE[user_id] = {"state": STATE_RATING, "data": {"worker_id": worker_id}}
        await update.message.reply_text(
            get_msg("rate_worker"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )
    
    elif state == STATE_WORKER_CHECKIN_PHOTO:
        data["checkin_photo"] = photo_file_id
        USER_STATE[user_id] = {"state": STATE_WORKER_CHECKIN_LOCATION, "data": data}
        await update.message.reply_text(
            get_msg("checkin_location"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Share Live Location", request_location=True)], ["↩️ Back to Main Menu"]],
                one_time_keyboard=True
            )
        )
    
    elif state == STATE_WORKER_UPDATE_FYDA:
        # Start the Fyda upload process
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA_FRONT, "data": {}}
        await update.message.reply_text(
            get_msg("worker_fyda_front"),
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
        )
    
    else:
        await update.message.reply_text(
            "I don't understand what to do with this photo. Please use the menu.\nይህን ፎቶ ምን ማድረግ እንዳለብኝ አላውቅም። እባክዎን ምናውን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
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
    
    if state == STATE_CLIENT_LOCATION:
        data["location"] = (lat, lon)
        USER_STATE[user_id]["data"] = data
        order_id = f"YZL-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:4].upper()}"
        
        logger.info(f"Creating new order {order_id} for client {user_id}")
        
        try:
            worksheet = get_worksheet("Orders")
            # Create order with explicit "Pending" status
            worksheet.append_row([
                order_id,
                str(datetime.now()),
                str(user_id),
                data.get("bureau", ""),
                data.get("city", ""),
                "Pending",  # Status
                "",  # Worker_ID
                "1",  # Hours
                str(HOURLY_RATE),  # Hourly_Rate
                "No",  # Payment_Verified
                "0",  # Total_Amount
                "Pending",  # Payment_Status
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
                                [InlineKeyboardButton("Accept", callback_data=f"accept_{order_id}_{user_id}")]
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
            
            # Find column indices
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
                    
                    # Update status to "Checked In"
                    if status_col is not None:
                        worksheet.update_cell(i, status_col + 1, "Checked In")
                    
                    # Notify client
                    if client_id_col is not None and client_id_col < len(row):
                        client_id = row[client_id_col]
                        try:
                            await context.bot.send_message(
                                chat_id=int(client_id),
                                text="✅ Worker checked in! Live location active.\n✅ ሠራተኛ ተገኝቷል! የቀጥታ መገኛ አንስቶ ነው።"
                            )
                        except Exception as e:
                            logger.error(f"Client notification error: {e}")
                    
                    # Get job location and calculate distance
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
                ["✅ I'm at the front of the line"],
                ["↩️ Back to Main Menu"]
            ]
            await update.message.reply_text(
                "✅ Check-in complete! When you reach the front of the line, press the button below.\n✅ የመግቢያ ሂደት ተጠናቅቋል! የመስረቃ መስመር ላይ ሲደርሱ ከታች ያለውን ቁልፍ ይጫኑ።",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            )
            USER_STATE[user_id] = {"state": STATE_WORKER_AT_FRONT, "data": {"order_id": order_id}}
        else:
            await update.message.reply_text(
                "⚠️ Could not find your assigned order. Please contact admin.\n⚠️ የተመደበልዎ ትዕዛዝ ሊገኝ አልቻለም። አስተዳዳሪውን ያነጋግሩ።"
            )
    
    else:
        await update.message.reply_text(
            "Location received, but I'm not sure what to do with it. Please use the menu.\nመገኛዎ ተቀበልኩ፣ ነገር ግን ምን ማድረግ እንዳለብኝ አላውቅም። እባክዎን ምናውን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup([["↩️ Back to Main Menu"]], one_time_keyboard=True)
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
    
    if data.startswith("accept_"):
        parts = data.split("_")
        if len(parts) < 3:
            await query.edit_message_text("⚠️ Invalid job data.")
            return
        
        order_id = parts[1]
        client_id = parts[2]
        
        logger.info(f"Worker {user_id} attempting to accept order {order_id}")
        
        try:
            # Get all orders
            all_values = []
            try:
                worksheet = get_worksheet("Orders")
                all_values = worksheet.get_all_values()
            except Exception as e:
                logger.error(f"Error getting Orders worksheet: {e}")
                await query.edit_message_text(
                    "⚠️ Error accessing orders. Please try again.\n⚠️ ትዕዛዞች ላይ ስህተት። እንደገና ይሞክሩ።"
                )
                return
            
            if not all_values or len(all_values) < 2:
                await query.edit_message_text("⚠️ No orders found.")
                return
            
            # Get headers
            headers = all_values[0]
            logger.info(f"Order headers: {headers}")
            
            # Find the order
            order = None
            row_idx = -1
            status_col_idx = None
            
            # Find status column
            for j, header in enumerate(headers):
                if header == "Status":
                    status_col_idx = j
                    break
            
            if status_col_idx is None:
                # Try to find status column with different name
                for j, header in enumerate(headers):
                    if "status" in header.lower():
                        status_col_idx = j
                        break
            
            logger.info(f"Status column index: {status_col_idx}")
            
            # Also find Order_ID column
            order_id_col_idx = None
            for j, header in enumerate(headers):
                if header == "Order_ID":
                    order_id_col_idx = j
                    break
            
            if order_id_col_idx is None:
                # Try to find Order_ID column with different name
                for j, header in enumerate(headers):
                    if "order" in header.lower() and "id" in header.lower():
                        order_id_col_idx = j
                        break
            
            logger.info(f"Order_ID column index: {order_id_col_idx}")
            
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
                # Try alternative: check first column if order_id not found
                for i, row in enumerate(all_values[1:], start=2):
                    if len(row) > 0 and row[0] == order_id:  # First column
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
            
            # Check if job is still available
            current_status = order.get("Status", "")
            logger.info(f"Current status of order {order_id}: '{current_status}'")
            
            # Check various possible status values (strip whitespace and normalize)
            current_status_clean = str(current_status).strip().lower()
            available_statuses = ["pending", "available", "open", ""]
            
            if current_status_clean not in available_statuses:
                logger.info(f"Order {order_id} not available. Status: '{current_status}' (cleaned: '{current_status_clean}')")
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
            # Update the order status and assign worker
            worksheet = get_worksheet("Orders")
            
            # Find Worker_ID column
            worker_id_col = None
            for j, header in enumerate(headers):
                if header == "Worker_ID":
                    worker_id_col = j
                    break
            
            logger.info(f"Worker_ID column index: {worker_id_col}")
            
            # Update worker ID
            if worker_id_col is not None:
                worksheet.update_cell(row_idx, worker_id_col + 1, str(user_id))
                logger.info(f"Updated Worker_ID at cell ({row_idx}, {worker_id_col + 1}) to {user_id}")
            else:
                # If Worker_ID column not found, try column 7 (G) as fallback
                worksheet.update_cell(row_idx, 7, str(user_id))
                logger.info(f"Updated Worker_ID at cell ({row_idx}, 7) to {user_id}")
            
            # Update status to "Assigned"
            if status_col_idx is not None:
                worksheet.update_cell(row_idx, status_col_idx + 1, "Assigned")
                logger.info(f"Updated Status at cell ({row_idx}, {status_col_idx + 1}) to 'Assigned'")
            else:
                # If Status column not found, try column 6 (F) as fallback
                worksheet.update_cell(row_idx, 6, "Assigned")
                logger.info(f"Updated Status at cell ({row_idx}, 6) to 'Assigned'")
            
            # Get worker info
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
                # Format account number for display
                account_number = str(worker_info.get("Account_number", ""))
                last_four = account_number[-4:] if len(account_number) >= 4 else account_number
                
                contact_msg = (
                    f"👷‍♂️ Worker found!\n"
                    f"Name: {worker_info.get('Full_Name', 'N/A')}\n"
                    f"Phone: {worker_info.get('Phone_Number', 'N/A')}\n"
                    f"Telebirr: {worker_info.get('Telebirr_number', 'N/A')}\n"
                    f"Bank: {worker_info.get('Bank_type', 'N/A')} ••••{last_four}"
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
            
            # Start location monitoring
            context.job_queue.run_repeating(
                check_worker_location,
                interval=300,
                first=10,
                data={"worker_id": user_id, "order_id": order_id},
                name=f"location_monitor_{order_id}"
            )
            
            # Notify worker of successful acceptance
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ You've accepted the job at {bureau}! Please proceed to check-in.\n✅ በ{bureau} ያለውን ስራ ተቀብለዋል! እባክዎን ወደ ምዝገባ ይሂዱ።"
            )
            
            # Notify client
            await context.bot.send_message(
                chat_id=int(client_id),
                text=f"✅ A worker has accepted your job at {bureau}! They will check in soon.\n✅ በ{bureau} ያለውን ስራዎ ሠራተኛ ተቀብሏል! በቅርቡ ያገኙዎታል።"
            )
            
            # Also update the message that the worker clicked on
            try:
                await query.edit_message_text(
                    text=f"✅ You've accepted this job!\n📍 Bureau: {bureau}\n⏰ Please proceed to check-in.",
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
            
            # Find status column
            for j, header in enumerate(headers):
                if header == "Status":
                    status_col = j
                    break
            
            if status_col is None:
                return
            
            # Update worker status
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and row[0] == worker_db_id:  # Worker_ID is first column
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
            
            # Find status column
            for j, header in enumerate(headers):
                if header == "Status":
                    status_col = j
                    break
            
            if status_col is None:
                return
            
            # Update worker status
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[3]) == str(worker_tg_id):  # Telegram_ID is usually column D (index 3)
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
            
            # Find columns
            for j, header in enumerate(headers):
                if header == "Status":
                    status_col = j
                elif header == "Payment_Verified":
                    payment_verified_col = j
            
            # Update order
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and str(row[2]) == str(client_id) and row[5] == "Pending":  # Client_TG_ID and Status
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
# ERROR HANDLER
# ======================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=context.error)

# ======================
# FLASK APP
# ======================
flask_app = Flask(__name__)

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok"})

# ======================
# MAIN FUNCTION
# ======================
def main():
    # Check required environment variables
    required_vars = ["TELEGRAM_BOT_TOKEN_MAIN", "ADMIN_CHAT_ID", "SHEET_ID"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        sys.exit(1)
    
    port = int(os.environ.get("PORT", 10000))
    
    # Build application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_error_handler(error_handler)
    
    # Start Flask in background thread
    def run_flask():
        flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    logger.info(f"Starting bot on port {port}...")
    
    # Run the bot
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,  # Clear any pending updates
            close_loop=False
        )
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
