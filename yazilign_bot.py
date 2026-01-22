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
# USER STATES (FIXED - NO UNPACKING)
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
STATE_WORKER_FYDA = 9
STATE_WORKER_CHECKIN_PHOTO = 10
STATE_WORKER_CHECKIN_LOCATION = 11
STATE_DISPUTE_REASON = 12
STATE_RATING = 13
STATE_CLIENT_MONITORING = 14

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
    "worker_fyda": {"en": "📸 Send FRONT & BACK of Fyda:", "am": "📸 ፊዳዎን ገጽ እና ወለድ ያስገቡ:"},
    "admin_approve_worker": {"en": "🆕 New worker!\nName: {name}\nPhone: {phone}\nApprove?", "am": "🆕 አዲስ ሠራተኛ!\nስም: {name}\nስልክ: {phone}"},
    "worker_approved": {"en": "✅ Approved!", "am": "✅ ተፈቅዶልናል!"},
    "worker_declined": {"en": "❌ Declined.", "am": "❌ ተውግዷል።"},
    "order_created": {"en": "✅ Order created! Searching for workers...", "am": "✅ ትዕዛዝ ተፈጸመ!"},
    "job_post": {"en": "📍 {bureau}\n🏙️ {city}\n💰 {rate} ETB/hour\n[Accept]", "am": "📍 {bureau}\n🏙️ {city}\n💰 {rate} ብር/ሰዓት\n[ቀበል]"},
    "worker_accepted": {"en": "✅ Worker accepted! They’ll check in soon.", "am": "✅ ሠራተኛ ተቀብሏል!"},
    "checkin_photo": {"en": "📸 Send photo of yourself in line at {bureau}", "am": "📸 በ{bureau} ውስጥ ያለውን ፎቶ ይላኩ"},
    "checkin_location": {"en": "📍 Start live location sharing now", "am": "📍 አሁን የቀጥታ መገኛ ያጋሩ"},
    "checkin_complete": {"en": "✅ Check-in complete! Client notified.", "am": "✅ የመግቢያ ሂደት ተጠናቅቋል!"},
    "location_off_alert": {"en": "⚠️ Worker’s location is off!", "am": "⚠️ የሰራተኛው መገኛ ጠፍቷል!"},
    "turn_on_location": {"en": "Turn On Location", "am": "መገኛ አብራ"},
    "location_alert_sent": {"en": "🔔 Request sent.", "am": "🔔 ጥያቄ ተልኳል።"},
    "final_hours": {"en": "How many hours did the worker wait? (Min 1, Max 12)", "am": "ሰራተኛው ስንት ሰዓት ጠብቷል? (ከ1-12)"},
    "final_payment": {"en": "💼 Pay {amount} ETB to worker and upload receipt.", "am": "💼 ለሰራተኛ {amount} ብር ይላክሱ እና ሲምበር ያስገቡ።"},
    "payment_complete": {"en": "✅ Payment confirmed! Thank you.", "am": "✅ ክፍያ ተረጋግጧል! እናመሰግናለን።"},
    "commission_request": {"en": "💰 Send 25% ({commission}) within 3 hours.", "am": "💰 25% ({commission}) በ3 ሰዓት ውስጥ ይላክሱ።"},
    "commission_timeout": {"en": "⏰ 1 hour left!", "am": "⏰ 1 ሰዓት ብቻ ይቀራል!"},
    "commission_missed": {"en": "🚨 Missed deadline. Contact admin.", "am": "🚨 ጊዜ አልፏል። አስተዳዳሪ ያነጋግሩ።"},
    "request_new_worker": {"en": "🔄 Request New Worker", "am": "🔄 ሌላ ሰራተኛ ይፈለግ"},
    "reassign_reason": {"en": "Why new worker?", "am": "ለምን ሌላ ሰራተኛ?"},
    "worker_reassigned": {"en": "🔁 Job reopened.", "am": "🔁 ስራ በድጋሚ ክፍት ሆኗል።"},
    "dispute_button": {"en": "⚠️ Dispute", "am": "⚠️ ቅሬታ"},
    "dispute_reason": {"en": "Select reason:", "am": "ምክንያት ይምረጡ:"},
    "reason_no_show": {"en": "Worker didn’t show", "am": "ሰራተኛ አልመጣም"},
    "reason_payment": {"en": "Payment issue", "am": "የክፍያ ችግር"},
    "reason_fake_photo": {"en": "Fake photo", "am": "ሀሰተኛ ፎቶ"},
    "dispute_submitted": {"en": "📄 Dispute submitted.", "am": "📄 ቅሬታ ቀርቧል።"},
    "rate_worker": {"en": "Rate worker (1–5 stars):", "am": "ኮከብ ይሰጡ (1-5):"},
    "rating_thanks": {"en": "Thank you!", "am": "እናመሰግናለን!"},
    "user_banned": {"en": "🚫 Banned.", "am": "🚫 ታግደዋል።"}
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
        ban_user(phone="unknown", tg_id=worker_id, reason="Missed commission")
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
    user_id = update.effective_user.id
    USER_STATE[user_id] = {"state": STATE_NONE, "data": {}, "lang": "en"}
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

    elif state == STATE_CLIENT_FINAL_HOURS:
        try:
            hours = int(text)
            if 1 <= hours <= 12:
                data["hours"] = hours
                total = HOURLY_RATE * hours
                data["total"] = total
                USER_STATE[user_id] = {"state": STATE_CLIENT_FINAL_RECEIPT, "data": data, "lang": lang}
                await update.message.reply_text(get_msg("final_payment", lang, amount=total - 100))
            else:
                await update.message.reply_text(get_msg("final_hours", lang))
        except ValueError:
            await update.message.reply_text(get_msg("final_hours", lang))

    elif state == STATE_RATING:
        try:
            rating = int(text)
            if 1 <= rating <= 5:
                update_worker_rating(data["worker_id"], rating)
                await update.message.reply_text(get_msg("rating_thanks", lang))
                await start(update, context)
            else:
                await update.message.reply_text(get_msg("rate_worker", lang))
        except ValueError:
            await update.message.reply_text(get_msg("rate_worker", lang))

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

        worker_id = str(uuid4())[:8]
        try:
            sheet = get_worksheet("Workers")
            sheet.append_row([
                worker_id, data["name"], data["phone"], str(user_id),
                "0", "0", "Pending"
            ])
        except Exception as e:
            logger.error(f"Worker save error: {e}")

        caption = get_msg("admin_approve_worker", "en", name=data["name"], phone=data["phone"])
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=data["fyda_front"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{worker_id}")],
                [InlineKeyboardButton("❌ Decline", callback_data=f"decline_{user_id}")]
            ])
        )
        if data["fyda_back"]:
            await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=data["fyda_back"])

        await update.message.reply_text("📄 Sent to admin.")

    elif state == STATE_CLIENT_BOOKING_RECEIPT:
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

        await context.bot.send_message(
            chat_id=WORKER_CHANNEL_ID,
            text=get_msg("job_post", "en", bureau=data["bureau"], city=data["city"], rate=HOURLY_RATE),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Accept", callback_data=f"accept_{order_id}_{user_id}")]])
        )
        await update.message.reply_text(get_msg("order_created", lang))

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
            text=get_msg("commission_request", "en", total=total, commission=commission)
        )
        start_commission_timer(context.application, data["order_id"], worker_id, total)

        USER_STATE[user_id] = {"state": STATE_RATING, "data": {"worker_id": worker_id}, "lang": lang}
        await update.message.reply_text(get_msg("rate_worker", lang))

    elif state == STATE_WORKER_CHECKIN_PHOTO:
        data["checkin_photo"] = update.message.photo[-1].file_id
        USER_STATE[user_id] = {"state": STATE_WORKER_CHECKIN_LOCATION, "data": data, "lang": "en"}
        await update.message.reply_text(get_msg("checkin_location", "en"))

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state_info = USER_STATE.get(user_id, {})
    state = state_info.get("state", STATE_NONE)
    data = state_info.get("data", {})

    if state == STATE_CLIENT_LOCATION:
        data["location"] = (update.message.location.latitude, update.message.location.longitude)
        USER_STATE[user_id]["data"] = data
        await update.message.reply_text(get_msg("booking_fee", "en"))

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
                            text="✅ Worker checked in! Live location active."
                        ),
                        context.application.updater.dispatcher.loop
                    )
                    break
        except Exception as e:
            logger.error(f"Check-in update error: {e})

        await update.message.reply_text(get_msg("checkin_complete", "en"))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    lang = "en"

    if data == "cancel":
        USER_STATE[user_id] = {"state": STATE_NONE, "data": {}, "lang": "en"}
        await query.message.reply_text("Cancelled.")

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

    elif data.startswith("accept_"):
        parts = data.split("_")
        order_id = parts[1]
        client_id = parts[2]
        try:
            sheet = get_worksheet("Orders")
            records = sheet.get_all_records()
            order = None
            for record in records:
                if record.get("Order_ID") == order_id and record.get("Status") == "Booking Paid":
                    order = record
                    break
            if order:
                row_idx = records.index(order) + 2
                sheet.update_cell(row_idx, 7, str(user_id))
                sheet.update_cell(row_idx, 6, "Assigned")

                await context.bot.send_message(
                    chat_id=int(client_id),
                    text=get_msg("worker_accepted", "en")
                )

                bureau = order["Bureau_Name"]
                USER_STATE[user_id] = {
                    "state": STATE_WORKER_CHECKIN_PHOTO,
                    "data": {"order_id": order_id, "bureau": bureau},
                    "lang": "en"
                }
                await context.bot.send_message(
                    chat_id=user_id,
                    text=get_msg("checkin_photo", "en", bureau=bureau)
                )
        except Exception as e:
            logger.error(f"Accept error: {e}")

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
                            text="🔔 Client requested live location. Please turn it on now."
                        )
                        await query.message.reply_text(get_msg("location_alert_sent", "en"))
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
