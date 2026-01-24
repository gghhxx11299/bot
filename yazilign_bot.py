import os, math, logging, asyncio, gspread
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)

# --- CONFIG & LOGGING ---
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "8322080514"))
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_MAIN")
SHEET_ID = os.getenv("SHEET_ID")
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- DATABASE ENGINE ---
def get_sheet(sheet_name):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = {
            "type": os.getenv("GOOGLE_CREDENTIALS_TYPE"),
            "project_id": os.getenv("GOOGLE_PROJECT_ID"),
            "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
            "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace('\\n', '\n'),
            "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "auth_uri": os.getenv("GOOGLE_AUTH_URI"),
            "token_uri": os.getenv("GOOGLE_TOKEN_URI"),
            "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_X509_CERT_URL"),
            "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL")
        }
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID).worksheet(sheet_name)
    except Exception as e:
        logging.error(f"Sheet Access Error: {e}")
        return None

def sync_data(sheet_name, row_data):
    sheet = get_sheet(sheet_name)
    if sheet: sheet.append_row(row_data)

# --- MATH ---
def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- DATA ---
LOCATIONS = {
    "Addis Ketema": [f"Wereda {i:02d}" for i in [1,3,4,5,6,8,9,10,11,12,13,14]],
    "Akaki Kaliti": [f"Wereda {i:02d}" for i in [1,2,3,4,5,6,7,8,9,10,12,13]],
    "Arada": [f"Wereda {i:02d}" for i in range(1, 11)],
    "Bole": [f"Wereda {i:02d}" for i in [1,2,3,4,5,6,7,9,11,12,13,14]],
    "Gulele": [f"Wereda {i:02d}" for i in range(1, 11)],
    "Kirkos": [f"Wereda {i:02d}" for i in [1,2,3,4,5,7,8,9,10,11]],
    "Kolfe Keranio": [f"Wereda {i:02d}" for i in range(1, 12)],
    "Lideta": [f"Wereda {i:02d}" for i in range(1, 11)],
    "Nifas Silk-Lafto": [f"Wereda {i:02d}" for i in [1,2,5,6,7,8,9,10,11,12,13,15]],
    "Yeka": [f"Wereda {i:02d}" for i in range(1, 13)],
    "Lemi Kura": [f"Wereda {i:02d}" for i in [2,3,4,5,6,8,9,10,13,14]]
}

# --- STATES ---
ROLE, C_REG_NAME, C_REG_PHONE, C_REG_PAY, ORD_BUREAU, ORD_LOC, DEP_SCREEN, W_REG_NAME, W_REG_SUBCITY, W_REG_WEREDA, W_REG_ID_F, W_REG_ID_B, W_REG_SELFIE, W_ARRIVAL = range(14)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["I am a Client / ደንበኛ", "I am a Worker / ሰራተኛ"]]
    await update.message.reply_text("Yazilign / ጻፍልኝ\nSelect Role / ሚና ይምረጡ:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ROLE

# --- WORKER REGISTRATION (Mappings to 'Workers' Table) ---
async def w_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_name'] = update.message.text
    kb = [[s] for s in LOCATIONS.keys()]
    await update.message.reply_text("Select Subcity / ክፍለ ከተማ:", reply_markup=ReplyKeyboardMarkup(kb))
    return W_REG_SUBCITY

async def w_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_subcity'] = update.message.text
    kb = [[w] for w in LOCATIONS[update.message.text]]
    await update.message.reply_text("Select Wereda / ወረዳ:", reply_markup=ReplyKeyboardMarkup(kb))
    return W_REG_WEREDA

async def w_wereda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_wereda'] = update.message.text
    await update.message.reply_text("Upload ID FRONT (Fayda):\nየመታወቂያ ፊት ይላኩ:", reply_markup=ReplyKeyboardRemove())
    return W_REG_ID_F

async def w_id_f(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    path = f"f_{update.effective_user.id}.jpg"
    await file.download_to_drive(path)
    context.user_data['id_f_link'] = path
    await update.message.reply_text("Upload ID BACK:\nየመታወቂያ ጀርባ ይላኩ:")
    return W_REG_ID_B

async def w_id_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    path = f"b_{update.effective_user.id}.jpg"
    await file.download_to_drive(path)
    context.user_data['id_b_link'] = path
    await update.message.reply_text("Upload Selfie:\nሴልፊ ይላኩ:")
    return W_REG_SELFIE

async def w_selfie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    path = f"s_{update.effective_user.id}.jpg"
    await file.download_to_drive(path)
    
    # Save to Workers Table
    sync_data("Workers", [
        update.effective_user.id, context.user_data['w_name'], context.user_data['w_subcity'], 
        context.user_data['w_wereda'], "N/A", "N/A", "N/A", 
        context.user_data['id_f_link'], context.user_data['id_b_link'], path, "Pending Approval", "5.0"
    ])
    
    kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"app_w_{update.effective_user.id}")]]
    await context.bot.send_message(ADMIN_ID, f"New Worker: {context.user_data['w_name']}", reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("Registration sent / ተመዝግቧል።")
    return ConversationHandler.END

# --- CLIENT REG & ORDER (Mappings to 'Users' & 'Orders' Tables) ---
async def c_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_name'] = update.message.text
    await update.message.reply_text("Phone Number / ስልክ ቁጥር:")
    return C_REG_PHONE

async def c_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_phone'] = update.message.text
    await update.message.reply_text("Account Number / የባንክ ቁጥር:")
    return C_REG_PAY

async def c_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Save to Users Table
    sync_data("Users", [
        update.effective_user.id, context.user_data['c_name'], context.user_data['c_phone'],
        datetime.now().strftime("%Y-%m-%d"), "Bank", update.message.text, context.user_data['c_name'], "Active", datetime.now().isoformat()
    ])
    await update.message.reply_text("Enter Bureau/Hospital Name / የቢሮ ስም:")
    return ORD_BUREAU

async def ord_bureau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bureau'] = update.message.text
    kb = [[s] for s in LOCATIONS.keys()]
    await update.message.reply_text("Select Subcity / ክፍለ ከተማ:", reply_markup=ReplyKeyboardMarkup(kb))
    return ORD_LOC

async def ord_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['loc'] = update.message.text
    await update.message.reply_text("Send 100 ETB Deposit Screenshot / የ100 ብር ደረሰኝ ይላኩ:", reply_markup=ReplyKeyboardRemove())
    return DEP_SCREEN

async def dep_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    path = f"dep_{update.effective_user.id}.jpg"
    await file.download_to_drive(path)
    
    # Save to Orders Table
    sync_data("Orders", [
        f"ORD_{update.effective_user.id}", update.effective_user.id, "N/A", 
        context.user_data['bureau'], context.user_data['loc'], "Waiting for Payment", 
        "N/A", path, datetime.now().isoformat(), "N/A", "0", "0", "N/A"
    ])
    
    kb = [[InlineKeyboardButton("✅ Verify Payment", callback_data=f"pay_ok_{update.effective_user.id}")]]
    await context.bot.send_message(ADMIN_ID, f"Deposit: {context.user_data['c_name']}", reply_markup=InlineKeyboardMarkup(kb))
    await update.message.reply_text("Payment under review / ክፍያዎ እየተረጋገጠ ነው።")
    return ConversationHandler.END

# --- SECURITY: GEOFENCING & 72H BAN ---
async def track_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.edited_message if update.edited_message else update.message
    if not msg.location: return
    u_id = update.effective_user.id
    context.bot_data[f"hb_{u_id}"] = datetime.now()
    
    if f"fix_{u_id}" not in context.bot_data:
        context.bot_data[f"fix_{u_id}"] = (msg.location.latitude, msg.location.longitude)
        await context.bot.send_message(u_id, "📍 Geofence Active / መከታተል ተጀምሯል።")
    else:
        lat, lon = context.bot_data[f"fix_{u_id}"]
        if get_distance(lat, lon, msg.location.latitude, msg.location.longitude) > 500:
            await context.bot.send_message(u_id, "🚨 ALERT: >500m Movement! / ⚠️ ከቦታው 500ሜ ርቀዋል!")
            sync_data("History", [datetime.now().isoformat(), "N/A", u_id, "Worker", "Geofence Violation", "Left site >500m"])

async def background_checks(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    # 30-min Location Check
    for k in list(context.bot_data.keys()):
        if k.startswith("hb_"):
            u_id = int(k.split("_")[1])
            if now - context.bot_data[k] > timedelta(minutes=30):
                await context.bot.send_message(u_id, "❌ Job Canceled: GPS Inactive for 30m.")
                del context.bot_data[k]

    # 72-hour Commission Ban Check (Logic to scan Payouts Sheet)
    sheet = get_sheet("Payouts")
    if sheet:
        data = sheet.get_all_records()
        for row in data:
            deadline = datetime.fromisoformat(row['Deadline_72h'])
            if now > deadline and row['Commission_Status'] != "Paid":
                sync_data("Banned", [row['Worker_ID'], "Worker", "72h Commission Unpaid", now.isoformat(), row['Commission_Due'], "None"])
                await context.bot.send_message(row['Worker_ID'], "🚫 BANNED: Unpaid Commission / 🚫 ኮሚሽን ስላልከፈሉ ታግደዋል።")

# --- CALLBACKS ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.data.split("_")[2]
    if "app_w" in query.data:
        await context.bot.send_message(uid, "✅ Registration Approved! / ምዝገባዎ ጸድቋል!")
    if "pay_ok" in query.data:
        await context.bot.send_message(uid, "✅ Payment Verified! Send Arrival Photo at site.\n✅ ክፍያ ተረጋግጧል። ቦታው ሲደርሱ ፎቶ ይላኩ።")

# --- MAIN ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.job_queue.run_repeating(background_checks, interval=300)
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ROLE: [MessageHandler(filters.TEXT, lambda u, c: W_REG_NAME if "Worker" in u.message.text else C_REG_NAME)],
            W_REG_NAME: [MessageHandler(filters.TEXT, w_name)],
            W_REG_SUBCITY: [MessageHandler(filters.TEXT, w_subcity)],
            W_REG_WEREDA: [MessageHandler(filters.TEXT, w_wereda)],
            W_REG_ID_F: [MessageHandler(filters.PHOTO, w_id_f)],
            W_REG_ID_B: [MessageHandler(filters.PHOTO, w_id_b)],
            W_REG_SELFIE: [MessageHandler(filters.PHOTO, w_selfie)],
            C_REG_NAME: [MessageHandler(filters.TEXT, c_name)],
            C_REG_PHONE: [MessageHandler(filters.TEXT, c_phone)],
            C_REG_PAY: [MessageHandler(filters.TEXT, c_pay)],
            ORD_BUREAU: [MessageHandler(filters.TEXT, ord_bureau)],
            ORD_LOC: [MessageHandler(filters.TEXT, ord_loc)],
            DEP_SCREEN: [MessageHandler(filters.PHOTO, dep_screen)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.LOCATION, track_location))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
