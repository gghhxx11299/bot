import os, math, logging, asyncio, gspread
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)

# --- CONFIG & LOGGING ---
ADMIN_ID = int(os.getenv("ADMIN_CHAT_ID", "8322080514"))
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_MAIN")
SHEET_ID = os.getenv("SHEET_ID")
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

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
    except Exception as e: logging.error(f"Sync Error: {e}")

# --- LOCATIONS DATA ---
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
ROLE, C_NAME, C_PAY, ORD_BUREAU, ORD_LOC, DEP_SCREEN, W_NAME, W_SUBCITY, W_WEREDA, W_ID_F, W_ID_B, W_SELFIE = range(12)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [["I am a Client / ደንበኛ", "I am a Worker / ሰራተኛ"]]
    await update.message.reply_text("Yazilign / ጻፍልኝ\nSelect Role / ሚና ይምረጡ:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ROLE

async def handle_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if "Worker" in choice:
        await update.message.reply_text("Full Name / ሙሉ ስም:")
        return W_NAME
    else:
        await update.message.reply_text("Full Name / ሙሉ ስም:")
        return C_NAME

# --- CLIENT ORDER FLOW ---
async def c_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_name'] = update.message.text
    await update.message.reply_text("Telebirr/Bank Info:\nየቴሌብር ወይም የባንክ መረጃ:")
    return C_PAY

async def c_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['c_pay'] = update.message.text
    await update.message.reply_text("Enter Bureau/Hospital Name:\nየቢሮ ወይም የሆስፒታል ስም ያስገቡ:")
    return ORD_BUREAU

async def ord_bureau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bureau'] = update.message.text
    kb = [[s] for s in LOCATIONS.keys()]
    await update.message.reply_text("Select Subcity / ክፍለ ከተማ ይምረጡ:", reply_markup=ReplyKeyboardMarkup(kb))
    return ORD_LOC

async def ord_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['loc'] = update.message.text
    await update.message.reply_text("Send 100 ETB Deposit & Upload Screenshot:\n100 ብር ቅድመ ክፍያ ይክፈሉ እና ደረሰኝ ይላኩ:", reply_markup=ReplyKeyboardRemove())
    return DEP_SCREEN

async def dep_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    path = f"dep_{update.effective_user.id}.jpg"
    await file.download_to_drive(path)
    
    kb = [[InlineKeyboardButton("✅ Verify Payment", callback_data=f"pay_ok_{update.effective_user.id}")]]
    await context.bot.send_message(ADMIN_ID, f"Deposit: {context.user_data['c_name']}\nBureau: {context.user_data['bureau']}", reply_markup=InlineKeyboardMarkup(kb))
    await context.bot.send_photo(ADMIN_ID, open(path, 'rb'))
    
    sync_data("Orders", [update.effective_user.id, context.user_data['c_name'], context.user_data['bureau'], context.user_data['loc'], "Pending Payment"])
    await update.message.reply_text("Payment under review. / ክፍያዎ እየተረጋገጠ ነው።")
    return ConversationHandler.END

# --- WORKER REG FLOW ---
async def w_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_name'] = update.message.text
    kb = [[s] for s in LOCATIONS.keys()]
    await update.message.reply_text("Select Subcity / ክፍለ ከተማ:", reply_markup=ReplyKeyboardMarkup(kb))
    return W_SUBCITY

async def w_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_subcity'] = update.message.text
    kb = [[w] for w in LOCATIONS[update.message.text]]
    await update.message.reply_text("Select Wereda / ወረዳ:", reply_markup=ReplyKeyboardMarkup(kb))
    return W_WEREDA

async def w_wereda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['w_wereda'] = update.message.text
    await update.message.reply_text("Upload ID FRONT (Fayda):\nየመታወቂያ ፊት ይላኩ:", reply_markup=ReplyKeyboardRemove())
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
    await update.message.reply_text("Upload Selfie / ሴልፊ ይላኩ:")
    return W_SELFIE

async def w_selfie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.photo[-1].get_file()
    path = f"s_{update.effective_user.id}.jpg"
    await file.download_to_drive(path)
    
    kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"app_w_{update.effective_user.id}")]]
    await context.bot.send_message(ADMIN_ID, f"New Worker: {context.user_data['w_name']}", reply_markup=InlineKeyboardMarkup(kb))
    await context.bot.send_photo(ADMIN_ID, open(context.user_data['id_f'], 'rb'))
    await context.bot.send_photo(ADMIN_ID, open(context.user_data['id_b'], 'rb'))
    await context.bot.send_photo(ADMIN_ID, open(path, 'rb'))
    
    sync_data("Workers", [update.effective_user.id, context.user_data['w_name'], context.user_data['w_subcity'], "Pending Approval"])
    await update.message.reply_text("Sent for approval. / ተልኳል።")
    return ConversationHandler.END

# --- CALLBACK HANDLER ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("app_w_"):
        uid = query.data.split("_")[2]
        await context.bot.send_message(uid, "✅ Approved! / ጸድቋል!")
        await query.edit_message_text("Worker Approved ✅")
    if query.data.startswith("pay_ok_"):
        uid = query.data.split("_")[2]
        await context.bot.send_message(uid, "✅ Payment Verified! / ክፍያ ተረጋግጧል!")
        await query.edit_message_text("Payment Verified ✅")

# --- MAIN ---
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ROLE: [MessageHandler(filters.TEXT, handle_role)],
            C_NAME: [MessageHandler(filters.TEXT, c_name)],
            C_PAY: [MessageHandler(filters.TEXT, c_pay)],
            ORD_BUREAU: [MessageHandler(filters.TEXT, ord_bureau)],
            ORD_LOC: [MessageHandler(filters.TEXT, ord_loc)],
            DEP_SCREEN: [MessageHandler(filters.PHOTO, dep_screen)],
            W_NAME: [MessageHandler(filters.TEXT, w_name)],
            W_SUBCITY: [MessageHandler(filters.TEXT, w_subcity)],
            W_WEREDA: [MessageHandler(filters.TEXT, w_wereda)],
            W_ID_F: [MessageHandler(filters.PHOTO, w_id_f)],
            W_ID_B: [MessageHandler(filters.PHOTO, w_id_b)],
            W_SELFIE: [MessageHandler(filters.PHOTO, w_selfie)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
