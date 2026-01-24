import os, math, logging, asyncio, gspread
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- ENV CONFIG ---
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "8322080514"))
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_MAIN")
SHEET_ID = os.getenv("SHEET_ID")

# --- DATABASE SYNC ---
def sync_data(sheet_name, row_data):
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
        sheet = client.open_by_key(SHEET_ID).worksheet(sheet_name)
        sheet.append_row(row_data)
    except Exception as e:
        logging.error(f"Sync Error: {e}")

# --- 122 WEREDA DATA ---
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

# --- GEOLOCATION CALC ---
def get_distance(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- STATES ---
ROLE, W_REG, W_SUBCITY, W_WEREDA, W_ID_F, W_ID_B, W_SELFIE = range(7)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["I am a Client / ደንበኛ", "I am a Worker / ሰራተኛ"]]
    text = "Welcome to Yazilign! Select your role:\nእንኳን ወደ ጻፍልኝ በደህና መጡ! ሚናዎን ይምረጡ:"
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ROLE

async def handle_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "Worker" in update.message.text:
        await update.message.reply_text("Enter Full Name (Matches Bank):\nሙሉ ስምዎን ያስገቡ:")
        return W_REG
    await update.message.reply_text("Client module coming soon.")
    return ConversationHandler.END

async def w_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_name'] = update.message.text
    kb = [[s] for s in LOCATIONS.keys()]
    await update.message.reply_text("Select Subcity / ክፍለ ከተማ:", reply_markup=ReplyKeyboardMarkup(kb))
    return W_SUBCITY

async def w_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_subcity'] = update.message.text
    kb = [[w] for w in LOCATIONS[update.message.text]]
    await update.message.reply_text("Select Wereda / ወረዳ:", reply_markup=ReplyKeyboardMarkup(kb))
    return W_WEREDA

async def w_reg_wereda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_wereda'] = update.message.text
    await update.message.reply_text("Upload ID FRONT / የመታወቂያ ፊት:", reply_markup=ReplyKeyboardRemove())
    return W_ID_F

async def w_id_f(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    path = f"f_{update.effective_user.id}.jpg"
    await file.download_to_drive(path)
    context.user_data['id_f'] = path
    await update.message.reply_text("Upload ID BACK / የመታወቂያ ጀርባ:")
    return W_ID_B

async def w_id_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    path = f"b_{update.effective_user.id}.jpg"
    await file.download_to_drive(path)
    context.user_data['id_b'] = path
    await update.message.reply_text("Upload Selfie / ፎቶዎን ይላኩ:")
    return W_SELFIE

async def w_selfie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    path = f"s_{update.effective_user.id}.jpg"
    await file.download_to_drive(path)
    
    # Send to Admin for Approval
    await context.bot.send_message(ADMIN_ID, f"New Worker Approval:\nName: {context.user_data['w_name']}")
    await context.bot.send_photo(ADMIN_ID, open(context.user_data['id_f'], 'rb'))
    await context.bot.send_photo(ADMIN_ID, open(context.user_data['id_b'], 'rb'))
    await context.bot.send_photo(ADMIN_ID, open(path, 'rb'))
    
    sync_data("Workers", [update.effective_user.id, context.user_data['w_name'], context.user_data['w_subcity'], "Pending"])
    await update.message.reply_text("Registration sent! / ተመዝግቧል።")
    return ConversationHandler.END

# --- GEOFENCE & 30-MIN TIMER ---
async def location_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.edited_message if update.edited_message else update.message
    if not msg.location: return
    u_id = update.effective_user.id
    context.bot_data[f"hb_{u_id}"] = datetime.now()
    
    if f"fix_{u_id}" in context.bot_data:
        lat, lon = context.bot_data[f"fix_{u_id}"]
        if get_distance(lat, lon, msg.location.latitude, msg.location.longitude) > 500:
            await context.bot.send_message(u_id, "⚠️ WARNING: You left the site! / ⚠️ ቦታውን ለቀው ወጥተዋል!")

async def monitor_jobs(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    for k in list(context.bot_data.keys()):
        if k.startswith("hb_"):
            u_id = k.split("_")[1]
            if now - context.bot_data[k] > timedelta(minutes=30):
                await context.bot.send_message(u_id, "❌ Disconnected. Job Canceled. / ❌ ግንኙነት ተቋርጧል ስራው ተሰርዟል።")

# --- MAIN ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    if app.job_queue:
        app.job_queue.run_repeating(monitor_jobs, interval=300)

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ROLE: [MessageHandler(filters.TEXT, handle_role)],
            W_REG: [MessageHandler(filters.TEXT, w_reg_name)],
            W_SUBCITY: [MessageHandler(filters.TEXT, w_reg_subcity)],
            W_WEREDA: [MessageHandler(filters.TEXT, w_reg_wereda)],
            W_ID_F: [MessageHandler(filters.PHOTO, w_id_f)],
            W_ID_B: [MessageHandler(filters.PHOTO, w_id_b)],
            W_SELFIE: [MessageHandler(filters.PHOTO, w_selfie)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.LOCATION, location_update))
    app.run_polling()

if __name__ == "__main__":
    main()
