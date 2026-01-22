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
# CONFIGURATION FROM ENV
# ======================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_MAIN")
REGISTRATION_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_REGISTRATION")  # Optional
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
WORKER_CHANNEL_ID = int(os.getenv("WORKER_CHANNEL_ID"))
SHEET_ID = os.getenv("SHEET_ID")

# Google Service Account from individual env vars
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

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# User state
USER_STATE = {}

# States
(
    STATE_NONE, STATE_CLIENT_CITY, STATE_CLIENT_BUREAU, STATE_CLIENT_LOCATION,
    STATE_CLIENT_BOOKING_RECEIPT, STATE_CLIENT_FINAL_PAYMENT,
    STATE_WORKER_NAME, STATE_WORKER_PHONE, STATE_WORKER_FYDA,
    STATE_DISPUTE_REASON
) = range(10)

# ======================
# BILINGUAL MESSAGES
# ======================

MESSAGES = {
    "start": {
        "en": "Welcome! Are you a Client, Worker, or Admin?",
        "am": "እንኳን በደህና መጡ! ከላይ ያሉት የስራ ሰራተኛ ወይስ አድሚን ነዎት?"
    },
    "cancel": {
        "en": "↩️ Cancel",
        "am": "↩️ ሰርዝ"
    },
    "choose_city": {
        "en": "📍 Choose city:",
        "am": "📍 ከተማ ይምረጡ፡"
    },
    "city_not_active": {
        "en": "🚧 We’re not operating in {city} yet! Please choose Addis Ababa.",
        "am": "🚧 እስካሁን በ{city} አገልግሎት አልጀመርንም! እባክዎን አዲስ አበባን ይምረጡ።"
    },
    "enter_bureau": {
        "en": "📍 Type the bureau name (e.g., CMC Passport Office):",
        "am": "📍 የቢሮውን ስም ይጥቀሱ (ለምሳሌ፦ ሲኤምሲ ፓስፖርት ቢሮ)፡"
    },
    "send_location": {
        "en": "📍 Please share your live location for meetup:",
        "am": "📍 ለመገናኘት እንዲያመች የቀጥታ መገኛዎን ይላኩ፡"
    },
    "booking_fee": {
        "en": "To confirm, please pay 100 ETB to [CBE Account] and upload the receipt.",
        "am": "ለማረጋገጥ፣ እባክዎን 100 ብር ወደ [CBE Account] ገቢ አድርገው ደረሰኙን ይላኩ።"
    },
    "worker_welcome": {
        "en": "👷 Welcome! Please send your full name:",
        "am": "👷 እንኳን ደህና መጡ! እባክዎን ሙሉ ስምዎን ይላኩ፡"
    },
    "worker_phone": {
        "en": "📱 Please send your phone number:",
        "am": "📱 እባክዎን ስልክ ቁጥርዎን ይላኩ፡"
    },
    "worker_fyda": {
        "en": "📸 Please send FRONT and BACK photos of your Fyda (ID):",
        "am": "📸 እባክዎን የፋይዳ (መታወቂያ) ፊት እና ጀርባ ፎቶ ይላኩ፡"
    },
    "admin_approve_worker": {
        "en": "🆕 New worker registration!\nName: {name}\nPhone: {phone}\nApprove?",
        "am": "🆕 አዲስ የሰራተኛ ምዝገባ!\nስም፡ {name}\nስልክ፡ {phone}\nይፅደቅ?"
    },
    "worker_approved": {
        "en": "✅ Approved! You’ll receive job alerts soon.",
        "am": "✅ ፀድቋል! በቅርቡ የስራ ማስታወቂያ ይደርስዎታል።"
    },
    "worker_declined": {
        "en": "❌ Declined. Contact admin for details.",
        "am": "❌ ውድቅ ተደርጓል። ለተጨማሪ መረጃ አስተዳዳሪውን ያነጋግሩ።"
    },
    "order_created": {
        "en": "✅ Order created! Searching for workers...",
        "am": "✅ ትዕዛዝ ተፈጥሯል! ሰራተኛ እየፈለግን ነው..."
    },
    "job_post": {
        "en": "📍 {bureau}\n🏙️ {city}\n💰 100 ETB/hour\n[Accept]",
        "am": "📍 {bureau}\n🏙️ {city}\n💰 በሰዓት 100 ብር\n[ተቀበል]"
    },
    "worker_accepted": {
        "en": "✅ Worker accepted! They’ll check in soon.",
        "am": "✅ ሰራተኛ ተገኝቷል! በቅርቡ ያገኙዎታል።"
    },
    "final_payment": {
        "en": "💼 Job done! Please pay {amount} ETB to the worker and upload receipt.",
        "am": "💼 ስራ ተጠናቋል! እባክዎን {amount} ብር ለሰራተኛው ከፍለው ደረሰኙን ይላኩ።"
    },
    "payment_complete": {
        "en": "✅ Payment confirmed! Thank you.",
        "am": "✅ ክፍያ ተረጋግጧል! እናመሰግናለን።"
    },
    "commission_request": {
        "en": "💰 You earned {total} ETB! Send 25% ({commission}) to @YourTelegram within 3 hours.",
        "am": "💰 {total} ብር ሰርተዋል! የ25% ኮሚሽን ({commission}) በ3 ሰዓት ውስጥ ለ @YourTelegram ይላኩ።"
    },
    "commission_timeout": {
        "en": "⏰ 1 hour left to send your 25% commission!",
        "am": "⏰ የ25% ኮሚሽን ለመላክ 1 ሰዓት ብቻ ይቀራል!"
    },
    "commission_missed": {
        "en": "🚨 You missed the commission deadline. Contact admin immediately.",
        "am": "🚨 የኮሚሽን መክፈያ ጊዜ አልፏል። በአስቸኳይ አስተዳዳሪውን ያነጋግሩ።"
    },
    "request_new_worker": {
        "en": "🔄 Request New Worker",
        "am": "🔄 ሌላ ሰራተኛ ይፈለግ"
    },
    "reassign_reason": {
        "en": "Why do you want a new worker?",
        "am": "ሌላ ሰራተኛ ለምን ፈለጉ?"
    },
    "worker_reassigned": {
        "en": "🔁 Job reopened. A new worker will be assigned soon.",
        "am": "🔁 ስራው በድጋሚ ክፍት ሆኗል። በቅርቡ ሌላ ሰራተኛ ይመደባል።"
    },
    "dispute_button": {
        "en": "⚠️ Dispute",
        "am": "⚠️ ቅሬታ"
    },
    "dispute_reason": {
        "en": "Select dispute reason:",
        "am": "የቅሬታ ምክንያቱን ይምረጡ፡"
    },
    "reason_no_show": {
        "en": "Worker didn’t show",
        "am": "ሰራተኛው አልመጣም"
    },
    "reason_payment": {
        "en": "Payment issue",
        "am": "የክፍያ ችግር"
    },
    "reason_fake_photo": {
        "en": "Fake photo",
        "am": "ሀሰተኛ ፎቶ"
    },
    "dispute_submitted": {
        "en": "📄 Dispute submitted. Admin will review shortly.",
        "am": "📄 ቅሬታዎ ቀርቧል። አስተዳዳሪው በቅርቡ ይመለከተዋል።"
    },
    "rate_worker": {
        "en": "How would you rate this worker? (1–5 stars)",
        "am": "ለዚህ ሰራተኛ ምን ያህል ኮከብ ይሰጣሉ? (ከ1-5 ኮከቦች)"
    },
    "rating_thanks": {
        "en": "Thank you! Your feedback helps us improve.",
        "am": "እናመሰግናለን! የእርስዎ አስተያየት አገልግሎታችንን ለማሻሻል ይረዳናል።"
    },
    "location_off": {
        "en": "⚠️ Worker’s location is off!",
        "am": "⚠️ የሰራተኛው መገኛ ጠፍቷል!"
    },
    "turn_on_location": {
        "en": "Turn On Location",
        "am": "መገኛን አብራ"
    },
    "location_alert_sent": {
        "en": "🔔 Request sent. Worker will be notified to turn on location.",
        "am": "🔔 ጥያቄ ተልኳል። ሰራተኛው መገኛውን እንዲያበራ መልዕክት ይደርሰዋል።"
    },
    "user_banned": {
        "en": "🚫 You are banned from using Yazilign. Contact admin for details.",
        "am": "🚫 ከያዝልኝ አገልግሎት ታግደዋል። ለዝርዝር መረጃ አስተዳዳሪውን ያነጋግሩ።"
    }
}

def get_msg(key, lang="en", **kwargs):
    text = MESSAGES[key].get(lang, MESSAGES[key]["en"])
    return text.format(**kwargs)

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

def is_user_banned(phone=None, tg_id=None):
    try:
        sheet = get_worksheet("Banned")
        records = sheet.get_all_records()
        for r in records:
            if (phone and r.get("Phone_Number") == phone) or (tg_id and str(r.get("Telegram_ID")) == str(tg_id)):
                return True
    except Exception as e:
        logger.error(f"Ban check error: {e}")
    return False

def ban_user(phone, tg_id, reason=""):
    try:
        sheet = get_worksheet("Banned")
        sheet.append_row([phone, str(tg_id), reason, str(datetime.now())])
    except Exception as e:
        logger.error(f"Ban error: {e}")

# ======================
# COMMISSION TIMER
# ======================

def start_commission_timer(application, order_id, worker_id, total_amount):
    commission = int(total_amount * COMMISSION_PERCENT)
    
    def first_reminder():
        asyncio.run_coroutine_threadsafe(
            application.bot.send_message(
                chat_id=worker_id,
                text=get_msg("commission_timeout", "en")
            ),
            application.updater.dispatcher.loop
        )
    
    def final_alert():
        asyncio.run_coroutine_threadsafe(
            application.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🚨 Commission missed!\nOrder: {order_id}\nWorker: {worker_id}\nAmount: {commission} ETB"
            ),
            application.updater.dispatcher.loop
        )
        # Auto-ban logic can be added here after manual review
    
    Timer(2 * 3600, first_reminder).start()      # 2 hours
    Timer(3 * 3600, final_alert).start()         # 3 hours

# ======================
# TELEGRAM HANDLERS
# ======================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USER_STATE[user_id] = {"state": STATE_NONE, "data": {}, "lang": "en"}  # Default English
    
    keyboard = [["Client", "Worker"]]
    if user_id == ADMIN_CHAT_ID:
        keyboard.append(["Admin"])
    await update.message.reply_text(
        get_msg("start", "en"),
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state_info = USER_STATE.get(user_id, {"state": STATE_NONE, "data": {}, "lang": "en"})
    state = state_info["state"]
    data = state_info["data"]
    lang = state_info["lang"]

    if text == get_msg("cancel", lang):
        await start(update, context)
        return

    if text == "Client":
        USER_STATE[user_id] = {"state": STATE_CLIENT_CITY, "data": {}, "lang": lang}
        keyboard = [[city] for city in ALL_CITIES]
        await update.message.reply_text(
            get_msg("choose_city", lang),
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        )

    elif text == "Worker":
        if is_user_banned(tg_id=user_id):
            await update.message.reply_text(get_msg("user_banned", lang))
            return
        USER_STATE[user_id] = {"state": STATE_WORKER_NAME, "data": {}, "lang": lang}
        await update.message.reply_text(get_msg("worker_welcome", lang))

    elif state == STATE_CLIENT_CITY:
        if text not in ACTIVE_CITIES:
            await update.message.reply_text(get_msg("city_not_active", lang, city=text))
            keyboard = [[city] for city in ALL_CITIES]
            await update.message.reply_text(
                get_msg("choose_city", lang),
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
            )
            return
        data["city"] = text
        USER_STATE[user_id] = {"state": STATE_CLIENT_BUREAU, "data": data, "lang": lang}
        await update.message.reply_text(get_msg("enter_bureau", lang))

    elif state == STATE_CLIENT_BUREAU:
        data["bureau"] = text
        USER_STATE[user_id] = {"state": STATE_CLIENT_LOCATION, "data": data, "lang": lang}
        await update.message.reply_text(
            get_msg("send_location", lang),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Share Live Location", request_location=True)]],
                one_time_keyboard=True
            )
        )

    elif state == STATE_WORKER_NAME:
        data["name"] = text
        USER_STATE[user_id] = {"state": STATE_WORKER_PHONE, "data": data, "lang": lang}
        await update.message.reply_text(get_msg("worker_phone", lang))

    elif state == STATE_WORKER_PHONE:
        data["phone"] = text
        if is_user_banned(phone=text):
            await update.message.reply_text(get_msg("user_banned", lang))
            return
        USER_STATE[user_id] = {"state": STATE_WORKER_FYDA, "data": data, "lang": lang}
        await update.message.reply_text(get_msg("worker_fyda", lang))

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state_info = USER_STATE.get(user_id, {})
    state = state_info.get("state", STATE_NONE)
    data = state_info.get("data", {})
    lang = state_info.get("lang", "en")

    if state == STATE_WORKER_FYDA:
        photos = update.message.photo
        data["fyda_front"] = photos[-1].file_id
        data["fyda_back"] = photos[-2].file_id if len(photos) >= 2 else None
        USER_STATE[user_id]["data"] = data

        try:
            sheet = get_worksheet("Workers")
            sheet.append_row([
                str(uuid4())[:8], data["name"], data["phone"], str(user_id),
                "", "0", "Pending"
            ])
        except Exception as e:
            logger.error(f"Worker save error: {e}")

        caption = get_msg("admin_approve_worker", "en", name=data["name"], phone=data["phone"])
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=data["fyda_front"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}")],
                [InlineKeyboardButton("❌ Decline", callback_data=f"decline_{user_id}")]
            ])
        )
        if data["fyda_back"]:
            await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=data["fyda_back"])

        await update.message.reply_text("📄 Sent to admin.", reply_markup=ReplyKeyboardMarkup([[get_msg("cancel", lang)]]))

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state_info = USER_STATE.get(user_id, {})
    state = state_info.get("state", STATE_NONE)
    data = state_info.get("data", {})
    lang = state_info.get("lang", "en")

    if state == STATE_CLIENT_LOCATION:
        data["location"] = (update.message.location.latitude, update.message.location.longitude)
        order_id = f"YZL-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:4].upper()}"
        
        try:
            sheet = get_worksheet("Orders")
            sheet.append_row([
                order_id, str(datetime.now()), str(user_id),
                data["bureau"], data["city"], "Booking Paid", "",
                "1", str(HOURLY_RATE), "Yes", "0", "Booking Paid"
            ])
        except Exception as e:
            logger.error(f"Order create error: {e}")

        await update.message.reply_text(get_msg("booking_fee", lang))
        USER_STATE[user_id] = {"state": STATE_CLIENT_BOOKING_RECEIPT, "data": data, "lang": lang}

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    lang = "en"  # Admin uses English

    if data == "cancel":
        USER_STATE[user_id] = {"state": STATE_NONE, "data": {}, "lang": "en"}
        await query.message.reply_text("Cancelled.")

    elif data.startswith("approve_"):
        worker_tg_id = int(data.split("_")[1])
        try:
            sheet = get_worksheet("Workers")
            records = sheet.get_all_records()
            for i, record in enumerate(records, start=2):
                if str(record.get("Telegram_ID")) == str(worker_tg_id):
                    sheet.update_cell(i, 7, "Active")
                    break
        except Exception as e:
            logger.error(f"Approve error: {e}")
        await context.bot.send_message(chat_id=worker_tg_id, text=get_msg("worker_approved", "en"))
        await query.edit_message_caption(caption="✅ Approved!")

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
        await context.bot.send_message(chat_id=worker_tg_id, text=get_msg("worker_declined", "en"))
        await query.edit_message_caption(caption="❌ Declined.")

# ======================
# FLASK / HEALTH
# ======================

flask_app = Flask(__name__)

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok", "uptime": "running"})

# ======================
# MAIN
# ======================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=port)).start()

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
