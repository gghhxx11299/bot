# bot_logic.py
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
import re
from datetime import datetime
import os

# --- BILINGUAL SYSTEM PROMPT (kept for reference) ---
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
        'en': "Now enter your full name for the cards:",
        'am': "አሁን ለካርዶቹ ሙሉ ስምዎን ያስገቡ:"
    },
    'name_saved': {
        'en': "Name saved: {name}\nNow please share your phone number for order updates:",
        'am': "ስምዎ ተቀብሏል፡ {name}\nአሁን ለትዕዛዝ ዝርዝሮች ስልክ ቁጥርዎን ያሳውቁን፡"
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
Our team will handle everything manually:
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
ቡድናችን ሁሉንም ነገር በአግባቡ ያስተናግዳል:
• የዲዛይን ምክር ከፈለጉ
• የክፍያ ማደራጀት
• የማስረከቢያ አሰጣጥ
**የማስረከቢያ አማራጮች:**
• በአዲስ አበባ ውስጥ ሁሉ ቦታ - 200 ብር
• ከኢትዮጵያ ውጭ በጠይቅ ላይ (0960375738 ይደውሉ)
የፋይንዳታ ኤንኤፍሲ ካርዶች ስለመረጡ እናመሰግናለን!
የአገልግሎት ቡድናችን በቅርብ ጊዜ እናግኝዎታለን።
"""
    }
}

# --- CONFIG (use env vars in production) ---
TOKEN = os.getenv("BOT_TOKEN", "8043069992:AAED1gGkZQ52JItsWpbVKWuFiRSv2cp82U0")
MY_ADMIN_ID = os.getenv("ADMIN_ID", "1621254504")

# --- STATES ---
QUANTITY, AGREEMENT, FRONT_IMAGE, BACK_IMAGE, USER_NAME, CONTACT_INFO, DESIGN_CONFIRM = range(7)
SUPPORT_DESC, SUPPORT_PHONE = range(8, 10)

# --- HELPERS ---
def get_message(key, lang='en', **kwargs):
    """Get bilingual message"""
    message = MESSAGES.get(key, {}).get(lang, MESSAGES.get(key, {}).get('en', ''))
    return message.format(**kwargs) if kwargs else message

def detect_language(text):
    """Simple language detection based on Amharic characters"""
    amharic_range = range(4608, 4989)  # Amharic Unicode range
    if any(ord(char) in amharic_range for char in str(text)[:10]):
        return 'am'
    return 'en'

def calculate_price(qty):
    if qty >= 10:
        return qty * 1000
    if qty >= 5:
        return qty * 1100
    return qty * 1200

def validate_phone(phone):
    """Validate Ethiopian phone numbers"""
    eth_pattern = r'^(09\d{8}|\+2519\d{8}|2519\d{8}|9\d{8})$'
    return bool(re.match(eth_pattern, str(phone)))

def generate_order_id():
    return f"FD-{datetime.now().strftime('%Y%m%d%H%M%S')}"

# --- HANDLERS (identical to original, no AI) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ['🛍 Order / ይዘዙ', '💰 Pricing / ዋጋ'],
        ['ℹ️ How it Works / እንዴት ይሰራል', '📞 Support / እርዳታ'],
        ['📋 Design Guidelines / የዲዛይን መመሪያዎች', '📊 Check Status / ሁኔታ ማየት']
    ]
    welcome_text = f"{get_message('welcome', 'en')}\n{get_message('welcome', 'am')}"
    await update.message.reply_text(
        welcome_text,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return ConversationHandler.END

async def show_how_it_works(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text) if update.message else 'en'
    if lang == 'am':
        content = HOW_IT_WORKS_AM
        button = [['🛍 አሁን ይዘዙ', '🏠 ወደ መነሻ ይመለሱ']]
    else:
        content = HOW_IT_WORKS_EN
        button = [['🛍 Order Now', '🏠 Back to Menu']]
    await update.message.reply_text(
        content,
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(button, resize_keyboard=True)
    )

async def show_design_guidelines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text) if update.message else 'en'
    if lang == 'am':
        guidelines = DESIGN_GUIDELINES_AM
        button = [['🛍 አሁን ይዘዙ', '🏠 ወደ መነሻ ይመለሱ']]
    else:
        guidelines = DESIGN_GUIDELINES_EN
        button = [['🛍 Order Now', '🏠 Back to Menu']]
    await update.message.reply_text(
        guidelines,
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(button, resize_keyboard=True)
    )

async def show_pricing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text) if update.message else 'en'
    if lang == 'am':
        pricing = PRICING_AM
        button = [['🛍 አሁን ይዘዙ', '🏠 ወደ መነሻ ይመለሱ']]
    else:
        pricing = PRICING_EN
        button = [['🛍 Order Now', '🏠 Back to Menu']]
    await update.message.reply_text(
        pricing,
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(button, resize_keyboard=True)
    )

async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    lang = detect_language(update.message.text)
    order_id = generate_order_id()
    context.user_data['order_id'] = order_id
    context.user_data['language'] = lang
    if lang == 'am':
        buttons = [['🏠 ወደ መነሻ ይመለሱ']]
    else:
        buttons = [['🏠 Back to Menu']]
    await update.message.reply_text(
        get_message('order_start', lang, order_id=order_id),
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('language', 'en')
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text:
        return await start(update, context)
    try:
        qty = int(update.message.text.strip())
        if qty <= 0:
            await update.message.reply_text(get_message('invalid_number', lang))
            return QUANTITY
        if qty > 100:
            if lang == 'en':
                await update.message.reply_text("For bulk orders over 100, please contact support directly. How many cards?")
            else:
                await update.message.reply_text("ለ100 በላይ በጅምላ ትዕዛዞች በቀጥታ ድጋፍ ያግኙ። ስንት ካርዶች?")
            return QUANTITY
        context.user_data['quantity'] = qty
        context.user_data['total_price'] = calculate_price(qty)
        unit_price = calculate_price(qty) // qty
        total = context.user_data['total_price']
        price_info = get_message('price_breakdown', lang, qty=qty, unit_price=unit_price, total=total)
        if qty < 5:
            price_info += get_message('tip_small', lang)
        elif qty < 10:
            price_info += get_message('tip_medium', lang)
        full_message = f"{price_info}\n{get_message('confirm_order', lang, total=total)}"
        if lang == 'en':
            buttons = [['✅ Yes, Continue', '❌ Cancel', '🏠 Back to Menu']]
        else:
            buttons = [['✅ አዎ, ቀጥል', '❌ ሰርዝ', '🏠 ወደ መነሻ ይመለሱ']]
        await update.message.reply_text(
            full_message,
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        return AGREEMENT
    except ValueError:
        await update.message.reply_text(get_message('invalid_number', lang))
        return QUANTITY
    except Exception as e:
        logging.error(f"Error in get_quantity: {e}")
        if lang == 'en':
            await update.message.reply_text("An error occurred. Please try again with /start")
        else:
            await update.message.reply_text("ስህተት ተከስቷል። /start በመጠቀም እንደገና ይሞክሩ")
        return ConversationHandler.END

async def get_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('language', 'en')
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text:
        return await start(update, context)
    if 'Cancel' in update.message.text or 'ሰርዝ' in update.message.text:
        await update.message.reply_text(get_message('order_cancelled', lang))
        return await start(update, context)
    if 'Yes' in update.message.text or 'አዎ' in update.message.text:
        if lang == 'am':
            guidelines = DESIGN_GUIDELINES_AM
            buttons = [['📤 ፊት ለፊት ይጫኑ', '🔗 ከዲዛይነር ጋር ይገናኙ', 'ዝለል', '🏠 ወደ መነሻ ይመለሱ']]
        else:
            guidelines = DESIGN_GUIDELINES_EN
            buttons = [['📤 Upload Front', '🔗 Connect with Designer', 'Skip', '🏠 Back to Menu']]
        await update.message.reply_text(
            guidelines,
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        return FRONT_IMAGE
    else:
        await update.message.reply_text(get_message('order_cancelled', lang))
        return await start(update, context)

async def get_front(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('language', 'en')
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text:
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
• Language: {lang}
Please contact them manually for design consultation.
"""
            await context.bot.send_message(chat_id=MY_ADMIN_ID, text=admin_msg, parse_mode='Markdown')
        except Exception as e:
            logging.error(f"Error notifying admin about designer request: {e}")
        if lang == 'am':
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 ወደ መነሻ ይመለሱ']]
            message = "✅ ከዲዛይነር ጋር ለመገናኘት ጥያቄዎ ተቀብሏል! በቅርብ ጊዜ እናግኝዎታለን። አሁን የጀርባ ዲዛይን ይጫኑ:"
        else:
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 Back to Menu']]
            message = "✅ Designer connection request received! We'll contact you soon. Now upload back design:"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE
    if update.message.text and ('skip' in update.message.text.lower() or 'ዝለል' in update.message.text):
        context.user_data['front_photo'] = "SKIP"
        context.user_data['front_note'] = "Using default template"
        if lang == 'am':
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 ወደ መነሻ ይመለሱ']]
            message = "የመደበኛ ቅጥ በመጠቀም ላይ። አሁን የጀርባ ዲዛይን ይጫኑ:"
        else:
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 Back to Menu']]
            message = "Using default template. Now upload back design:"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['front_photo'] = file_id
        if lang == 'am':
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 ወደ መነሻ ይመለሱ']]
            message = "✅ የፊት ለፊት ዲዛይን ተቀብሎአል! አሁን የጀርባ ዲዛይን ይጫኑ:"
        else:
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 Back to Menu']]
            message = "✅ Front design accepted! Now upload back design:"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE
    elif update.message.document:
        if lang == 'am':
            message = "እባክዎ ዲዛይንን እንደ ፎቶ ይላኩ (እንደ ፋይል ሳይሆን)።\nPDF/AI ፋይል ካለዎት እባክዎ ድጋፍ ያግኙ።"
            buttons = [['📤 UPLOAD FRONT', '🔗 CONNECT WITH DESIGNER', 'SKIP', '🏠 ወደ መነሻ ይመለሱ']]
        else:
            message = "Please send the design as a photo (not a document file).\nIf you have a PDF/AI file, please contact support."
            buttons = [['📤 UPLOAD FRONT', '🔗 CONNECT WITH DESIGNER', 'SKIP', '🏠 Back to Menu']]
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return FRONT_IMAGE
    else:
        if lang == 'am':
            buttons = [['📤 UPLOAD FRONT', '🔗 CONNECT WITH DESIGNER', 'ዝለል', '🏠 ወደ መነሻ ይመለሱ']]
            message = "እባክዎ የፊት ለፊት ዲዛይንዎን ይጫኑ፣ ከዲዛይነር ጋር ለመገናኘት ይምረጡ ወይም 'ዝለል' ይተይቡ:"
        else:
            buttons = [['📤 UPLOAD FRONT', '🔗 CONNECT WITH DESIGNER', 'SKIP', '🏠 Back to Menu']]
            message = "Please upload a photo of your front design, connect with a designer, or click 'Skip':"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return FRONT_IMAGE

async def get_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('language', 'en')
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text:
        return await start(update, context)
    if update.message.text and ('no' in update.message.text.lower() or 'skip' in update.message.text.lower() or 'የለም' in update.message.text or 'ዝለል' in update.message.text):
        context.user_data['back_photo'] = "NONE"
        if lang == 'am':
            buttons = [['🏠 ወደ መነሻ ይመለሱ']]
        else:
            buttons = [['🏠 Back to Menu']]
        await update.message.reply_text(get_message('enter_name', lang), reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return USER_NAME
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['back_photo'] = file_id
        await update.message.reply_text("✅ Back design accepted!" if lang == 'en' else "✅ የጀርባ ዲዛይን ተቀብሎአል!", reply_markup=ReplyKeyboardRemove())
        if lang == 'am':
            buttons = [['🏠 ወደ መነሻ ይመለሱ']]
        else:
            buttons = [['🏠 Back to Menu']]
        await update.message.reply_text(get_message('enter_name', lang), reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return USER_NAME
    elif update.message.document:
        if lang == 'am':
            message = "እባክዎ ዲዛይንን እንደ ፎቶ ይላኩ (እንደ ፋይል ሳይሆን)።"
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 ወደ መነሻ ይመለሱ']]
        else:
            message = "Please send the design as a photo (not a document file)."
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 Back to Menu']]
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE
    else:
        if lang == 'am':
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 ወደ መነሻ ይመለሱ']]
            message = "እባክዎ የጀርባ ዲዛይን ይጫኑ ወይም 'ጀርባ የለም' ይምረጡ:"
        else:
            buttons = [['UPLOAD BACK', 'NO BACK DESIGN', '🏠 Back to Menu']]
            message = "Please upload back design or select 'No Back Design':"
        await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return BACK_IMAGE

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('language', 'en')
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text:
        return await start(update, context)
    name = update.message.text.strip()
    if len(name) < 2:
        if lang == 'en':
            await update.message.reply_text("Please enter a valid full name (at least 2 characters):")
        else:
            await update.message.reply_text("እባክዎ ትክክለኛ ሙሉ ስም ያስገቡ (ቢያንስ 2 ፊደላት):")
        return USER_NAME
    context.user_data['full_name'] = name
    if lang == 'am':
        button_text = "📱 ስልክ ቁጥር ያጋሩ"
        buttons = [['📱 ስልክ ቁጥር ያጋሩ', '🏠 ወደ መነሻ ይመለሱ']]
    else:
        button_text = "📱 Share Phone Number"
        buttons = [['📱 Share Phone Number', '🏠 Back to Menu']]
    keyboard = [[KeyboardButton(button_text, request_contact=True)]]
    keyboard.append(buttons[0])
    await update.message.reply_text(
        get_message('name_saved', lang, name=name),
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return CONTACT_INFO

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('language', 'en')
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text:
        return await start(update, context)
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()
    if not validate_phone(phone):
        if lang == 'am':
            button_text = "📱 ስልክ ቁጥር ያጋሩ"
            buttons = [['📱 ስልክ ቁጥር ያጋሩ', '🏠 ወደ መነሻ ይመለሱ']]
        else:
            button_text = "📱 Share Phone Number"
            buttons = [['📱 Share Phone Number', '🏠 Back to Menu']]
        keyboard = [[KeyboardButton(button_text, request_contact=True)]]
        keyboard.append(buttons[0])
        await update.message.reply_text(
            get_message('invalid_phone', lang),
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return CONTACT_INFO
    context.user_data['phone'] = phone
    order_id = context.user_data.get('order_id', 'N/A')
    quantity = context.user_data.get('quantity', 0)
    total_price = context.user_data.get('total_price', 0)
    front_photo = context.user_data.get('front_photo', '')
    if front_photo == 'NEEDS_DESIGNER':
        front_type = 'Needs designer connection'
    elif front_photo == 'SKIP':
        front_type = 'Default template'
    elif front_photo:
        front_type = 'Custom design'
    else:
        front_type = 'Not specified'
    back_photo = context.user_data.get('back_photo', '')
    if back_photo == 'NONE':
        back_type = 'None'
    elif back_photo:
        back_type = 'Custom design'
    else:
        back_type = 'Not specified'
    if lang == 'am':
        if front_type == 'Needs designer connection':
            front_type = 'ከዲዛይነር ጋር ማገናኘት ያስፈልገዋል'
        elif front_type == 'Default template':
            front_type = 'የመደበኛ ቅጥ'
        elif front_type == 'Custom design':
            front_type = 'ብጁ ዲዛይን'
        if back_type == 'None':
            back_type = 'የለም'
        elif back_type == 'Custom design':
            back_type = 'ብጁ ዲዛይን'
    summary = get_message('order_confirmation', lang,
        order_id=order_id,
        name=context.user_data.get('full_name', 'N/A'),
        phone=phone,
        quantity=quantity,
        total=total_price,
        front_type=front_type,
        back_type=back_type)
    if lang == 'en':
        buttons = [['✅ Confirm & Submit', '✏️ Edit Information', '🏠 Back to Menu']]
    else:
        buttons = [['✅ አረጋግጥ & አስገባ', '✏️ መረጃ አርትዕ', '🏠 ወደ መነሻ ይመለሱ']]
    await update.message.reply_text(
        summary,
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return DESIGN_CONFIRM

async def confirm_design(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('language', 'en')
    if 'Back' in update.message.text or 'ይመለሱ' in update.message.text:
        return await start(update, context)
    if 'Confirm' in update.message.text or 'አረጋግጥ' in update.message.text:
        order_id = context.user_data.get('order_id', 'N/A')
        front_photo = context.user_data.get('front_photo', '')
        back_photo = context.user_data.get('back_photo', '')
        if lang == 'am':
            if front_photo == 'NEEDS_DESIGNER':
                front_status = 'ከዲዛይነር ጋር ማገናኘት ያስፈልገዋል'
            elif front_photo == 'SKIP':
                front_status = 'ቅጥ'
            elif front_photo:
                front_status = 'ብጁ'
            else:
                front_status = 'አልተገለጸም'
            if back_photo == 'NONE':
                back_status = 'የለም'
            elif back_photo:
                back_status = 'ብጁ'
            else:
                back_status = 'አልተገለጸም'
            admin_summary = f"""
🚀 **አዲስ ትዕዛዝ ተቀብሏል** `{order_id}`
**የደንበኛ መረጃ:**
👤 ስም: {context.user_data.get('full_name', 'N/A')}
📞 ስልክ: {context.user_data.get('phone', 'N/A')}
🆔 ተጠቃሚ: @{update.message.from_user.username}
**የትዕዛዝ ዝርዝሮች:**
🔢 ብዛት: {context.user_data.get('quantity', 0)}
💰 ጠቅላላ: {context.user_data.get('total_price', 0)} ብር
🎨 ፊት: {front_status}
🎨 ጀርባ: {back_status}
**ማሳሰቢያ:** ይህን ትዕዛዝ በአግባቡ ያስተናግዱ።
"""
        else:
            if front_photo == 'NEEDS_DESIGNER':
                front_status = 'Needs designer connection'
            elif front_photo == 'SKIP':
                front_status = 'Template'
            elif front_photo:
                front_status = 'Custom'
            else:
                front_status = 'Not specified'
            if back_photo == 'NONE':
                back_status = 'None'
            elif back_photo:
                back_status = 'Custom'
            else:
                back_status = 'Not specified'
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
            confirmation = get_message('order_submitted', lang,
                order_id=order_id,
                quantity=context.user_data.get('quantity', 0),
                total=context.user_data.get('total_price', 0))
            await update.message.reply_text(confirmation, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
            from asyncio import sleep
            async def send_reminder():
                await sleep(7200)
                try:
                    if lang == 'am':
                        reminder = "🔔 **ማስገንዘቢያ:** የአገልግሎት ቡድናችን በቅርብ ጊዜ እናግኝዎታለን!"
                    else:
                        reminder = "🔔 **Reminder:** Our service team will contact you soon!"
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=reminder, parse_mode='Markdown')
                except Exception as e:
                    logging.error(f"Error sending reminder: {e}")
            context.application.create_task(send_reminder())
        except Exception as e:
            logging.error(f"Error sending order to admin: {e}")
            if lang == 'en':
                await update.message.reply_text("Order submitted! You'll be contacted shortly.")
            else:
                await update.message.reply_text("ትዕዛዙ ቀርቧል! በቅርብ ጊዜ እናግኝዎታለን።")
        return await start(update, context)
    else:
        if lang == 'am':
            buttons = [['🏠 ወደ መነሻ ይመለሱ']]
        else:
            buttons = [['🏠 Back to Menu']]
        await update.message.reply_text(get_message('enter_name', lang), reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
        return USER_NAME

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text) if update.message else 'en'
    order_id = context.user_data.get('order_id')
    if not order_id:
        if 'full_name' in context.user_
            order_id = context.user_data.get('order_id', 'Unknown')
        else:
            if lang == 'en':
                await update.message.reply_text(
                    "No active order found. Please start a new order with the Order button.",
                    reply_markup=ReplyKeyboardMarkup(
                        [['🛍 Order / ይዘዙ', '📞 Support / እርዳታ', '🏠 Back to Menu']],
                        resize_keyboard=True
                    )
                )
            else:
                await update.message.reply_text(
                    "ምንም ንቁ ትዕዛዝ አልተገኘም። እባክዎ አዲስ ትዕዛዝ በ'ይዘዙ' ቁልፍ ይጀምሩ።",
                    reply_markup=ReplyKeyboardMarkup(
                        [['🛍 Order / ይዘዙ', '📞 Support / እርዳታ', '🏠 ወደ መነሻ ይመለሱ']],
                        resize_keyboard=True
                    )
                )
            return
    if lang == 'am':
        status_message = f"""
📊 **የትዕዛዝ ሁኔታ** `{order_id}`
**የአሁኑ ሁኔታ:** ⏳ በግምገማ ላይ
**የጊዜ መርሃ ግብር:**
1. ✅ ትዕዛዝ ቀርቧል - በቅርብ ጊዜ እናግኝዎታለን
2. 🎨 የዲዛይን ማረጋገጫ - በ24 ሰዓታት ውስጥ
3. 🏭 ምርት - በ1-2 ቀናት
4. 📦 ማስረከቢያ - በ3-5 የስራ ቀናት
**ማስታወሻ:** የአገልግሎት ቡድናችን ሁሉንም ነገር በአግባቡ ያስተናግዳል።
**እርዳታ ያስፈልግዎታል?**
• ለአስቸኳይ ጥያቄዎች ድጋፍ ቁልፉን ይጠቀሙ
• ለቅጣት እርዳታ ይደውሉልን
የአገልግሎት ቡድናችን በቅርብ ጊዜ እናግኝዎታለን!
"""
    else:
        status_message = f"""
📊 **Order Status** `{order_id}`
**Current Status:** ⏳ Under Review
**Timeline:**
1. ✅ Order Submitted - We'll contact you soon
2. 🎨 Design Proof - Within 24 hours
3. 🏭 Production - 1-2 days
4. 📦 Delivery - 3-5 business days
**Note:** Our service team handles everything manually.
**Need Help?**
• Use Support button for urgent queries
• Call us for immediate assistance
Our service team will contact you soon!
"""
    await update.message.reply_text(status_message, parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup(
        [['📞 Contact Support', '🛍 New Order', '🏠 Back to Menu']],
        resize_keyboard=True
    ))

async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text)
    if lang == 'am':
        keyboard = [
            ['የዲዛይን ችግር', 'የትዕዛዝ ሁኔታ'],
            ['የክፍያ ጥያቄ', 'የቴክኒክ ችግር'],
            ['ሌላ', '🏠 ወደ መነሻ ይመለሱ']
        ]
        message = "የችግሩን አይነት ይምረጡ ወይም ይግለጹ:"
    else:
        keyboard = [
            ['Design Issue', 'Order Status'],
            ['Payment Question', 'Technical Problem'],
            ['Other', '🏠 Back to Menu']
        ]
        message = "Select your issue type or describe it:"
    await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return SUPPORT_DESC

async def support_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = detect_language(update.message.text)
    context.user_data['support_type'] = update.message.text
    context.user_data['support_lang'] = lang
    if lang == 'am':
        message = "እባክዎ ችግሩን በዝርዝር ይግለጹ:"
        buttons = [['🏠 ወደ መነሻ ይመለሱ']]
    else:
        message = "Please describe your problem in detail:"
        buttons = [['🏠 Back to Menu']]
    await update.message.reply_text(message, reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
    return SUPPORT_PHONE

async def handle_support_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get('support_lang', 'en')
    if not context.user_data.get('support_msg'):
        context.user_data['support_msg'] = update.message.text
        if lang == 'am':
            button_text = "📱 ስልክ ቁጥር ያጋሩ"
            buttons = [['📱 ስልክ ቁጥር ያጋሩ', '🏠 ወደ መነሻ ይመለሱ']]
        else:
            button_text = "📱 Share Phone Number"
            buttons = [['📱 Share Phone Number', '🏠 Back to Menu']]
        keyboard = [[KeyboardButton(button_text, request_contact=True)]]
        keyboard.append(buttons[0])
        await update.message.reply_text(
            "Thank you. Now please share your phone number for callback:" if lang == 'en' else "አመሰግናለሁ። አሁን እባክዎ ለመመለስ ስልክ ቁጥርዎን ያጋሩ:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return SUPPORT_PHONE
    else:
        if update.message.contact:
            phone = update.message.contact.phone_number
        else:
            phone = update.message.text.strip()
        if 'Back' in update.message.text or 'ይመለሱ' in update.message.text:
            return await start(update, context)
        if not validate_phone(phone):
            if lang == 'am':
                button_text = "📱 ስልክ ቁጥር ያጋሩ"
                buttons = [['📱 ስልክ ቁጥር ያጋሩ', '🏠 ወደ መነሻ ይመለሱ']]
            else:
                button_text = "📱 Share Phone Number"
                buttons = [['📱 Share Phone Number', '🏠 Back to Menu']]
            keyboard = [[KeyboardButton(button_text, request_contact=True)]]
            keyboard.append(buttons[0])
            await update.message.reply_text(
                get_message('invalid_phone', lang),
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            )
            return SUPPORT_PHONE
        if lang == 'am':
            admin_msg = f"""
🆘 **የድጋፍ ጥያቄ**
**አይነት:** {context.user_data.get('support_type', 'አልተገለጸም')}
**ስልክ:** {phone}
**ተጠቃሚ:** @{update.message.from_user.username}
**መልእክት:**
{context.user_data.get('support_msg', 'መልእክት የለም')}
**ሁኔታ:** ⏳ መመለስ ያስፈልገዋል
"""
        else:
            admin_msg = f"""
🆘 **SUPPORT REQUEST**
**Type:** {context.user_data.get('support_type', 'Not specified')}
**Phone:** {phone}
**User:** @{update.message.from_user.username}
**Message:**
{context.user_data.get('support_msg', 'No message')}
**Status:** ⏳ Needs callback
"""
        try:
            await context.bot.send_message(chat_id=MY_ADMIN_ID, text=admin_msg, parse_mode='Markdown')
            if lang == 'en':
                await update.message.reply_text("✅ Support request sent! We'll call you within 30 minutes.", reply_markup=ReplyKeyboardRemove())
            else:
                await update.message.reply_text("✅ የድጋፍ ጥያቄ ተልኳል! በ30 ደቂቃዎች ውስጥ እንደገና እናግኝዎታለን።", reply_markup=ReplyKeyboardRemove())
        except Exception as e:
            logging.error(f"Error sending support request: {e}")
            if lang == 'en':
                await update.message.reply_text("Message received. We'll contact you soon.", reply_markup=ReplyKeyboardRemove())
            else:
                await update.message.reply_text("መልእክት ተቀብሎአል። በቅርብ ጊዜ እናግኝዎታለን።", reply_markup=ReplyKeyboardRemove())
        return await start(update, context)

async def handle_status_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await check_status(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Update {update} caused error {context.error}")
    try:
        lang = 'en'
        if update and update.message:
            lang = detect_language(update.message.text) if update.message.text else 'en'
        if lang == 'en':
            await update.message.reply_text(
                "Sorry, an error occurred. Please try again or use /start",
                reply_markup=ReplyKeyboardMarkup([['🔄 Restart', '🏠 Back to Menu']], resize_keyboard=True)
            )
        else:
            await update.message.reply_text(
                "ይቅርታ፣ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ ወይም /start ይጠቀሙ",
                reply_markup=ReplyKeyboardMarkup([['🔄 እንደገና ጀምር', '🏠 ወደ መነሻ ይመለሱ']], resize_keyboard=True)
            )
    except:
        pass

# --- MAIN SETUP FUNCTION (for webhook import) ---
def setup_application() -> Application:
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)

    # Command handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', check_status))

    # Non-conversation handlers
    app.add_handler(MessageHandler(filters.Regex('Pricing|ዋጋ'), show_pricing))
    app.add_handler(MessageHandler(filters.Regex('Design Guidelines|የዲዛይን መመሪያዎች'), show_design_guidelines))
    app.add_handler(MessageHandler(filters.Regex('How it Works|እንዴት ይሰራል'), show_how_it_works))
    app.add_handler(MessageHandler(filters.Regex('Check Status|ሁኔታ ማየት'), handle_status_button))

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
            MessageHandler(filters.Regex('Cancel|Restart|ሰርዝ|እንደገና ጀምር|Back|ይመለሱ'), start)
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
            MessageHandler(filters.Regex('Cancel|Restart|ሰርዝ|እንደገና ጀምር|Back|ይመለሱ'), start)
        ],
    )

    app.add_handler(order_conv_handler)
    app.add_handler(support_conv_handler)

    # 🔥 NO AI HANDLER — REMOVED FOR SPEED

    return app
