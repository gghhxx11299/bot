import asyncio
import logging
import gspread
import re
import time
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler
)
# Using Google Auth instead of oauth2client for better stability with service accounts
from google.oauth2.service_account import Credentials

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
TOKEN_MAIN = os.getenv("TELEGRAM_BOT_TOKEN_MAIN", "8280641086:AAGnCKDcmugoMHBG_IVEFkFcHFFA-HdCylk")
TOKEN_REG = os.getenv("TELEGRAM_BOT_TOKEN_REGISTRATION", "8460866208:AAEtlMSE3XqWELE7Fmrk_mR-PQ-5aA2d6Bw")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "8322080514"))
WORKER_CHANNEL_ID = int(os.getenv("WORKER_CHANNEL_ID", "-100123456789"))
SHEET_ID = os.getenv("SHEET_ID", "1SqbFIXim9fVjXQJ8_7ICgBNamCTiYzbTd4DcnVvffv4")

# Load Google credentials from environment variables
GCP_CREDENTIALS = {
    "type": os.getenv("GOOGLE_CREDENTIALS_TYPE", "service_account"),
    "project_id": os.getenv("GOOGLE_PROJECT_ID", "genial-shore-480106-i8"),
    "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID", "4b574c48f39a8e2b8a0ae1228dab9485d0ea455e"),
    "private_key": os.getenv("GOOGLE_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDDOhKl3XIr74ZR\nk/GliLeEHukiKgt2d7UiUZTrphpR9XoClY8jq8+MsG3viMWyv8URgQilBPg57H0d\nG5LNYf2P23nuqjtDdPdBDuuyu+2aYxQfYa5Rqj3MqnW1QjP+975fIcPNYqgWkFoi\nUVea9JWvKT6ZeXsAt1JWGpNOv24lNgDr37TQbE1eQocces7LE/NEGyLjGwlYOl2p\nKy3PsivwXTOmsqYjP3dAyEdntS9+E9PmGiysl8dP+WRvxXC6R8KAix+lI4dE+r3E\nFEa+7JQlb/hIbgfkoQhFoEjqtySN+Anjcp7ehFRkV3xQSVXmOGO4UeTuIbVFF5lT\n8pClnymrAgMBAAECggEAC5yWo1rqgYZ7nLqJ8uiQ0cDs6OVLTT6NfX8QtntosVtC\naIjwvJRpgdq0jzy5VYpmdEYSd442HWvdfS+4qZKcfEP3mqRxZe+9DReQGU9oMHiY\nJ82tipnvlw7EdYV8hjvCDPJ7LOojSURIuCXSahsGFCcF3CcHk+FTel+WR2bHbFsR\nUgxOEr0zETtadUwyWCwLruqDD/UANQvUudomlyVitFNR/7un3IfjOe7x2t4JBLaz\nwRw4fEQp70+UAsWvOSY1TIrceCvqiNQF7zcwGYpuLi4o4MRsHdvmxPpKBytwIFJ8\nWIpANoggAzX3Pz+O6MrgztnOHV6uuaX9cFg/24npMQKBgQDoL2v8Xx0QArUPtIO2\nJAfcQg/N42TKW7q+BT/zXXf3dr3O7MUFicSxlnZbuiUVcfkTy8yfD+v5vThjnzBi\npZi+CA1Be+dTEJR/X5AWVxHKENgvKSbbDH16PcvPztrtcw6nGwSJ4avoxP0g0DZz\nsSYbuSpnpHF4D1snVEviVzbaTwKBgQDXQDhXs20Rlwa46B6GThkaXCMbkYFuy18Q\nW+G9+R/x5mDZjt5JPWuNMmMCi4z09SL+oyuxC1skKsHV+MuQt/0Cc31oRdgRvgRW\nnGXCz/rbYOJ0NadDz9zY+S5AAeNat3Chw2ZIbN0+nP12nCEwuzFv8dkCqWPJmccD\nYWVBbnjP5QKBgQDdpwfLsXEpK6x2BboHU3Y9isNTpdU+aTto09ItHfm8wBqLQ/UC\nSHcBocXz40wroNZLU69P2f9INp9yWzHxumyKXV1qOkKnRZi90BjZet18rX/z5bE2\nREI1RHEhPTQ6ojBGzsAScOGQIR4VCTAyWdcreCVHM/Eu0FoQvaSDuwaeeQKBgCo2\n8RXaHZjmiq328A2dAXVW/peoiL7m6cT2kCZG1ooFiZcBWvz4K8CsUhisr79W2D8i\nVy5IsN49+HfzbFD8lIVHix/JGuAX6RfnYlm7mlIuBRuPbjdxa7mt3PE2rZUcBt3i\nyYuItjdSaK87XZMGE2MGBm5sNCLUouA52LblaJI1AoGAQHAnbFwg5P8kPZJaZAI+\nau16rgRq2Kz27zXQunXIqcTFKk2ntM8m4GnmazgftI3JkCRI7K+7VzaQM8TqTo+3\nF5/RGAEnmSDw2GvgcpAnjjoUnj4WSad2IgB9mPZ/6gRfAqdz8P3lOfDdZz6bfO7C\nfFi3c6J00gk123sDLZAr0KU=\n-----END PRIVATE KEY-----\n"),
    "client_email": os.getenv("GOOGLE_CLIENT_EMAIL", "streamlit-manager@genial-shore-480106-i8.iam.gserviceaccount.com"),
    "client_id": os.getenv("GOOGLE_CLIENT_ID", "110751734401818551433"),
    "auth_uri": os.getenv("GOOGLE_AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
    "token_uri": os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
    "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_X509_CERT_URL", "https://www.googleapis.com/oauth2/v1/certs"),
    "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL", "https://www.googleapis.com/robot/v1/metadata/x509/streamlit-manager%40genial-shore-480106-i8.iam.gserviceaccount.com"),
}

GCP_CREDENTIALS["private_key"] = GCP_CREDENTIALS["private_key"].replace("\\n", "\n")

# ================= GOOGLE SHEETS =================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets", 
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_info(GCP_CREDENTIALS, scopes=SCOPES)
gc = gspread.authorize(creds)
S_ORDERS = gc.open_by_key(SHEET_ID).worksheet("Orders")
S_WORKERS = gc.open_by_key(SHEET_ID).worksheet("Workers")

# ================= BOT STATES =================
LEGAL, NAME, PHONE, ID_FRONT, ID_BACK, SELFIE = range(6)
BUREAU, CLIENT_LOC = 1, 2

class YazilignBotSystem:
    def __init__(self):
        # Initialize both bots
        self.main_app = Application.builder().token(TOKEN_MAIN).build()
        self.reg_app = Application.builder().token(TOKEN_REG).build()
        
        # Set up conversation handlers
        self.setup_main_bot_handlers()
        self.setup_reg_bot_handlers()

    def setup_main_bot_handlers(self):
        """Setup handlers for the main bot"""
        # Add conversation handler for order creation
        order_conv = ConversationHandler(
            entry_points=[CommandHandler("order", self.order_start)],
            states={
                BUREAU: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.bureau_rec)],
                CLIENT_LOC: [MessageHandler(filters.LOCATION, self.loc_rec)]
            },
            fallbacks=[]
        )
        self.main_app.add_handler(order_conv)

        # Add other handlers
        self.main_app.add_handler(MessageHandler(filters.PHOTO, self.payment_rec))
        self.main_app.add_handler(CallbackQueryHandler(self.handle_accept, "^a_"))
        self.main_app.add_handler(CallbackQueryHandler(self.admin_verify_pay, "^vp_"))
        self.main_app.add_handler(CommandHandler("start", self.start))

    def setup_reg_bot_handlers(self):
        """Setup handlers for the registration bot"""
        # Create conversation handler
        reg_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("Register / ተመዝገብ"), self.begin_reg)],
            states={
                LEGAL: [MessageHandler(filters.Regex("I Agree / ተስማምቻለሁ"), self.get_legal)],
                NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_name)],
                PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_phone)],
                ID_FRONT: [MessageHandler(filters.PHOTO, self.get_id_front)],
                ID_BACK: [MessageHandler(filters.PHOTO, self.get_id_back)],
                SELFIE: [MessageHandler(filters.PHOTO, self.finish)],
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel), 
                CommandHandler("start", self.start_reg)
            ],
        )
        
        self.reg_app.add_handler(CommandHandler("start", self.start_reg))
        self.reg_app.add_handler(MessageHandler(filters.Regex("Check Status / ሁኔታዬን አሳይ"), self.status_check))
        self.reg_app.add_handler(reg_conv)

    # ============= MAIN BOT HANDLERS =============
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = (
            "👋 Welcome! / እንኳን መጡ!\n\n"
            "1. Request first. / መጀመሪያ ይጠይቁ።\n"
            "2. Worker accepts. / ሰራተኛው ይቀበላል።\n"
            "3. Pay only after worker is ready. / ሰራተኛው ሲዘጋጅ ብቻ ይከፍላሉ።\n\n"
            "Use /order to start. / ለመጀመር /order ይጠቀሙ"
        )
        await update.message.reply_text(msg)

    async def order_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🏢 Bureau Name? / የቢሮው ስም?")
        return BUREAU

    async def bureau_rec(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['bureau'] = update.message.text
        await update.message.reply_text("📍 Please send your Live Location. / እባክዎን የቀጥታ ቦታዎን (Live Location) ይላኩ።")
        return CLIENT_LOC

    async def loc_rec(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message.location: 
            return CLIENT_LOC
        oid = f"YAZ-{int(time.time()) % 100000}"

        # Save to Sheets
        S_ORDERS.append_row([oid, datetime.now().isoformat(), update.effective_user.id, context.user_data['bureau'], "WAITING"])

        # Notify Workers
        kbd = [[InlineKeyboardButton("Accept / ተቀበል", callback_data=f"a_{oid}")]]
        await context.bot.send_message(WORKER_CHANNEL_ID, f"🆕 JOB: {oid}\nAt: {context.user_data['bureau']}", reply_markup=InlineKeyboardMarkup(kbd))

        await update.message.reply_text("🔎 Searching... We will notify you when a worker accepts.\nፈልጋ ላይ ነን... ሰራተኛ ሲገኝ እናሳውቆታለን።")
        return ConversationHandler.END

    async def handle_accept(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        oid = query.data[2:]
        wid = query.from_user.id

        cell = S_ORDERS.find(oid)
        # Check if still waiting
        if S_ORDERS.cell(cell.row, 5).value != "WAITING":
            await query.answer("Taken! / ተወስዷል!")
            return

        S_ORDERS.update_cell(cell.row, 5, "ACCEPTED")
        S_ORDERS.update_cell(cell.row, 6, wid)

        uid = S_ORDERS.cell(cell.row, 3).value
        # Ask Client for Payment
        await context.bot.send_message(uid, f"✅ A worker accepted! Please send your payment receipt to start.\nሰራተኛ ተገኝቷል! ለመጀመር እባክዎን የክፍያ ማረጋገጫ ይላኩ።")
        await query.edit_message_text(f"✅ Accepted {oid}. Waiting for client payment.")

    async def payment_rec(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message.photo: 
            return

        # Find the order for this user
        all_data = S_ORDERS.get_all_values()
        row = next((r for r in all_data if r[2] == str(update.effective_user.id) and r[4] == "ACCEPTED"), None)

        if row:
            oid = row[0]
            kbd = [[InlineKeyboardButton("Verify Pay ✅", callback_data=f"vp_{oid}")]]
            await context.bot.send_photo(ADMIN_CHAT_ID, update.message.photo[-1].file_id, caption=f"💰 Payment for {oid}", reply_markup=InlineKeyboardMarkup(kbd))
            await update.message.reply_text("⏳ Verifying payment... / ክፍያውን እያረጋገጥን ነው።")

    async def admin_verify_pay(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        oid = update.callback_query.data[3:]
        cell = S_ORDERS.find(oid)
        uid = S_ORDERS.cell(cell.row, 3).value
        wid = S_ORDERS.cell(cell.row, 6).value

        S_ORDERS.update_cell(cell.row, 5, "PAID")
        await update.callback_query.edit_message_caption("✅ Verified")

        # Both parties exchange location
        await context.bot.send_message(uid, "✅ Paid! Sharing your location with worker. / ተከፍሏል! አድራሻዎ ለሰራተኛው እየተላከ ነው።")
        await context.bot.send_message(wid, "✅ Paid! Go to client. / ተከፍሏል! ወደ ዲንበኛው ይሂዱ።")

    # ============= REGISTRATION BOT HANDLERS =============
    async def start_reg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = ReplyKeyboardMarkup([
            ["Register / ተመዝገብ"], 
            ["Check Status / ሁኔታዬን አሳይ"]
        ], resize_keyboard=True)
        await update.message.reply_text(
            "👋 Yazilign Worker Registration Bot / የያዝልኝ ሰራተኛ መመዝገቢያ ቦት", 
            reply_markup=keyboard
        )
        return ConversationHandler.END

    async def status_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = str(update.effective_user.id)
        rows = S_WORKERS.get_all_values()
        
        for row in rows:
            if len(row) >= 7 and row[6] == tg_id:
                worker_id = row[0]
                status = row[5].upper()
                if status == "ACTIVE" or status == "APPROVED":
                    await update.message.reply_text(
                        f"🎉 **Approved! / ጸድቋል!**\n\nYour Worker ID: `{worker_id}`\nYou can now start working.\nአሁን ስራ መጀመር ይችላሉ።",
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(
                        f"⏳ Current Status: {status}\nVerification in progress. / ማረጋገጫ በመከናወን ላይ ነው።"
                    )
                return
        
        await update.message.reply_text("❌ Not registered / አልተመዘገቡም")

    async def begin_reg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        legal_text = (
            "⚖️ **Legal Agreement / ህጋዊ ስምምነት**\n\n"
            "1. All information provided is accurate.\n"
            "2. The assigned Worker ID serves as professional proof for future claims.\n"
            "መረጃው ትክክል መሆኑን እና የተሰጠኝ መለያ ቁጥር (ID) ለወደፊት ህጋዊ ጉዳዮች እንደ ማስረጃ እንደሚያገለግል አውቃለሁ።\n\n"
            "Do you agree? / ትስማማለህ?"
        )
        keyboard = ReplyKeyboardMarkup(
            [["I Agree / ተስማምቻለሁ"]], 
            resize_keyboard=True, 
            one_time_keyboard=True
        )
        await update.message.reply_text(
            legal_text, 
            reply_markup=keyboard, 
            parse_mode="Markdown"
        )
        return LEGAL

    async def get_legal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "👤 Full Name / ሙሉ ስም:", 
            reply_markup=ReplyKeyboardRemove()
        )
        return NAME

    async def get_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["name"] = update.message.text
        await update.message.reply_text("📱 Phone (09/07):")
        return PHONE

    async def get_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        phone = update.message.text
        if not re.match(r"^(09|07)\d{8}$", phone):
            await update.message.reply_text("❌ Invalid / የተሳሳተ ቁጥር")
            return PHONE

        # Check for Duplicate Phone Number
        try:
            phone_list = S_WORKERS.col_values(3)  # Column C is Phone
            if phone in phone_list:
                await update.message.reply_text(
                    "❌ This phone number is already registered.\nይህ ስልክ ቁጥር ቀድሞ ተመዝግቧል።\n\nPlease check your status.",
                    reply_markup=ReplyKeyboardMarkup(
                        [["Check Status / ሁኔታዬን አሳይ"]], 
                        resize_keyboard=True
                    )
                )
                return ConversationHandler.END
        except Exception as e:
            # If there's an error accessing the sheet, continue anyway
            logging.warning(f"Could not check for duplicate phone numbers: {e}")

        context.user_data["phone"] = phone
        await update.message.reply_text("📸 Fayda FRONT / የፊት ገጽ ፎቶ:")
        return ID_FRONT

    async def get_id_front(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message.photo:
            await update.message.reply_text("Please send a photo.")
            return ID_FRONT
        context.user_data["id_front"] = update.message.photo[-1].file_id
        await update.message.reply_text("📸 Fayda BACK / የጀርባ ገጽ ፎቶ:")
        return ID_BACK

    async def get_id_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message.photo:
            await update.message.reply_text("Please send a photo.")
            return ID_BACK
        context.user_data["id_back"] = update.message.photo[-1].file_id
        await update.message.reply_text("📸 Selfie / የእርስዎ ፎቶ:")
        return SELFIE

    async def finish(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message.photo:
            await update.message.reply_text("Please send a photo.")
            return SELFIE

        selfie = update.message.photo[-1].file_id
        tg_id = str(update.effective_user.id)
        assigned_id = f"YZ-{int(time.time()) % 1000000}"

        try:
            # Add worker to sheet with PENDING status
            S_WORKERS.append_row([
                assigned_id, 
                context.user_data["name"], 
                context.user_data["phone"], 
                "0",  # Total Earnings
                "0",  # Ratings
                "PENDING",  # Status
                tg_id  # Telegram ID
            ])
        except Exception as e:
            logging.error(f"Error adding worker to sheet: {e}")
            await update.message.reply_text("❌ Error registering. Please try again later.")
            return ConversationHandler.END

        # Admin Alert
        try:
            msg = (
                f"🚨 NEW REGISTRATION\n"
                f"ID: {assigned_id}\n"
                f"Name: {context.user_data['name']}\n"
                f"Phone: {context.user_data['phone']}"
            )
            await context.bot.send_message(ADMIN_CHAT_ID, msg)
            await context.bot.send_photo(ADMIN_CHAT_ID, context.user_data["id_front"], caption="Front ID")
            await context.bot.send_photo(ADMIN_CHAT_ID, context.user_data["id_back"], caption="Back ID")
            await context.bot.send_photo(ADMIN_CHAT_ID, selfie, caption="Selfie")
        except Exception as e:
            logging.error(f"Error sending admin notification: {e}")

        await update.message.reply_text(
            f"✅ **Registration Complete! / ምዝገባው ተጠናቅቋል!**\n\n"
            f"Your ID: `{assigned_id}`\n\n"
            "Please wait **24 hours** for your account to be activated.\n"
            "እባክዎን አካውንትዎ እስኪነቃ ድረስ **24 ሰዓት** ይጠብቁ።",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    async def run(self):
        """Run both bots concurrently"""
        print("Starting Yazilign Bot System...")
        print("Both main bot and registration bot will start simultaneously.")
        
        # Run both bots concurrently using polling
        await asyncio.gather(
            self.main_app.run_polling(drop_pending_updates=True, allowed_updates=['message', 'callback_query', 'inline_query']),
            self.reg_app.run_polling(drop_pending_updates=True, allowed_updates=['message', 'callback_query', 'inline_query'])
        )

def main():
    """Main function to run the combined bot system"""
    # Check if required environment variables are set
    if not os.getenv("TELEGRAM_BOT_TOKEN_MAIN"):
        print("Warning: TELEGRAM_BOT_TOKEN_MAIN environment variable not set.")
        print("Using default value. Please set it for production.")
    
    if not os.getenv("TELEGRAM_BOT_TOKEN_REGISTRATION"):
        print("Warning: TELEGRAM_BOT_TOKEN_REGISTRATION environment variable not set.")
        print("Using default value. Please set it for production.")
    
    if not os.getenv("ADMIN_CHAT_ID"):
        print("Warning: ADMIN_CHAT_ID environment variable not set.")
        print("Using default value. Please set it for production.")
    
    # Create and run the bot system
    bot_system = YazilignBotSystem()
    
    try:
        asyncio.run(bot_system.run())
    except KeyboardInterrupt:
        print("\nYazilign Bot System stopped by user.")
    except Exception as e:
        print(f"\nError running Yazilign Bot System: {e}")

if __name__ == '__main__':
    main()