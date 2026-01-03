import logging
import os
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
import re
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json  # Added for parsing JSON credentials from env

# --- BILINGUAL SYSTEM PROMPT (for reference only) ---
SYSTEM_PROMPT = """
You are the FineData Assistant for an Ethiopian startup selling premium laser-engraved NFC business cards.
Respond in English or Amharic based on user's language preference.
- Price: 1,200 ETB (1-4 cards), 1,100 ETB (5-9 cards), 1,000 ETB (10+ cards).
- Key Feature: One-tap digital contact sharing via NFC.
- Payment: CBE (1000728253499 - Geabral) or Telebirr (0960375738 - Gabriel).
- Delivery: 200 ETB anywhere in Addis Ababa; outside Ethiopia upon request (call 0960375738).
- Location: Addis Ababa.
Be professional. Keep answers short and helpful.
Respond in same language as user query.
"""

# --- BILINGUAL DESIGN SPECIFICATIONS ---
DESIGN_GUIDELINES_EN = """
📋 **Design Guidelines for NFC Business Cards**
**Required Specifications:**
• **Format:** PNG or JPG (transparent background preferred)
• **Dimensions:** 3.5 × 2 inches (1050 × 600 pixels)
• **Resolution:** 300 DPI minimum
• **Color Mode:** CMYK for best printing results
• **Safe Zone:** Keep critical content 0.125" from edges
**Design Options:**
✓ Upload your own design
✓ Use our template
✓ Connect with a designer (if you have an idea but haven't made it yet)
Upload your front design now, or type 'skip' to use our template.
"""

DESIGN_GUIDELINES_AM = """
📋 **የኤንኤፍሲ ቢዝነስ ካርዶች ዲዛይን መመሪያዎች**
**የሚፈለጉ ዝርዝሮች:**
• **ፎርማት:** PNG ወይም JPG (ባዶ በስተጀርባ የተዘጋጀ)
• **ልኬቶች:** 3.5 × 2 ኢንች (1050 × 600 ፒክሰል)
• **ጥራት:** ደቂቃ 300 DPI
• **የቀለም ሞድ:** ለመስተጋብር CMYK ይጠቀሙ
• **ደህንነት ቦታ:** አስፈላጊ ነገሮችን ከጫፍ 0.125" አርቀው ያስቀምጡ
**የዲዛይን አማራጮች:**
✓ የራስዎን ዲዛይን ይጫኑ
✓ የእኛን ቅጥ ይጠቀሙ
✓ ከዲዛይነር ጋር ይገናኙ (ሃሳብ ካለዎት ግን ካላደረጉት)
የፊት ለፊት ዲዛይንዎን ይጫኑ ወይም 'ዝለል' ይተይቡ እኛን ቅጥ ለመጠቀም።
"""

# --- PRICING INFO ---
PRICING_EN = """
💰 **Pricing for NFC Business Cards**
**Price Breakdown:**
• 1-4 cards: 1,200 ETB each
• 5-9 cards: 1,100 ETB each
• 10+ cards: 1,000 ETB each
**Delivery:**
• 200 ETB in Addis Ababa
• Outside Ethiopia upon request (call 0960375738)
"""

PRICING_AM = """
💰 **የኤንኤፍሲ ቢዝነስ ካርዶች ዋጋ**
**የዋጋ ዝርዝር:**
• 1-4 ካርዶች: 1,200 ብር እያንዳንዱ
• 5-9 ካርዶች: 1,100 ብር እያንዳንዱ
• 10+ ካርዶች: 1,000 ብር እያንዳንዱ
**ማስረከቢያ:**
• በአዲስ አበባ ውስጥ 200 ብር
• ከኢትዮጵያ ውጭ በጠይቅ ላይ (0960375738 ይደውሉ)
"""

# --- HOW IT WORKS INFO ---
HOW_IT_WORKS_EN = """
ℹ️ **How It Works**
**Step 1: Order**
• Click "Order" and specify quantity
• Upload your design or use our template
**Step 2: Design**
• We'll send design proof within 24 hours
• Approve or request changes
**Step 3: Payment**
• You'll be contacted with payment details
• Service team will handle payment confirmation
**Step 4: Production**
• Cards are printed and NFC chips programmed
• Quality check completed
**Step 5: Delivery**
• 200 ETB delivery in Addis Ababa
• Outside Ethiopia upon request (call 0960375738)
"""

HOW_IT_WORKS_AM = """
ℹ️ **እንዴት ይሰራል**
**ደረጃ 1: ትዕዛዝ**
• "ይዘዙ" ይጫኑ እና ብዛት ይግለጹ
• ዲዛይንዎን ይጫኑ ወይም እኛን ቅጥ ይጠቀሙ
**ደረጃ 2: ዲዛይን**
• በ24 ሰዓት ውስጥ የዲዛይን ማረጋገጫ እናስገባለን
• ያረጋግጡ ወይም ለውጦች ይጠይቁ
**ደረጃ 3: ክፍያ**
• ከክፍያ ዝርዝሮች ጋር እናግኝዎታለን
• የአገልግሎት ቡድን የክፍያ ማረጋገጫ ያስተናግዳል
**ደረጃ 4: ምርት**
• ካርዶቹ ተሰብስባሉ እና ኤንኤፍሲ ቻይፎች ይቀመጣሉ
• የጥራት ማረጋገጫ ተፈጽሟል
**ደረጃ 5: ማስረከቢያ**
• በአዲስ አበባ ውስጥ 200 ብር ማስረከቢያ
• ከኢትዮጵያ ውጭ በጠይቅ ላይ (0960375738 ይደውሉ)
"""

# --- BILINGUAL MESSAGES ---
MESSAGES = {
    'welcome': {
        'en': "Welcome to FineData NFC Cards!",
        'am': "ወደ ፋይንዳታ ኤንኤፍሲ ካርዶች እንኳን በደህና መጡ!"
    },
    'order_start': {
        'en': "Starting new order: `{order_id}`\nHow many NFC cards would you like?",
        'am': "አዲስ ትዕዛዝ በመጀመር ላይ: `{order_id}`\nስንት ኤንኤፍሲ ካርዶች ይፈልጋሉ?"
    },
    'invalid_number': {
        'en': "Please enter a valid number. How many cards?",
        'am': "እባክዎ ትክክለኛ ቁጥር ያስገቡ። ስንት ካርዶች ይፈልጋሉ?"
    },
    'price_breakdown': {
        'en': "**Price Breakdown:**\n• {qty} cards × {unit_price} ETB = {total} ETB\n",
        'am': "**የዋጋ ዝርዝር:**\n• {qty} ካርዶች × {unit_price} ብር = {total} ብር\n"
    },
    'tip_small': {
        'en': "💡 **Tip:** Order 5+ cards to get 1,100 ETB each!",
        'am': "💡 **መመሪያ:** 5 ወይም ከዚያ በላይ ካርዶች ብታዘዙ እያንዳንዱ 1,100 ብር ይሆናል!"
    },
    'tip_medium': {
        'en': "💡 **Tip:** Order 10+ cards to get 1,000 ETB each!",
        'am': "💡 **መመሪያ:** 10 ወይም ከዚያ በላይ ካርዶች ብታዘዙ እያንዳንዱ 1,000 ብር ይሆናል!"
    },
    'confirm_order': {
        'en': "Total: *{total} ETB*\nProceed with this order?",
        'am': "ጠቅላላ: *{total} ብር*\nበዚህ ትዕዛዝ መቀጠል ይፈልጋሉ?"
    },
    'order_cancelled': {
        'en': "Order cancelled.",
        'am': "ትዕዛዙ ተሰርዟል።"
    },
    'enter_name': {
        'en': "Now enter your full name for the cards (in English):",
        'am': "አሁን ለካርዶቹ ሙሉ ስምዎን ያስገቡ (በእንግሊዝኛ):"
    },
    'name_saved': {
        'en': "Name saved: {name}\nNow please enter your phone number for order updates:",
        'am': "ስምዎ ተቀብሏል፡ {name}\nአሁን ለትዕዛዝ ዝርዝሮች ስልክ ቁጥርዎን ያስገቡ:"
    },
    'invalid_phone': {
        'en': "Please enter a valid Ethiopian phone number (e.g., 0912345678):",
        'am': "እባክዎ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር ያስገቡ (ለምሳሌ፡ 0912345678):"
    },
    'order_confirmation': {
        'en': """📋 **ORDER CONFIRMATION** `{order_id}`
**Order Details:**
• Name: {name}
• Phone: {phone}
• Quantity: {quantity} cards
• Total: {total} ETB
**Designs:**
• Front: {front_type}
• Back: {back_type}
**Next Steps:**
1. Our service team will contact you within 1 hour
2. Design proof will be sent within 24 hours
3. Production starts after design approval
Use /status to check order progress anytime.
""",
        'am': """📋 **የትዕዛዝ ማረጋገጫ** `{order_id}`
**ዝርዝሮች:**
• ስም: {name}
• ስልክ: {phone}
• ብዛት: {quantity} ካርዶች
• ጠቅላላ: {total} ብር
**ዲዛይኖች:**
• ፊት: {front_type}
• ጀርባ: {back_type}
**ቀጣይ ደረጃዎች:**
1. የአገልግሎት ቡድናችን በ1 ሰዓት ውስጥ እናግኝዎታለን
2. የዲዛይን ማረጋገጫ በ24 ሰዓት ውስጥ ይላካል
3. ዲዛይን ከተጸድቀ በኋላ ምርት ይጀምራል
ሁነታ ለመመልከት /status ይጠቀሙ።
"""
    },
    'order_submitted': {
        'en': """✅ **ORDER SUBMITTED SUCCESSFULLY!**
Your order `{order_id}` has been received.
**What happens next:**
1. 📞 Our service team will contact you within 1 hour
2. 🎨 You'll receive a design proof within 24 hours
3. ⚡ Production starts after design approval
4. 📦 Delivery in 3-5 business days
**Order Summary:**
• Items: {quantity} NFC Business Cards
• Total: {total} ETB
• Status: Awaiting Contact
**Our team will handle everything manually:**
• Design consultation if needed
• Payment arrangements
• Delivery coordination
**Delivery Options:**
• 200 ETB anywhere in Addis Ababa
• Outside Ethiopia upon request (call 0960375738)
Thank you for choosing FineData NFC Cards!
Our service team will be in touch with you soon.
""",
        'am': """✅ **ትዕዛዎ በተሳካ ሁኔታ ተቀብሏል!**
የእርስዎ ትዕዛዝ `{order_id}` ተቀብሏል።
**ቀጣይ ደረጃ:**
1. 📞 የአገልግሎት ቡድናችን በ1 ሰዓት ውስጥ እናግኝዎታለን
2. 🎨 የዲዛይን ማረጋገጫ በ24 ሰዓት ውስጥ ይላካል
3. ⚡ ዲዛይን ከተጸድቀ በኋላ ምርት ይጀምራል
4. 📦 ማስረከቢያ በ3-5 የስራ ቀናት
**አጠቃላይ ዝርዝር:**
• ዕቃዎች: {quantity} ኤንኤፍሲ ቢዝነስ ካርዶች
• ጠቅላላ: {total} ብር
• ሁኔታ: በመገናኘት ላይ
**ቡድናችን ሁሉንም ነገር በአግባቡ ያስተናግዳል:**
• የዲዛይን ምክር ከፈለጉ
• የክፍያ ማደራጀት
• የማስረከቢያ አሰጣጥ
**የማስረከቢያ አማራጮች:**
• በአዲስ አበባ ውስጥ ሁሉ ቦታ - 200 ብር
• ከኢትዮጵያ ውጭ በጠይቅ ላይ (0960375738 ይደውሉ)
የፋይንዳታ ኤንኤፍሲ ካርዶች ስለመረጡ እናመሰግናለን!
የአገልግሎት ቡድናችን በቅርብ ጊዜ እናግኝዎታለን።
"""
    },
    'status_not_found': {
        'en': "Order ID `{order_id}` not found. Please check the ID and try again.",
        'am': "ትዕዛዝ መታወቂያ `{order_id}` አልተገኘም። እባክዎ መታወቂያውን ያረጋግጡ እና እንደገና ይሞክሩ።"
    }
}

# --- CONFIG (from environment variables) ---
TOKEN = os.getenv("BOT_TOKEN")
MY_ADMIN_ID = os.getenv("ADMIN_ID")
if not TOKEN or not MY_ADMIN_ID:
    raise ValueError("Missing required environment variables: BOT_TOKEN, ADMIN_ID")

# --- STATES ---
QUANTITY, AGREEMENT, FRONT_IMAGE, BACK_IMAGE, USER_NAME, CONTACT_INFO, DESIGN_CONFIRM = range(7)
SUPPORT_DESC, SUPPORT_PHONE = range(8, 10)
CHECK_STATUS_ID = 10  # New state for checking status

# --- HELPERS ---
def get_message(key, **kwargs):
    # Always return both English and Amharic
    en_msg = MESSAGES.get(key, {}).get('en', '')
    am_msg = MESSAGES.get(key, {}).get('am', '')
    if kwargs:
        en_msg = en_msg.format(**kwargs)
        am_msg = am_msg.format(**kwargs)
    return f"{en_msg}\n\n{am_msg}"

def calculate_price(qty):
    if qty >= 10:
        return qty * 1000
    if qty >= 5:
        return qty * 1100
    return qty * 1200

def validate_phone(phone):
    eth_pattern = r'^(09\d{8}|\+2519\d{8}|2519\d{8}|9\d{8})$'
    return bool(re.match(eth_pattern, str(phone)))

def generate_order_id():
    return f"FD-{datetime.now().strftime('%Y%m%d%H%M%S')}"

# --- MODIFIED GOOGLE SHEETS FUNCTION ---
def save_to_google_sheets(order_data):
    try:
        # 1. Get the credentials JSON string from environment variable
        creds_json_str = os.getenv("GOOGLE_SHEETS_CREDENTIALS") # Use the name you set in your platform
        if not creds_json_str:
            logging.error("GSHEET ERROR: Environment variable 'GOOGLE_SHEETS_CREDENTIALS' not found.")
            return False

        # 2. Parse the JSON string into a Python dictionary
        try:
            creds_info = json.loads(creds_json_str)
        except json.JSONDecodeError as e:
            logging.error(f"GSHEET ERROR: Failed to parse credentials JSON: {e}")
            return False

        # 3. Define the required scope
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        # 4. Create credentials object directly from the dictionary
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)

        # 5. Authorize the gspread client
        client = gspread.authorize(creds)

        # 6. Open the specific Google Sheet using its URL
        spreadsheet_url = "https://docs.google.com/spreadsheets/d/1SqbFIXim9fVjXQJ8_7ICgBNamCTiYzbTd4DcnVvffv4/edit"
        sheet = client.open_by_url(spreadsheet_url).sheet1 # Opens the first sheet

        # 7. Prepare the new row data matching your EXACT spreadsheet columns:
        # Name	Contact	Qty	money	Stage	Total	Biker	Order Time	Order_ID	Paid	Called	Exported
        new_row = [
            order_data.get('full_name', ''),           # Name
            order_data.get('phone', ''),               # Contact
            order_data.get('quantity', 0),             # Qty
            order_data.get('total_price', 0),          # money
            "Pending",                                 # Stage
            order_data.get('total_price', 0),          # Total
            "Unassigned",                              # Biker
            datetime.now().strftime('%Y-%m-%d %H:%M'), # Order Time
            order_data.get('order_id', ''),            # Order_ID
            "No",                                      # Paid
            "No",                                      # Called
            "No"                                       # Exported
        ]

        # 8. Append the new row to the sheet
        sheet.append_row(new_row)
        logging.info(f"Successfully saved order {order_data.get('order_id', 'N/A')} to Google Sheets.")
        return True

    except gspread.exceptions.APIError as e:
        # Handle specific Google Sheets API errors
        logging.error(f"GSHEET API ERROR: {e.response.status_code} - {e.response.json()}")
        return False
    except Exception as e:
        # Handle any other errors
        logging.error(f"GSHEET ERROR: {e}")
        return False

# --- STATUS CHECK FUNCTION ---
def check_order_status_in_sheet(order_id):
    try:
        # 1. Access the secret directly from Streamlit's secrets (Matches your Render setup)
        creds_json_str = st.secrets["GCP_JSON"]
        
        if not creds_json_str:
            logging.error("GSHEET ERROR: Secret 'GCP_JSON' not found.")
            return None

        # 2. Setup Credentials and Client
        creds_info = json.loads(creds_json_str)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)

        # 3. Open the Spreadsheet
        spreadsheet_url = "https://docs.google.com/spreadsheets/d/1SqbFIXim9fVjXQJ8_7ICgBNamCTiYzbTd4DcnVvffv4/edit"
        sheet = client.open_by_url(spreadsheet_url).sheet1 

        # 4. Get all data as a list of dictionaries
        # This maps Column headers (Row 1) to values (Row 2, 3...)
        records = sheet.get_all_records()

        # 5. Search for the specific Order_ID
        for row in records:
            # Convert both to string to ensure a match (e.g., "1001" == "1001")
            if str(row.get('Order_ID')).strip() == str(order_id).strip():
                return {
                    'stage': row.get('Stage', 'Pending'),
                    'paid': row.get('Paid', 'No'),
                    'biker': row.get('Biker', 'Unassigned'),
                    'order_time': row.get('Order Time', 'Unknown')
                }

        # If we get through the whole loop without a match
        logging.warning(f"Order ID {order_id} not found in sheet.")
        return None

    except Exception as e:
        logging.error(f"Error during status check: {e}")
        return None

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        ['🛍 Order / ይዘዙ', '💰 Pricing / ዋጋ'],
        ['ℹ️ How it Works / እንዴት ይሰራል', '📞 Support / እርዳታ'],
        ['📋 Design Guidelines / የዲዛይን መመሪያዎች', '📊 Check Status / ሁኔታ ማየት']
    ]
    await update.message.reply_text(
        get_message('welcome'),
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return ConversationHandler.END

async def show_how_it_works(update: Update, context: ContextTypes.DEFAULT_TYPE):
    content_en = HOW_IT_WORKS_EN
    content_am = HOW_IT_WORKS_AM
    button = [['🛍 Order Now / አሁን ይዘዙ', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
    await update.message.reply_text(
        f"{content_en}\n\n{content_am}",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(button, resize_keyboard=True)
    )

async def show_design_guidelines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    guidelines_en = DESIGN_GUIDELINES_EN
    guidelines_am = DESIGN_GUIDELINES_AM
    button = [['🛍 Order Now / አሁን ይዘዙ', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
    await update.message.reply_text(
        f"{guidelines_en}\n\n{guidelines_am}",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(button, resize_keyboard=True)
    )

async def show_pricing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pricing_en = PRICING_EN
    pricing_am = PRICING_AM
    button = [['🛍 Order Now / አሁን ይዘዙ', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
    await update.message.reply_text(
        f"{pricing_en}\n\n{pricing_am}",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(button, resize_keyboard=True)
    )

async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    order_id = generate_order_id()
    context.user_data['order_id'] = order_id
    await update.message.reply_text(
        get_message('order_start', order_id=order_id),
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup([['🏠 Back to Menu / ወደ መነሻ ይመለሱ']], resize_keyboard=True)
    )
    return QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text or 'Menu' in update.message.text or 'መነሻ' in update.message.text:
        return await start(update, context)
    try:
        qty = int(update.message.text.strip())
        if qty <= 0:
            await update.message.reply_text(get_message('invalid_number'))
            return QUANTITY
        if qty > 100:
            await update.message.reply_text(
                "For bulk orders over 100, please contact support directly. How many cards?\n\n"
                "ለ100 በላይ በጅምላ ትዕዛዞች በቀጥታ ድጋፍ ያግኙ። ስንት ካርዶች?"
            )
            return QUANTITY
        context.user_data['quantity'] = qty
        context.user_data['total_price'] = calculate_price(qty)
        unit_price = calculate_price(qty) // qty
        total = context.user_data['total_price']
        price_info = get_message('price_breakdown', qty=qty, unit_price=unit_price, total=total)
        if qty < 5:
            price_info += get_message('tip_small')
        elif qty < 10:
            price_info += get_message('tip_medium')
        full_message = f"{price_info}\n{get_message('confirm_order', total=total)}"
        buttons = [['✅ Yes, Continue / አዎ, ቀጥል', '❌ Cancel / ሰርዝ', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(
            full_message,
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        return AGREEMENT
    except ValueError:
        await update.message.reply_text(get_message('invalid_number'))
        return QUANTITY
    except Exception as e:
        logging.error(f"Error in get_quantity: {e}")
        await update.message.reply_text(
            "An error occurred. Please try again with /start\n\n"
            "ስህተት ተከስቷል። /start በመጠቀም እንደገና ይሞክሩ"
        )
        return ConversationHandler.END

async def get_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text or 'Menu' in update.message.text or 'መነሻ' in update.message.text:
        return await start(update, context)
    if 'Cancel' in update.message.text or 'ሰርዝ' in update.message.text:
        await update.message.reply_text(get_message('order_cancelled'))
        return await start(update, context)
    if 'Yes' in update.message.text or 'አዎ' in update.message.text or 'Continue' in update.message.text or 'ቀጥል' in update.message.text:
        guidelines_en = DESIGN_GUIDELINES_EN
        guidelines_am = DESIGN_GUIDELINES_AM
        buttons = [['📤 Upload Front / ፊት ለፊት ይጫኑ', '🔗 Connect with Designer / ከዲዛይነር ጋር ይገናኙ', 'Skip / ዝለል', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(
            f"{guidelines_en}\n\n{guidelines_am}",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        return FRONT_IMAGE
    else:
        await update.message.reply_text(get_message('order_cancelled'))
        return await start(update, context)

async def get_front(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text or 'Menu' in update.message.text or 'መነሻ' in update.message.text:
        return await start(update, context)
    if update.message.text and ('designer' in update.message.text.lower() or 'ዲዛይነር' in update.message.text):
        context.user_data['front_photo'] = "NEEDS_DESIGNER"
        context.user_data['front_note'] = "Customer wants to connect with a designer"
        try:
            admin_msg = f"""
🎨 **DESIGNER CONNECTION REQUEST** `{context.user_data.get('order_id', 'N/A')}`
Customer wants to connect with a designer.
They have an idea but haven't made the design yet.
**Customer Info:**
• Order ID: {context.user_data.get('order_id', 'N/A')}
• Quantity: {context.user_data.get('quantity', 'N/A')}
Please contact them manually for design consultation.
"""
            await context.bot.send_message(chat_id=MY_ADMIN_ID, text=admin_msg, parse_mode='Markdown')
        except Exception as e:
            logging.error(f"Error notifying admin about designer request: {e}")
        buttons = [['📤 Upload Back / ጀርባ ይጫኑ', 'NO BACK DESIGN / ጀርባ የለም', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        message = "✅ Designer connection request received! We'll contact you soon. Now upload back design:\n\n✅ ከዲዛይነር ጋር ለመገናኘት ጥያቄዎ ተቀብሏል! በቅርብ ጊዜ እናግኝዎታለን። አሁን የጀርባ ዲዛይን ይጫኑ:"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE
    if update.message.text and ('skip' in update.message.text.lower() or 'ዝለል' in update.message.text):
        context.user_data['front_photo'] = "SKIP"
        context.user_data['front_note'] = "Using default template"
        buttons = [['📤 Upload Back / ጀርባ ይጫኑ', 'NO BACK DESIGN / ጀርባ የለም', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        message = "Using default template. Now upload back design:\n\nየመደበኛ ቅጥ በመጠቀም ላይ። አሁን የጀርባ ዲዛይን ይጫኑ:"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['front_photo'] = file_id
        buttons = [['📤 Upload Back / ጀርባ ይጫኑ', 'NO BACK DESIGN / ጀርባ የለም', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        message = "✅ Front design accepted! Now upload back design:\n\n✅ የፊት ለፊት ዲዛይን ተቀብሎአል! አሁን የጀርባ ዲዛይን ይጫኑ:"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE
    elif update.message.document:
        message = "Please send the design as a photo (not a document file).\nIf you have a PDF/AI file, please contact support.\n\nእባክዎ ዲዛይንን እንደ ፎቶ ይላኩ (እንደ ፋይል ሳይሆን)።\nPDF/AI ፋይል ካለዎት እባክዎ ድጋፍ ያግኙ።"
        buttons = [['📤 Upload Front / ፊት ለፊት ይጫኑ', '🔗 Connect with Designer / ከዲዛይነር ጋር ይገናኙ', 'Skip / ዝለል', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return FRONT_IMAGE
    else:
        buttons = [['📤 Upload Front / ፊት ለፊት ይጫኑ', '🔗 Connect with Designer / ከዲዛይነር ጋር ይገናኙ', 'Skip / ዝለል', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        message = "Please upload a photo of your front design, connect with a designer, or click 'Skip':\n\nእባክዎ የፊት ለፊት ዲዛይንዎን ይጫኑ፣ ከዲዛይነር ጋር ለመገናኘት ይምረጡ ወይም 'ዝለል' ይተይቡ:"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return FRONT_IMAGE

async def get_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text or 'Menu' in update.message.text or 'መነሻ' in update.message.text:
        return await start(update, context)
    if update.message.text and ('no' in update.message.text.lower() or 'skip' in update.message.text.lower() or 'የለም' in update.message.text or 'ዝለል' in update.message.text):
        context.user_data['back_photo'] = "NONE"
        buttons = [['🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(get_message('enter_name'), reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return USER_NAME
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['back_photo'] = file_id
        await update.message.reply_text("✅ Back design accepted!\n\n✅ የጀርባ ዲዛይን ተቀብሎአል!", reply_markup=ReplyKeyboardRemove())
        buttons = [['🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(get_message('enter_name'), reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return USER_NAME
    elif update.message.document:
        message = "Please send the design as a photo (not a document file).\n\nእባክዎ ዲዛይንን እንደ ፎቶ ይላኩ (እንደ ፋይል ሳይሆን)።"
        buttons = [['📤 Upload Back / ጀርባ ይጫኑ', 'NO BACK DESIGN / ጀርባ የለም', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE
    else:
        buttons = [['📤 Upload Back / ጀርባ ይጫኑ', 'NO BACK DESIGN / ጀርባ የለም', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        message = "Please upload back design or select 'No Back Design':\n\nእባክዎ የጀርባ ዲዛይን ይጫኑ ወይም 'ጀርባ የለም' ይምረጡ:"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text or 'Menu' in update.message.text or 'መነሻ' in update.message.text:
        return await start(update, context)
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text(
            "Please enter a valid full name (at least 2 characters, in English):\n\n"
            "እባክዎ ትክክለኛ ሙሉ ስም ያስገቡ (ቢያንስ 2 ፊደላት, በእንግሊዝኛ):"
        )
        return USER_NAME
    context.user_data['full_name'] = name
    buttons = [['🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
    await update.message.reply_text(
        get_message('name_saved', name=name),
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return CONTACT_INFO

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text or 'Menu' in update.message.text or 'መነሻ' in update.message.text:
        return await start(update, context)
    phone = update.message.text.strip()
    if update.message.contact:
        phone = update.message.contact.phone_number
    if not validate_phone(phone):
        buttons = [['🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(
            get_message('invalid_phone'),
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        return CONTACT_INFO
    context.user_data['phone'] = phone
    order_id = context.user_data.get('order_id', 'N/A')
    quantity = context.user_data.get('quantity', 0)
    total_price = context.user_data.get('total_price', 0)
    front_photo = context.user_data.get('front_photo', '')
    if front_photo == 'NEEDS_DESIGNER':
        front_type = 'Needs designer connection / ከዲዛይነር ጋር ማገናኘት ያስፈልገዋል'
    elif front_photo == 'SKIP':
        front_type = 'Default template / የመደበኛ ቅጥ'
    elif front_photo:
        front_type = 'Custom design / ብጁ ዲዛይን'
    else:
        front_type = 'Not specified / አልተገለጸም'
    back_photo = context.user_data.get('back_photo', '')
    if back_photo == 'NONE':
        back_type = 'None / የለም'
    elif back_photo:
        back_type = 'Custom design / ብጁ ዲዛይን'
    else:
        back_type = 'Not specified / አልተገለጸም'
    summary = get_message('order_confirmation',
        order_id=order_id,
        name=context.user_data.get('full_name', 'N/A'),
        phone=phone,
        quantity=quantity,
        total=total_price,
        front_type=front_type,
        back_type=back_type)
    buttons = [['✅ Confirm & Submit / አረጋግጥ & አስገባ', '✏️ Edit Information / መረጃ አርትዕ', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
    await update.message.reply_text(
        summary,
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return DESIGN_CONFIRM

async def confirm_design(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text or 'Menu' in update.message.text or 'መነሻ' in update.message.text:
        return await start(update, context)
    if 'Confirm' in update.message.text or 'አረጋግጥ' in update.message.text or 'Submit' in update.message.text or 'አስገባ' in update.message.text:
        # 1. SAVE TO GOOGLE SHEETS
        success = save_to_google_sheets(context.user_data)
        # 2. NOTIFY ADMIN
        order_id = context.user_data.get('order_id', 'N/A')
        front_photo = context.user_data.get('front_photo', '')
        back_photo = context.user_data.get('back_photo', '')
        front_status = 'Needs designer connection' if front_photo == 'NEEDS_DESIGNER' else 'Template' if front_photo == 'SKIP' else 'Custom' if front_photo else 'Not specified'
        back_status = 'None' if back_photo == 'NONE' else 'Custom' if back_photo else 'Not specified'
        admin_summary = f"""
🚀 **NEW ORDER RECEIVED** `{order_id}`
**Customer Info:**
👤 Name: {context.user_data.get('full_name', 'N/A')}
📞 Phone: {context.user_data.get('phone', 'N/A')}
🆔 User: @{update.message.from_user.username}
**Order Details:**
🔢 Quantity: {context.user_data.get('quantity', 0)}
💰 Total: {context.user_data.get('total_price', 0)} ETB
🎨 Front: {front_status}
🎨 Back: {back_status}
**Note:** Handle this order manually.
"""
        try:
            await context.bot.send_message(chat_id=MY_ADMIN_ID, text=admin_summary, parse_mode='Markdown')
            if context.user_data.get('front_photo') and context.user_data.get('front_photo') not in ['SKIP', 'NEEDS_DESIGNER']:
                await context.bot.send_photo(chat_id=MY_ADMIN_ID, photo=context.user_data['front_photo'], caption=f"Front Design - Order {order_id}")
            if context.user_data.get('back_photo') and context.user_data.get('back_photo') != 'NONE':
                await context.bot.send_photo(chat_id=MY_ADMIN_ID, photo=context.user_data['back_photo'], caption=f"Back Design - Order {order_id}")
            confirmation = get_message('order_submitted',
                order_id=order_id,
                quantity=context.user_data.get('quantity', 0),
                total=context.user_data.get('total_price', 0))
            await update.message.reply_text(confirmation, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
            from asyncio import sleep
            async def send_reminder():
                await sleep(7200)
                try:
                    reminder = "🔔 **Reminder:** Our service team will contact you soon!\n\n🔔 **ማስገንዘቢያ:** የአገልግሎት ቡድናችን በቅርብ ጊዜ እናግኝዎታለን!"
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=reminder, parse_mode='Markdown')
                except Exception as e:
                    logging.error(f"Error sending reminder: {e}")
            context.application.create_task(send_reminder())
        except Exception as e:
            logging.error(f"Error sending order to admin: {e}")
        if success:
            await update.message.reply_text("✅ Order saved to ERP!\n\n✅ ትዕዛዝ ወደ ኤርፒ ተቀብሏል!")
        else:
            await update.message.reply_text("⚠️ Order saved to Telegram only (ERP connection failed).\n\n⚠️ ትዕዛዝ ብቻ ተቀብሏል (ኤርፒ ግንኙነት አልተሳካም).")
        return await start(update, context)
    else:
        buttons = [['🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(get_message('enter_name'), reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return USER_NAME

async def check_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = "Please enter your order ID (e.g., FD-20231201123456):\n\nእባክዎ የትዕዛዝ መታወቂያዎን ያስገቡ (ለምሳሌ FD-20231201123456):"
    button = [['🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
    await update.message.reply_text(
        message, 
        reply_markup=ReplyKeyboardMarkup(button, resize_keyboard=True)
    )
    return CHECK_STATUS_ID

async def handle_status_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_id = update.message.text.strip()
    
    # Check for back to menu
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text or 'Menu' in update.message.text or 'መነሻ' in update.message.text:
        return await start(update, context)
    
    # Check status in Google Sheet
    order_info = check_order_status_in_sheet(order_id)
    
    if order_info:
        status_message = f"""
📊 **Order Status for `{order_id}` / የትዕዛዝ ሁኔታ ለ `{order_id}`**
**Current Stage / የአሁኑ ሁኔታ:** {order_info['stage']}
**Payment Status / የክፍያ ሁኔታ:** {order_info['paid']}
**Delivery Agent / ማስረከቢያ ኤጀንት:** {order_info['biker']}
**Order Time / የትዕዛዝ ሰዓት:** {order_info['order_time']}

Thank you for your patience! / ለእርዳታዎ እናመሰግናለን!
        """
        await update.message.reply_text(status_message, parse_mode='Markdown')
    else:
        await update.message.reply_text(get_message('status_not_found', order_id=order_id))
    
    # Return to main menu
    keyboard = [
        ['🛍 Order / ይዘዙ', '💰 Pricing / ዋጋ'],
        ['ℹ️ How it Works / እንዴት ይሰራል', '📞 Support / እርዳታ'],
        ['📋 Design Guidelines / የዲዛይን መመሪያዎች', '📊 Check Status / ሁኔታ ማየት']
    ]
    await update.message.reply_text(
        "Returned to main menu / ወደ ዋናው ምናሌ ተመለሰ",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return ConversationHandler.END

async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ['Design Issue / የዲዛይን ችግር', 'Order Status / የትዕዛዝ ሁኔታ'],
        ['Payment Question / የክፍያ ጥያቄ', 'Technical Problem / የቴክኒክ ችግር'],
        ['Other / ሌላ', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']
    ]
    message = "Select your issue type or describe it:\n\nየችግሩን አይነት ይምረጡ ወይም ይግለጹ:"
    await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return SUPPORT_DESC

async def support_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['support_type'] = update.message.text
    message = "Please describe your problem in detail:\n\nእባክዎ ችግሩን በዝርዝር ይግለጹ:"
    buttons = [['🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
    await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
    return SUPPORT_PHONE

async def handle_support_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('support_msg'):
        context.user_data['support_msg'] = update.message.text
    phone = update.message.text.strip()
    if update.message.contact:
        phone = update.message.contact.phone_number
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text or 'Menu' in update.message.text or 'መነሻ' in update.message.text:
        return await start(update, context)
    if not validate_phone(phone):
        buttons = [['🏠 Back to Menu / ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(
            get_message('invalid_phone'),
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        return SUPPORT_PHONE
    admin_msg = f"""
🆘 **SUPPORT REQUEST / የድጋፍ ጥያቄ**
**Type / አይነት:** {context.user_data.get('support_type', 'Not specified / አልተገለጸም')}
**Phone / ስልክ:** {phone}
**User / ተጠቃሚ:** @{update.message.from_user.username}
**Message / መልእክት:**
{context.user_data.get('support_msg', 'No message / መልእክት የለም')}
**Status / ሁኔታ:** ⏳ Needs callback / መመለስ ያስፈልገዋል
"""
    try:
        await context.bot.send_message(chat_id=MY_ADMIN_ID, text=admin_msg, parse_mode='Markdown')
        await update.message.reply_text(
            "✅ Support request sent! We'll call you within 30 minutes.\n\n✅ የድጋፍ ጥያቄ ተልኳል! በ30 ደቂቃዎች ውስጥ እንደገና እናግኝዎታለን።",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logging.error(f"Error sending support request: {e}")
        await update.message.reply_text(
            "Message received. We'll contact you soon.\n\nመልእክት ተቀብሎአል። በቅርብ ጊዜ እናግኝዎታለን።",
            reply_markup=ReplyKeyboardRemove()
        )
    return await start(update, context)

# --- SETUP FUNCTION FOR WEBHOOK ---
def setup_application() -> Application:
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)
    # Command handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', check_status_command))
    # Non-conversation handlers
    app.add_handler(MessageHandler(filters.Regex('Pricing|ዋጋ'), show_pricing))
    app.add_handler(MessageHandler(filters.Regex('Design Guidelines|የዲዛይን መመሪያዎች'), show_design_guidelines))
    app.add_handler(MessageHandler(filters.Regex('How it Works|እንዴት ይሰራል'), show_how_it_works))
    app.add_handler(MessageHandler(filters.Regex('Check Status|ሁኔታ ማየት'), check_status_command))
    # Order conversation
    order_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('Order|ይዘዙ|Order Now|አሁን ይዘዙ'), order_start)],
        states={
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
            AGREEMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_agreement)],
            FRONT_IMAGE: [MessageHandler(filters.PHOTO | filters.TEXT | filters.Document.ALL, get_front)],
            BACK_IMAGE: [MessageHandler(filters.PHOTO | filters.TEXT | filters.Document.ALL, get_back)],
            USER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            CONTACT_INFO: [MessageHandler(filters.CONTACT | filters.TEXT, get_contact)],
            DESIGN_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_design)],
        },
        fallbacks=[
            CommandHandler('cancel', start),
            CommandHandler('start', start),
            MessageHandler(filters.Regex('Cancel|Restart|ሰርዝ|እንደገና ጀምር|Back|ይመለሱ|Menu|መነሻ'), start)
        ],
    )
    # Support conversation
    support_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('Support|እርዳታ'), support_start)],
        states={
            SUPPORT_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_description)],
            SUPPORT_PHONE: [MessageHandler(filters.CONTACT | filters.TEXT, handle_support_final)],
        },
        fallbacks=[
            CommandHandler('cancel', start),
            CommandHandler('start', start),
            MessageHandler(filters.Regex('Cancel|Restart|ሰርዝ|እንደገና ጀምር|Back|ይመለሱ|Menu|መነሻ'), start)
        ],
    )
    # Status check conversation
    status_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('Check Status|ሁኔታ ማየት'), check_status_command)],
        states={
            CHECK_STATUS_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_status_check)],
        },
        fallbacks=[
            CommandHandler('start', start),
            MessageHandler(filters.Regex('Back|ይመለሱ|Menu|መነሻ'), start)
        ],
    )

    app.add_handler(order_conv_handler)
    app.add_handler(support_conv_handler)
    app.add_handler(status_conv_handler)
    # NO AI HANDLER
    return app

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Update {update} caused error {context.error}")
    try:
        await update.message.reply_text(
            "Sorry, an error occurred. Please try again or use /start\n\n"
            "ይቅርታ፣ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ ወይም /start ይጠቀሙ",
            reply_markup=ReplyKeyboardMarkup([['🔄 Restart / እንደገና ጀምር', '🏠 Back to Menu / ወደ መነሻ ይመለሱ']], resize_keyboard=True)
        )
    except:
        pass
