import os
import logging
from datetime import datetime, timedelta
from threading import Timer
from uuid import uuid4

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
from flask import Flask, jsonify
import asyncio

# ======================
# CONFIGURATION
# ======================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_MAIN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
WORKER_CHANNEL_ID = int(os.getenv("WORKER_CHANNEL_ID"))
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

HOURLY_RATE = 100
COMMISSION_PERCENT = 0.25
COMMISSION_TIMEOUT_HOURS = 3

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
STATE_WORKER_BANK_TYPE = 10
STATE_WORKER_ACCOUNT_NUMBER = 11
STATE_WORKER_ACCOUNT_HOLDER = 12
STATE_WORKER_FYDA_FRONT = 13
STATE_WORKER_FYDA_BACK = 14
STATE_WORKER_CHECKIN_PHOTO = 15
STATE_WORKER_CHECKIN_LOCATION = 16
STATE_DISPUTE_REASON = 17
STATE_RATING = 18
STATE_CLIENT_MONITORING = 19

# ======================
# MESSAGES
# ======================

MESSAGES = {
    "start": {"en": "Welcome! Are you a Client, Worker, or Admin?", "am": "እንኳን በደህና መጡ!"},
    "cancel": {"en": "↩️ Cancel", "am": "↩️ ሰርዝ"},
    "choose_city": {"en": "📍 Choose city:", "am": "📍 ከተማ ይምረጡ፡"},
    "city_not_active": {"en": "🚧 Not in {city} yet. Choose Addis Ababa.", "am": "🚧 በ{city} አይሰራም። አዲስ አበባ ይምረጡ።"},
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
    "user_banned": {"en": "🚫 You are banned from using Yazilign. Contact admin for details.", "am": "🚫 ከያዝልኝ አገልግሎት ታግደዋል። ለዝርዝር መረጃ አስተዳዳሪውን ያነጋግሩ።"}
}

def get_msg(key, **kwargs):
    en_text = MESSAGES[key].get("en", "")
    am_text = MESSAGES[key].get("am", "")
    if kwargs:
        en_text = en_text.format(**kwargs)
        am_text = am_text.format(**kwargs)
    return f"{en_text}\n{am_text}"

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

    # 📜 LEGAL WELCOME MESSAGE
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

    # Ensure user exists
    get_or_create_user(user_id, first_name, username)

    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return

    text = update.message.text
    state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}})
    state = state_info["state"]
    data = state_info["data"]

    if text == "↩️ Cancel" or text == "↩️ ሰርዝ":
        await start(update, context)
        return

    if text == "Client":
        USER_STATE[user_id] = {"state": STATE_CLIENT_CITY, "data": {}}
        keyboard = [[city] for city in ALL_CITIES]
        await update.message.reply_text(
            get_msg("choose_city"),
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        )

    elif text == "Worker":
        if is_user_banned(user_id):
            await update.message.reply_text(get_msg("user_banned"))
            return
        USER_STATE[user_id] = {"state": STATE_WORKER_NAME, "data": {}}
        await update.message.reply_text(get_msg("worker_welcome"))

    elif state == STATE_CLIENT_CITY:
        if text not in ACTIVE_CITIES:
            await update.message.reply_text(get_msg("city_not_active", city=text))
            keyboard = [[city] for city in ALL_CITIES]
            await update.message.reply_text(
                get_msg("choose_city"),
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            )
            return
        data["city"] = text
        USER_STATE[user_id] = {"state": STATE_CLIENT_BUREAU, "data": data}
        await update.message.reply_text(get_msg("enter_bureau"))

    elif state == STATE_CLIENT_BUREAU:
        data["bureau"] = text
        USER_STATE[user_id] = {"state": STATE_CLIENT_LOCATION, "data": data}
        await update.message.reply_text(
            get_msg("send_location"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Share Live Location", request_location=True)]],
                one_time_keyboard=True
            )
        )

    elif state == STATE_WORKER_NAME:
        data["name"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_PHONE, "data": data}
        await update.message.reply_text(get_msg("worker_phone"))

    elif state == STATE_WORKER_PHONE:
        data["phone"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_TELEBIRR, "data": data}
        await update.message.reply_text("📱 Enter your Telebirr number:\n📱 የቴሌቢር ቁጥርዎን ይፃፉ፡")

    elif state == STATE_WORKER_TELEBIRR:
        data["telebirr"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_BANK_TYPE, "data": data}
        await update.message.reply_text("🏦 Enter your bank type (e.g., CBE, Awash, Dashen):\n🏦 የባንክ አይነትዎን ይፃፉ (ለምሳሌ፡ CBE, Awash, Dashen):")

    elif state == STATE_WORKER_BANK_TYPE:
        data["bank_type"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_ACCOUNT_NUMBER, "data": data}
        await update.message.reply_text("🔢 Enter your account number:\n🔢 የአካውንት ቁጥርዎን ይፃፉ፡")

    elif state == STATE_WORKER_ACCOUNT_NUMBER:
        data["account_number"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_ACCOUNT_HOLDER, "data": data}
        await update.message.reply_text("👤 Enter your account holder name (as on bank):\n👤 የአካውንት ባለቤት ስም (በባንክ የሚታየው)")

    elif state == STATE_WORKER_ACCOUNT_HOLDER:
        data["account_holder"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA_FRONT, "data": data}
        await update.message.reply_text(get_msg("worker_fyda_front"))

    elif state == STATE_CLIENT_FINAL_HOURS:
        try:
            hours = int(text)
            if 1 <= hours <= 12:
                data["hours"] = hours
                total = HOURLY_RATE * hours
                data["total"] = total
                USER_STATE[user_id] = {"state": STATE_CLIENT_FINAL_RECEIPT, "data": data}
                await update.message.reply_text(get_msg("final_payment", amount=total - 100))
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

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "User"
    username = user.username

    # Ensure user exists
    get_or_create_user(user_id, first_name, username)

    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return

    state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}})
    state = state_info["state"]
    data = state_info["data"]

    if state == STATE_WORKER_FYDA_FRONT:
        data["fyda_front"] = update.message.photo[-1].file_id
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA_BACK, "data": data}
        await update.message.reply_text(get_msg("worker_fyda_back"))

    elif state == STATE_WORKER_FYDA_BACK:
        data["fyda_back"] = update.message.photo[-1].file_id
        USER_STATE[user_id]["data"] = data

        worker_id = str(uuid4())[:8]
        try:
            sheet = get_worksheet("Workers")
            sheet.append_row([
                worker_id,
                data["name"],
                data["phone"],
                str(user_id),  # 👈 TELEGRAM USER ID SAVED HERE
                "0",  # Rating
                "0",  # Total_Earnings
                "Pending",
                data.get("telebirr", ""),
                data.get("bank_type", ""),
                data.get("account_number", ""),
                data.get("account_holder", "")
            ])
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
                    [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{worker_id}")],
                    [InlineKeyboardButton("❌ Decline", callback_data=f"decline_{user_id}")]
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
        await update.message.reply_text(get_msg("rate_worker"))

    elif state == STATE_WORKER_CHECKIN_PHOTO:
        data["checkin_photo"] = update.message.photo[-1].file_id
        USER_STATE[user_id] = {"state": STATE_WORKER_CHECKIN_LOCATION, "data": data}
        await update.message.reply_text(get_msg("checkin_location"))

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "User"
    username = user.username

    # Ensure user exists
    get_or_create_user(user_id, first_name, username)

    if is_user_banned(user_id):
        await update.message.reply_text(get_msg("user_banned"))
        return

    state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}})
    state = state_info["state"]
    data = state_info["data"]

    if not update.message:
        return

    if not update.message.location:
        await update.message.reply_text("📍 Please share a valid live location.\n📍 የሚሰራ የቀጥታ መገኛ ያጋሩ።")
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
                "Pending"
            ])
        except Exception as e:
            logger.error(f"Order create error: {e}")
            await update.message.reply_text("⚠️ Failed to create order. Try again.\n⚠️ ትዕዛዝ ማድረግ አልተሳካም።")
            return

        await update.message.reply_text(
            "✅ Order created! Searching for workers...\n✅ ትዕዛዝ ተፈጸመ! ሠራተኞች ተፈልተዋል..."
        )

        await context.bot.send_message(
            chat_id=WORKER_CHANNEL_ID,
            text=get_msg("job_post", bureau=data["bureau"], city=data["city"], rate=HOURLY_RATE),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Accept", callback_data=f"accept_{order_id}_{user_id}")]
            ])
        )

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
                    break
        except Exception as e:
            logger.error(f"Check-in update error: {e}")

        await update.message.reply_text(get_msg("checkin_complete"))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    first_name = user.first_name or "User"
    username = user.username

    # Ensure user exists
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
        worker_tg_id = int(parts[1])
        try:
            sheet = get_worksheet("Workers")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if str(record.get("Telegram_ID")) == str(worker_tg_id):
                    sheet.update_cell(i, 7, "Active")
                    break
        except Exception as e:
            logger.error(f"Approve error: {e}")
        await context.bot.send_message(chat_id=worker_tg_id, text=get_msg("worker_approved"))
        await query.edit_message_caption(caption="✅ Approved!\n✅ ተፈቅዶልናል!")

    elif data.startswith("decline_"):
        worker_tg_id = int(data.split("_")[1])
        try:
            sheet = get_worksheet("Workers")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if str(record.get("Telegram_ID")) == str(worker_tg_id):
                    sheet.update_cell(i, 7, "Declined")
                    break
        except Exception as e:
            logger.error(f"Decline error: {e}")
        await context.bot.send_message(chat_id=worker_tg_id, text=get_msg("worker_declined"))
        await query.edit_message_caption(caption="❌ Declined.\n❌ ተውግዷል።")

    elif data.startswith("accept_"):
        parts = data.split("_")
        order_id = parts[1]
        client_id = parts[2]
        try:
            sheet = get_worksheet("Orders")
            records = sheet.get_all_records()
            order = None
            for record in records:
                if record.get("Order_ID") == order_id and record.get("Status") == "Pending":
                    order = record
                    break
            if order:
                row_idx = records.index(order) + 2
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
                    
                    # Save worker ID to client state
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
                    sheet.update_cell(i, 10, "Yes")  # Booking_Fee_Paid
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
# FLASK / HEALTH
# ======================

flask_app = Flask(__name__)

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok"})

# ======================
# MAIN
# ======================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    from threading import Thread
    Thread(target=lambda: flask_app.run(host="0.0.0.0", port=port)).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    application.add_handler(CallbackQueryHandler(handle_callback))

    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{webhook_url}/{BOT_TOKEN}"
        )
    else:
        application.run_polling()
