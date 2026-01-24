import os
import logging
from datetime import datetime, timedelta
from threading import Lock, Thread
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
import sys
import json
from concurrent.futures import ThreadPoolExecutor
import time
from collections import defaultdict
import requests
import socket

# ======================
# GLOBAL STATE WITH LOCK
# ======================
STATE_LOCK = Lock()
USER_STATE = {}
WORKER_DASHBOARD_SESSIONS = {}
EXECUTOR = ThreadPoolExecutor(max_workers=10)

# ======================
# CACHE FOR SHEETS DATA
# ======================
SHEETS_CACHE = {
    "Users": {"data": None, "timestamp": None},
    "Workers": {"data": None, "timestamp": None},
    "Orders": {"data": None, "timestamp": None},
    "Payouts": {"data": None, "timestamp": None},
    "History": {"data": None, "timestamp": None}
}
CACHE_TIMEOUT = 30

# ======================
# BATCH OPERATIONS QUEUE
# ======================
BATCH_OPERATIONS = defaultdict(list)
BATCH_LOCK = Lock()
LAST_BATCH_FLUSH = datetime.now()
BATCH_FLUSH_INTERVAL = 10
BATCH_MAX_SIZE = 50

# ======================
# CONFIGURATION
# ======================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_MAIN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
SHEET_ID = os.getenv("SHEET_ID", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()

# ======================
# GOOGLE CREDENTIALS FROM ENV
# ======================
def get_google_credentials():
    """Get Google credentials from environment variables"""
    try:
        creds_dict = {
            "type": "service_account",
            "project_id": os.getenv("GOOGLE_PROJECT_ID", ""),
            "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID", ""),
            "private_key": os.getenv("GOOGLE_PRIVATE_KEY", "").replace("\\n", "\n"),
            "client_email": os.getenv("GOOGLE_CLIENT_EMAIL", ""),
            "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL", ""),
            "universe_domain": "googleapis.com"
        }
        
        required_fields = ["private_key_id", "private_key", "client_email", "project_id"]
        for field in required_fields:
            if not creds_dict.get(field):
                logger.error(f"Missing required Google credential: {field}")
                return None
        
        return creds_dict
    except Exception as e:
        logger.error(f"Error constructing Google credentials: {e}")
        return None

GOOGLE_CREDS = get_google_credentials()

ACTIVE_CITIES = ["Addis Ababa"]
ALL_CITIES = ["Addis Ababa", "Hawassa", "Dire Dawa", "Mekelle", "Bahir Dar", "Adama", "Jimma", "Dessie"]
BANKS = ["CBE", "Bank of Abyssinia"]
HOURLY_RATE = 100
COMMISSION_PERCENT = 0.25
COMMISSION_TIMEOUT_HOURS = 3
MAX_WARNING_DISTANCE = 100
MAX_ALLOWED_DISTANCE = 500
PORT = int(os.getenv("PORT", "10000"))
ADMIN_TELEGRAM_USERNAME = "@YazilignAdmin"
EXCHANGE_TIMEOUT_HOURS = 3
HANDOVER_DISTANCE_LIMIT = 50

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Disable verbose logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("gspread").setLevel(logging.WARNING)
logging.getLogger("oauth2client").setLevel(logging.WARNING)

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
STATE_WORKER_EXCHANGE_REQUEST = 31
STATE_WORKER_EXCHANGE_CONFIRM = 32
STATE_CLIENT_HANDOVER_CONFIRM = 33
STATE_WORKER_JOB_FINISHED = 34
STATE_WORKER_SELFIE = 35

# ======================
# BATCH OPERATIONS MANAGER
# ======================
def add_to_batch(sheet_name, operation_type, data):
    with BATCH_LOCK:
        BATCH_OPERATIONS[sheet_name].append((operation_type, data))
        if len(BATCH_OPERATIONS[sheet_name]) >= BATCH_MAX_SIZE:
            flush_batch(sheet_name)

def flush_all_batches():
    with BATCH_LOCK:
        for sheet_name in list(BATCH_OPERATIONS.keys()):
            if BATCH_OPERATIONS[sheet_name]:
                flush_batch(sheet_name)
        global LAST_BATCH_FLUSH
        LAST_BATCH_FLUSH = datetime.now()

def flush_batch(sheet_name):
    if sheet_name not in BATCH_OPERATIONS or not BATCH_OPERATIONS[sheet_name]:
        return
    
    operations = BATCH_OPERATIONS[sheet_name].copy()
    BATCH_OPERATIONS[sheet_name] = []
    
    append_operations = [op[1] for op in operations if op[0] == "append"]
    update_operations = [op[1] for op in operations if op[0] == "update"]
    
    try:
        if append_operations:
            batch_append_to_sheet(sheet_name, append_operations)
        if update_operations:
            batch_update_sheet(sheet_name, update_operations)
        logger.info(f"Flushed {len(operations)} operations to {sheet_name}")
    except Exception as e:
        logger.error(f"Batch flush error for {sheet_name}: {e}")
        BATCH_OPERATIONS[sheet_name].extend(operations)

def batch_append_to_sheet(sheet_name, rows_data):
    try:
        worksheet = get_worksheet(sheet_name)
        if rows_data:
            worksheet.append_rows(rows_data)
            logger.info(f"Appended {len(rows_data)} rows to {sheet_name}")
            invalidate_cache(sheet_name)
    except Exception as e:
        logger.error(f"Batch append error for {sheet_name}: {e}")
        raise

def batch_update_sheet(sheet_name, update_data):
    try:
        worksheet = get_worksheet(sheet_name)
        updates_by_row = defaultdict(dict)
        for row_index, col_index, value in update_data:
            updates_by_row[row_index][col_index] = value
        
        for row_index, updates in updates_by_row.items():
            for col_index, value in updates.items():
                worksheet.update_cell(row_index, col_index, value)
        
        logger.info(f"Batch updated {len(update_data)} cells in {sheet_name}")
        invalidate_cache(sheet_name)
    except Exception as e:
        logger.error(f"Batch update error for {sheet_name}: {e}")
        raise

# ======================
# CACHE MANAGEMENT
# ======================
def get_cached_data(sheet_name):
    cache_entry = SHEETS_CACHE.get(sheet_name)
    if cache_entry and cache_entry["data"] is not None:
        if cache_entry["timestamp"]:
            age = (datetime.now() - cache_entry["timestamp"]).total_seconds()
            if age < CACHE_TIMEOUT:
                return cache_entry["data"]
    return None

def set_cached_data(sheet_name, data):
    SHEETS_CACHE[sheet_name] = {"data": data, "timestamp": datetime.now()}

def invalidate_cache(sheet_name=None):
    if sheet_name:
        SHEETS_CACHE[sheet_name] = {"data": None, "timestamp": None}
    else:
        for key in SHEETS_CACHE:
            SHEETS_CACHE[key] = {"data": None, "timestamp": None}

# ======================
# GOOGLE SHEETS FUNCTIONS
# ======================
def get_sheet_client():
    """Get authenticated Google Sheets client"""
    try:
        if not GOOGLE_CREDS:
            logger.error("Google credentials not available")
            raise Exception("Google credentials not configured")
        
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDS, scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        logger.error(f"Failed to authenticate with Google Sheets: {e}")
        raise

def get_worksheet(sheet_name):
    try:
        client = get_sheet_client()
        spreadsheet = client.open_by_key(SHEET_ID)
        worksheet = spreadsheet.worksheet(sheet_name)
        return worksheet
    except Exception as e:
        logger.error(f"Error getting worksheet '{sheet_name}': {e}")
        raise

def get_worksheet_data_optimized(sheet_name, use_cache=True):
    if use_cache:
        cached_data = get_cached_data(sheet_name)
        if cached_data is not None:
            return cached_data
    
    try:
        worksheet = get_worksheet(sheet_name)
        all_values = worksheet.get_all_values()
        
        if not all_values:
            set_cached_data(sheet_name, [])
            return []
        
        headers = all_values[0]
        data = []
        
        batch_size = 100
        for i in range(1, len(all_values), batch_size):
            batch = all_values[i:i + batch_size]
            for row in batch:
                row_dict = {}
                for j, header in enumerate(headers):
                    row_dict[header] = row[j] if j < len(row) else ""
                data.append(row_dict)
        
        set_cached_data(sheet_name, data)
        logger.info(f"Loaded {len(data)} rows from {sheet_name}")
        return data
    except Exception as e:
        logger.error(f"Error getting worksheet data '{sheet_name}': {e}")
        return []

def bulk_get_sheets_data(sheet_names):
    results = {}
    try:
        client = get_sheet_client()
        spreadsheet = client.open_by_key(SHEET_ID)
        
        for sheet_name in sheet_names:
            cached_data = get_cached_data(sheet_name)
            if cached_data is not None:
                results[sheet_name] = cached_data
                continue
            
            try:
                worksheet = spreadsheet.worksheet(sheet_name)
                all_values = worksheet.get_all_values()
                
                if not all_values:
                    results[sheet_name] = []
                    set_cached_data(sheet_name, [])
                    continue
                
                headers = all_values[0]
                data = []
                for row in all_values[1:]:
                    row_dict = {}
                    for i, header in enumerate(headers):
                        row_dict[header] = row[i] if i < len(row) else ""
                    data.append(row_dict)
                
                results[sheet_name] = data
                set_cached_data(sheet_name, data)
                
            except Exception as e:
                logger.error(f"Error loading sheet {sheet_name}: {e}")
                results[sheet_name] = []
    
    except Exception as e:
        logger.error(f"Error in bulk sheet loading: {e}")
    
    return results

# ======================
# DATA FUNCTIONS
# ======================
def get_all_worksheet_names():
    """Get all worksheet names in the spreadsheet"""
    try:
        client = get_sheet_client()
        spreadsheet = client.open_by_key(SHEET_ID)
        worksheets = spreadsheet.worksheets()
        return [ws.title for ws in worksheets]
    except Exception as e:
        logger.error(f"Error getting worksheet names: {e}")
        return []

def get_user_by_id(user_id):
    """Get user from your Users sheet"""
    try:
        users_data = get_worksheet_data_optimized("Users")
        if not users_data:
            return None
        
        for user in users_data:
            if str(user.get("User_ID")) == str(user_id):
                return user
            if str(user.get("ID")) == str(user_id):
                return user
            if str(user.get("Telegram_ID")) == str(user_id):
                return user
        
        return None
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return None

def get_worker_by_telegram_id(telegram_id):
    """Get worker from Workers or Users sheet"""
    try:
        try:
            workers_data = get_worksheet_data_optimized("Workers")
            if workers_data:
                for worker in workers_data:
                    if str(worker.get("Telegram_ID")) == str(telegram_id):
                        return worker
        except:
            pass
        
        users_data = get_worksheet_data_optimized("Users")
        if users_data:
            for user in users_data:
                if str(user.get("Telegram_ID")) == str(telegram_id):
                    role = user.get("Role", "")
                    if role.lower() == "worker" or "worker" in role.lower():
                        return user
        
        return None
    except Exception as e:
        logger.error(f"Error getting worker {telegram_id}: {e}")
        return None

def get_active_workers():
    """Get active workers from Workers or Users sheet"""
    try:
        try:
            workers_data = get_worksheet_data_optimized("Workers")
            if workers_data:
                return [w for w in workers_data if w.get("Status") == "Active"]
        except:
            pass
        
        users_data = get_worksheet_data_optimized("Users")
        if users_data:
            active_workers = []
            for user in users_data:
                role = user.get("Role", "").lower()
                status = user.get("Status", "").lower()
                telegram_id = user.get("Telegram_ID", "")
                
                if ("worker" in role) and status == "active" and telegram_id:
                    active_workers.append(user)
            return active_workers
        
        return []
    except Exception as e:
        logger.error(f"Error getting active workers: {e}")
        return []

def get_order_by_id(order_id):
    """Get order from Orders sheet"""
    try:
        orders_data = get_worksheet_data_optimized("Orders")
        for order in orders_data:
            if order.get("Order_ID") == order_id:
                return order
        return None
    except:
        try:
            client = get_sheet_client()
            spreadsheet = client.open_by_key(SHEET_ID)
            spreadsheet.add_worksheet(title="Orders", rows=100, cols=20)
            worksheet = spreadsheet.worksheet("Orders")
            headers = ["Order_ID", "Timestamp", "Username", "Bureau_Name", "Status", 
                      "Assigned_Worker", "Hourly_Rate", "Booking_Fee_Paid", 
                      "Payment_Status", "Payment_Method", "Assignment_Timestamp",
                      "Client_TG_ID", "Location", "City", "Total_Hours", "Total_Amount"]
            worksheet.append_row(headers)
            return None
        except Exception as e:
            logger.error(f"Failed to create Orders sheet: {e}")
            return None

def get_pending_orders():
    """Get pending orders"""
    try:
        orders_data = get_worksheet_data_optimized("Orders")
        if orders_data:
            return [o for o in orders_data if o.get("Status") == "Pending"]
        return []
    except:
        logger.warning("Orders sheet not found or empty")
        return []

def update_order_in_batch(order_id, updates):
    """Update order in Orders sheet"""
    try:
        orders_data = get_worksheet_data_optimized("Orders", use_cache=False)
        
        for i, order in enumerate(orders_data):
            if order.get("Order_ID") == order_id:
                row_index = i + 2
                worksheet = get_worksheet("Orders")
                headers = worksheet.row_values(1)
                
                for field, value in updates.items():
                    col_index = None
                    for j, header in enumerate(headers):
                        if header.replace(" ", "_").replace("-", "_") == field.replace(" ", "_").replace("-", "_"):
                            col_index = j + 1
                            break
                    
                    if col_index:
                        add_to_batch("Orders", "update", (row_index, col_index, str(value)))
                    else:
                        logger.warning(f"Column {field} not found in Orders sheet")
                
                for field, value in updates.items():
                    if field in order:
                        order[field] = str(value)
                
                return True
        
        logger.warning(f"Order {order_id} not found for update")
        return False
    except Exception as e:
        logger.error(f"Error updating order {order_id}: {e}")
        return False

def create_order_in_batch(order_data):
    """Create order in Orders sheet"""
    try:
        add_to_batch("Orders", "append", order_data)
        return True
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        try:
            client = get_sheet_client()
            spreadsheet = client.open_by_key(SHEET_ID)
            spreadsheet.add_worksheet(title="Orders", rows=100, cols=20)
            worksheet = spreadsheet.worksheet("Orders")
            headers = ["Order_ID", "Timestamp", "Username", "Bureau_Name", "Status", 
                      "Assigned_Worker", "Hourly_Rate", "Booking_Fee_Paid", 
                      "Payment_Status", "Payment_Method", "Assignment_Timestamp",
                      "Client_TG_ID", "Location", "City", "Total_Hours", "Total_Amount"]
            worksheet.append_row(headers)
            add_to_batch("Orders", "append", order_data)
            return True
        except Exception as e2:
            logger.error(f"Failed to create Orders sheet: {e2}")
            return False

def create_payout_in_batch(payout_data):
    """Create payout in Payouts sheet"""
    try:
        add_to_batch("Payouts", "append", payout_data)
        return True
    except Exception as e:
        logger.error(f"Error creating payout: {e}")
        try:
            client = get_sheet_client()
            spreadsheet = client.open_by_key(SHEET_ID)
            spreadsheet.add_worksheet(title="Payouts", rows=100, cols=10)
            worksheet = spreadsheet.worksheet("Payouts")
            headers = ["Timestamp", "Order_ID", "Worker_ID", "Amount", "Type", 
                      "Status", "Payment_Method", "Account_Details"]
            worksheet.append_row(headers)
            add_to_batch("Payouts", "append", payout_data)
            return True
        except Exception as e2:
            logger.error(f"Failed to create Payouts sheet: {e2}")
            return False

def log_history_in_batch(action_data):
    """Log to History sheet"""
    try:
        add_to_batch("History", "append", action_data)
        return True
    except Exception as e:
        logger.error(f"Error logging history: {e}")
        try:
            client = get_sheet_client()
            spreadsheet = client.open_by_key(SHEET_ID)
            spreadsheet.add_worksheet(title="History", rows=1000, cols=10)
            worksheet = spreadsheet.worksheet("History")
            headers = ["Timestamp", "User_ID", "User_Type", "Action", "Details"]
            worksheet.append_row(headers)
            add_to_batch("History", "append", action_data)
            return True
        except Exception as e2:
            logger.error(f"Failed to create History sheet: {e2}")
            return False

def ban_user_in_batch(user_id, reason=""):
    try:
        users = get_worksheet_data_optimized("Users", use_cache=False)
        
        for i, user in enumerate(users):
            if str(user.get("User_ID")) == str(user_id):
                row_index = i + 2
                worksheet = get_worksheet("Users")
                headers = worksheet.row_values(1)
                
                if "Status" in headers:
                    col_index = headers.index("Status") + 1
                    add_to_batch("Users", "update", (row_index, col_index, "Banned"))
                
                log_history_in_batch([
                    str(datetime.now()),
                    str(user_id),
                    "Admin",
                    "User_Banned",
                    f"User banned: {reason}"
                ])
                
                return True
        
        return False
    except Exception as e:
        logger.error(f"Error banning user: {e}")
        return False

# ======================
# LOCATION FUNCTIONS
# ======================
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def can_worker_exchange(order_record, worker_id):
    try:
        assignment_time_str = order_record.get("Assignment_Timestamp")
        if not assignment_time_str:
            return True
        
        assignment_time = datetime.fromisoformat(assignment_time_str.replace('Z', '+00:00'))
        current_time = datetime.now()
        
        if (current_time - assignment_time).total_seconds() >= EXCHANGE_TIMEOUT_HOURS * 3600:
            return True
        
        assigned_worker = order_record.get("Assigned_Worker")
        if str(assigned_worker) == str(worker_id):
            return False
        
        return True
    except Exception as e:
        logger.error(f"Error checking exchange permission: {e}")
        return True

# ======================
# MESSAGE FUNCTIONS
# ======================
def get_msg(key, **kwargs):
    messages = {
        "start": "Welcome! Are you a Client, Worker, or Admin?\nእንኳን በደህና መጡ! ደንበኛ፣ ሰራተኛ ወይም አስተዳዳሪ ነዎት?",
        "worker_dashboard": "👷‍♂️ **Worker Dashboard**\n👷‍♂️ **የሰራተኛ ዳሽቦርድ**\nChoose an option:\nምርጫ ይምረጡ፡",
        "worker_job_alert": "📍 **New Job Available!**\n📍 **አዲስ ስራ አለ!**\n\nBureau: {bureau}\nCity: {city}\nRate: {rate} ETB/hour\n\nቢሮ: {bureau}\nከተማ: {city}\nክፍያ: {rate} ብር/ሰዓት",
        "worker_job_accepted": "✅ **Job Accepted!**\n✅ **ስራ ተቀበለዋል!**\n\nPlease proceed to {bureau} for check-in.\nእባክዎን ለምዝገባ ወደ {bureau} ይሂዱ።",
        "exchange_request": "🔄 **Exchange Requested**\n🔄 **መለዋወጥ ተጠየቀ**\n\nWorker {worker_name} wants to exchange positions. Available workers can accept this handover.",
        "exchange_accepted": "✅ **Exchange Accepted!**\n✅ **መለዋወጥ ተቀባይነት አግኝቷል!**\n\nPlease meet at {bureau} for handover. Share your live location when you arrive.",
        "handover_request": "🤝 **Handover Required**\n🤝 **መለዋወጥ ያስፈልጋል**\n\nPlease share your live location to confirm you're at {bureau} for handover.",
        "job_finished": "🏁 **Job Finished**\n🏁 **ስራ ተጠናቋል**\n\nClick the button below to mark this job as completed.",
        "client_handover_confirm": "📞 **Worker Ready to Handover**\n📞 **ሰራተኛ ለመለዋወጥ ዝግጁ ነው**\n\nYour worker is ready to handover the spot. Is everything okay?\n\nየእርስዎ ሰራተኛ ቦታውን ለመለዋወጥ ዝግጁ ነው። ሁሉም ነገር ተስማምቷል?",
        "payment_calculated": "💰 **Payment Calculated**\n💰 **ክፍያ ተሰልቷል**\n\nTotal Hours: {hours}\nTotal Amount: {amount} ETB\n\nጠቅላላ ሰዓት: {hours}\nጠቅላላ መጠን: {amount} ብር",
        "commission_notice": "💼 **Commission Due**\n💼 **ኮሚሽን ክፍያ**\n\nYou earned {total} ETB. Please send 25% ({commission} ETB) to {admin} within 3 hours.\n\n{total} ብር ሰርተዋል። እባክዎን 25% ({commission} ብር) ለ{admin} በ3 ሰዓት ውስጥ ይላኩ።",
        "ghost_payment": "👻 **Ghost Payment Processed**\n👻 **የጎስት ክፍያ ተከናውኗል**\n\nSince the client didn't confirm, 100 ETB has been allocated to each worker.",
        "menu_worker_dashboard": "🔍 Find Jobs\n🔍 ስራ ፈልግ\n\n📊 My Earnings\n📊 የእኔ ገቢ\n\n✏️ Profile\n✏️ መግለጫ\n\n🆘 Help/Admin\n🆘 እገዛ/አስተዳዳሪ",
        "menu_active_job": "📍 Check In\n📍 ምዝገባ\n\n🔄 Request Exchange\n🔄 መለዋወጥ ይጠይቁ\n\n🏁 Job Finished\n🏁 ስራ ጨርሰዋል\n\n📞 Contact Client\n📞 ደንበኛ ያግኙ",
        "back_to_dashboard": "↩️ Back to Dashboard\n↩️ ወደ ዳሽቦርድ ተመለስ",
        "worker_registration": "👷 **Worker Registration**\n👷 **የሰራተኛ ምዝገባ**\n\nPlease complete all steps:\nእባክዎን ሁሉንም ደረጃዎች ይጠናቀቁ፡",
        "worker_selfie": "📸 **Live Selfie Required**\n📸 **ቀጥተኛ የራስ ፎቶ ያስፈልጋል**\n\nPlease take a live selfie now (not from gallery).\nእባክዎን አሁን ቀጥተኛ የራስ ፎቶ ያንሱ (ከጋሌሪ አይደለም)።",
        "exchange_time_wait": "⏳ **Exchange Not Available Yet**\n⏳ **መለዋወጥ አሁንም አይገኝም**\n\nYou must wait {remaining} minutes before requesting exchange.\nእባክዎን የመለዋወጥ ጥያቄ ከመስጠትዎ በፊት {remaining} ደቂቃ ይጠብቁ።",
        "gps_warning": "⚠️ **Location Warning**\n⚠️ **የቦታ ማስጠንቀቂያ**\n\nYou are {distance}m away from the bureau. Return immediately!\nከቢሮ {distance}ሜ ርቀው ነዎት። ወዲያውኑ ይመለሱ!",
        "gps_ban": "🚫 **Account Banned**\n🚫 **አካውንት ታግዷል**\n\nYou moved too far from the job location. Account banned.\nከስራ ቦታ በጣም ርቀዋል። አካውንትዎ ታግዷል።",
        "user_banned": "🚫 You are banned from using Yazilign. Contact {admin} for details.\n🚫 ከያዝልኝ አገልግሎት ታግደዋል። ለዝርዝር መረጃ {admin} ያነጋግሩ።",
        "city_not_active": "🚧 Not in {city} yet. Choose Addis Ababa.\n🚧 በ{city} አይሰራም። አዲስ አበባ ይምረጡ።",
        "invalid_city": "⚠️ City name must be text only (no numbers). Please re-enter.\n⚠️ ከተማ ስሙ ፊደል ብቻ መሆን አለበት (ቁጥር ያልተካተተ)። እንደገና ይፃፉ።",
        "choose_city": "📍 Choose city:\n📍 ከተማ ይምረጡ፡",
        "enter_bureau": "📍 Type bureau name:\n📍 የቢሮ ስሙን ይፃፉ:",
        "send_location": "📍 Share live location:\n📍 ቦታዎን ያጋሩ:",
        "booking_fee": "Pay 100 ETB and upload receipt.\n100 ብር ይላክሱ እና ሲምበር ያስገቡ።",
        "worker_welcome": "👷 Send your full name:\n👷 ሙሉ ስምዎን ይላኩ:",
        "worker_phone": "📱 Send phone number:\n📱 ስልክ ቁጥርዎን ይላኩ:",
        "worker_fyda_front": "📸 Send FRONT of your Fyda (ID):\n📸 የፍይዳዎን (ID) ገጽ ፎቶ ይላኩ:",
        "worker_fyda_back": "📸 Send BACK of your Fyda (ID):\n📸 የፍይዳዎን (ID) ወለድ ፎቶ ይላኩ:",
        "admin_approve_worker": "🆕 New worker registration!\nName: {name}\nPhone: {phone}\nApprove?\n🆕 አዲስ የሰራተኛ ምዝገባ!\nስም፡ {name}\nስልክ፡ {phone}\nፀድቀው ይወስኑ?",
        "worker_approved": "✅ Approved! You'll receive job alerts soon.\n✅ ፀድቋል! በቅርቡ የስራ ማስታወቂያ ይደርስዎታል።",
        "worker_declined": "❌ Declined. Contact admin for details.\n❌ ውድቅ ተደርጓል። ለተጨማሪ መረጃ አስተዳዳሪውን ያነጋግሩ።",
        "order_created": "✅ Order created! Searching for workers...\n✅ ትዕዛዝ ተፈጥሯል! ሰራተኛ እየፈለግን ነው...",
        "worker_accepted": "✅ Worker accepted! They'll check in soon.\n✅ ሰራተኛ ተገኝቷል! በቅርቡ ያገኙዎታል።",
        "checkin_photo": "📸 Send photo of yourself in line at {bureau}\n📸 በ{bureau} ውስጥ ያለውን ፎቶ ይላኩ",
        "checkin_location": "📍 Start live location sharing now\n📍 አሁን የቀጥታ መገኛ ያጋሩ",
        "checkin_complete": "✅ Check-in complete! Client notified.\n✅ የመግቢያ ሂደት ተጠናቅቋል!",
        "location_off_alert": "⚠️ Worker's location is off!\n⚠️ የሰራተኛው መገኛ ጠፍቷል!",
        "turn_on_location": "📍 Turn On Location\n📍 መገኛን አብራ",
        "location_alert_sent": "🔔 Request sent. Worker will be notified to turn on location.\n🔔 ጥያቄ ተልኳል። ሰራተኛው መገኛውን እንዲያበራ መልዕክት ይደርሰዋል።",
        "final_hours": "How many hours did the worker wait? (Min 1, Max 12)\nሰራተኛው ምን ያህል ሰዓት ቆየ? (ቢያንስ 1፣ ከፍተኛ 12)",
        "final_payment": "💼 Pay {amount} ETB to worker and upload receipt.\n💼 ለሰራተኛ {amount} ብር ይላክሱ እና ሲምበር ያስገቡ።",
        "payment_complete": "✅ Payment confirmed! Thank you.\n✅ ክፍያ ተረጋግጧል! እናመሰግናለን።",
        "commission_request": "💰 You earned {total} ETB! Send 25% ({commission}) to {admin} within 3 hours.\n💰 {total} ብር ሰርተዋል! የ25% ኮሚሽን ({commission}) በ3 ሰዓት ውስጥ ለ {admin} ይላኩ።",
        "commission_timeout": "⏰ 1 hour left to send your 25% commission to {admin}!\n⏰ የ25% ኮሚሽን ለ{admin} ለመላክ 1 ሰዓት ብቻ ይቀራል!",
        "commission_missed": "🚨 You missed the commission deadline. Contact {admin} immediately.\n🚨 የኮሚሽን መክፈያ ጊዜ አልፏል። በአስቸኳይ {admin} ያነጋግሩ።",
        "request_new_worker": "🔄 Request New Worker\n🔄 ሌላ ሰራተኛ ይፈለግ",
        "reassign_reason": "Why do you want a new worker?\nሌላ ሰራተኛ ለምን ፈለጉ?",
        "worker_reassigned": "🔁 Job reopened. A new worker will be assigned soon.\n🔁 ስራው በድጋሚ ክፍት ሆኗል። በቅርቡ ሌላ ሰራተኛ ይመደባል።",
        "dispute_button": "⚠️ Dispute\n⚠️ ቅሬታ",
        "dispute_reason": "Select dispute reason:\nየቅሬታ ምክንያቱን ይምረጡ፡",
        "reason_no_show": "Worker didn't show\nሰራተኛው አልመጣም",
        "reason_payment": "Payment issue\nየክፍያ ችግር",
        "reason_fake_photo": "Fake photo\nሀሰተኛ ፎቶ",
        "dispute_submitted": "📄 Dispute submitted. Admin will review shortly.\n📄 ቅሬታዎ ቀርቧል። አስተዳዳሪው በቅርቡ ይመለከተዋል።",
        "rate_worker": "How would you rate this worker? (1-5 stars)\nለዚህ ሰራተኛ ምን ያህል ኮከብ ይሰጣሉ? (ከ1-5 ኮከቦች)",
        "rating_thanks": "Thank you! Your feedback helps us improve.\nእናመሰግናለን! የእርስዎ አስተያየት አገልግሎታችንን ለማሻሻል ይረዳናል።",
        "worker_far_warning": "⚠️ Worker moved >100m from job site!\n⚠️ ሠራተኛው ከሥራ ቦታ በላይ 100ሜ ተንቀሳቅሷል!",
        "worker_far_ban": "🚨 Worker moved >500m! Order cancelled & banned.\n🚨 ሠራተኛው ከሥራ ቦታ በላይ 500ሜ ተንቀሳቅሷል! ትዕዛዝ ተሰርዟል እና ታግዷል።",
        "menu_client_worker": "Client\nደንበኛ\n\nWorker\nሰራተኛ",
        "menu_login_register": "✅ Register as New Worker\n✅ አዲስ ሰራተኛ መመዝገቢያ\n\n🔑 Login as Existing Worker\n🔑 የሚገኝ ሰራተኛ መግቢያ\n\n↩️ Back to Main Menu\n↩️ ወደ ዋና ገጽ",
        "menu_update_options": "📱 Phone\n📱 ስልክ\n\n💳 Telebirr\n💳 ቴሌቢር\n\n🏦 Bank\n🏦 ባንክ\n\n🔢 Account\n🔢 አካውንት\n\n📸 Fyda Photos\n📸 የፍይዳ ፎቶዎች\n\n↩️ Back to Main Menu\n↩️ ወደ ዋና ገጽ",
        "menu_confirm_arrival": "✅ Confirm Arrival\n✅ መጣ ተብሎ ያረጋግጡ\n\n↩️ Back to Main Menu\n↩️ ወደ ዋና ገጽ",
        "menu_front_of_line": "✅ I'm at the front of the line\n✅ የመስረቃ መስመር ላይ ነኝ"
    }
    
    msg = messages.get(key, key)
    if kwargs:
        if "{admin}" in msg:
            msg = msg.replace("{admin}", ADMIN_TELEGRAM_USERNAME)
        msg = msg.format(**kwargs)
    return msg

# ======================
# PERSISTENT STATE FUNCTIONS
# ======================
def save_user_state_to_sheets(user_id, state_data):
    try:
        state_id = f"STATE_{user_id}_{int(time.time())}"
        add_to_batch("History", "append", [
            str(datetime.now()),
            f"USER_{user_id}",
            "State_Save",
            "User State Persistence",
            json.dumps(state_data)
        ])
        return True
    except Exception as e:
        logger.error(f"Error saving user state: {e}")
        return False

def load_user_state_from_sheets(user_id):
    try:
        history_data = get_worksheet_data_optimized("History", use_cache=True)
        
        user_states = []
        for record in history_data:
            if (record.get("User_ID") == f"USER_{user_id}" and 
                record.get("Action") == "State_Save"):
                try:
                    state_data = json.loads(record.get("Details", "{}"))
                    timestamp = datetime.fromisoformat(record.get("Timestamp", "").replace('Z', '+00:00'))
                    user_states.append((timestamp, state_data))
                except:
                    continue
        
        if user_states:
            user_states.sort(key=lambda x: x[0], reverse=True)
            return user_states[0][1]
        
        return {"state": STATE_NONE, "data": {}}
    except Exception as e:
        logger.error(f"Error loading user state: {e}")
        return {"state": STATE_NONE, "data": {}}

def update_persistent_user_state(user_id, state, data):
    with STATE_LOCK:
        USER_STATE[user_id] = {"state": state, "data": data}
    
    def save_async():
        try:
            save_user_state_to_sheets(user_id, {"state": state, "data": data})
        except:
            pass
    
    EXECUTOR.submit(save_async)

# ======================
# BROADCAST FUNCTIONS
# ======================
async def broadcast_job_to_workers(context: ContextTypes.DEFAULT_TYPE, order_id, bureau, city):
    try:
        active_workers = get_active_workers()
        
        if not active_workers:
            logger.warning("No active workers found for broadcasting")
            return
        
        message_text = get_msg("worker_job_alert", bureau=bureau, city=city, rate=HOURLY_RATE)
        
        sent_count = 0
        for worker in active_workers:
            try:
                telegram_id = worker.get("Telegram_ID")
                if telegram_id:
                    telegram_id_int = int(telegram_id)
                    await context.bot.send_message(
                        chat_id=telegram_id_int,
                        text=message_text,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                f"✅ Accept Job ({HOURLY_RATE} ETB/hr)\n✅ ስራ ተቀበል ({HOURLY_RATE} ብር/ሰዓት)",
                                callback_data=f"accept_{order_id}"
                            )]
                        ])
                    )
                    sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send to worker {telegram_id}: {e}")
        
        logger.info(f"Job broadcasted to {sent_count}/{len(active_workers)} workers")
        
    except Exception as e:
        logger.error(f"Error broadcasting job: {e}")

async def broadcast_exchange_request(context: ContextTypes.DEFAULT_TYPE, order_id, worker_name, bureau):
    try:
        order = get_order_by_id(order_id)
        if not order:
            return
        
        current_worker_id = order.get("Assigned_Worker")
        active_workers = get_active_workers()
        
        message_text = get_msg("exchange_request", worker_name=worker_name)
        
        sent_count = 0
        for worker in active_workers:
            worker_id = str(worker.get("Telegram_ID", ""))
            if worker_id and worker_id != str(current_worker_id):
                try:
                    await context.bot.send_message(
                        chat_id=int(worker_id),
                        text=message_text,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(
                                "✅ Accept Exchange\n✅ መለዋወጥ ተቀበል",
                                callback_data=f"exchange_accept_{order_id}"
                            )]
                        ])
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Failed to send exchange request: {e}")
        
        logger.info(f"Exchange request broadcasted to {sent_count} workers")
        
    except Exception as e:
        logger.error(f"Error broadcasting exchange request: {e}")

# ======================
# TELEGRAM HANDLERS
# ======================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    first_name = user.first_name or "User"
    username = user.username
    
    logger.info(f"Start command from user {user_id} ({first_name})")
    
    user_record = get_user_by_id(user_id)
    if user_record and user_record.get("Status") == "Banned":
        await update.message.reply_text(get_msg("user_banned"))
        return
    
    persistent_state = load_user_state_from_sheets(user_id)
    update_persistent_user_state(user_id, persistent_state.get("state", STATE_NONE), persistent_state.get("data", {}))
    
    if not user_record:
        user_data = [
            str(user_id),
            first_name,
            username or "",
            "",
            "Client",
            "Active",
            str(datetime.now()),
            str(datetime.now())
        ]
        
        try:
            users_ws = get_worksheet("Users")
            headers = users_ws.row_values(1)
            if not headers:
                headers = ["User_ID", "Full_Name", "Username", "Phone", "Role", "Status", "Created_At", "Updated_At"]
                users_ws.append_row(headers)
        except:
            pass
        
        add_to_batch("Users", "append", user_data)
        log_history_in_batch([
            str(datetime.now()),
            str(user_id),
            "User",
            "Registration",
            f"New user: {first_name} ({username})"
        ])
    
    legal_notice = (
        "ℹ️ **Yazilign Service Terms**\n"
        "• Workers are independent contractors\n"
        "• Pay only after service completion\n"
        "• 25% commission is mandatory\n"
        "• Fake photos/fraud = permanent ban\n"
        "• We are not liable for user disputes\n"
        "ℹ️ **የያዝልኝ አገልግሎት ውሎች**\n"
        "• ሠራተኞች ነፃ ተቋራጮች ናቸው\n"
        "• አገልግሎቱ ተጠናቅቋል ብለው ብቻ ይክፈሉ\n"
        "• 25% ኮሚሽን ግዴታ ነው\n"
        "• ሀሰተኛ ፎቶ/ጠላት = የዘላለም ቅጣት\n"
        "• ተጠቃሚ ግጭቶች ላይ ኃላፊነት የለንም"
    )
    
    keyboard = [["Client\nደንበኛ", "Worker\nሰራተኛ"]]
    if user_id == ADMIN_CHAT_ID:
        keyboard.append(["Admin\nአስተዳዳሪ"])
    
    await update.message.reply_text(
        f"{legal_notice}\n\n{get_msg('start')}",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="Markdown"
    )

async def show_worker_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    worker_info = get_worker_by_telegram_id(user_id)
    
    if not worker_info:
        await update.message.reply_text("⚠️ Worker not found. Please register first.\n⚠️ ሰራተኛ አልተገኘም። መጀመሪያ ይመዝገቡ።")
        return
    
    WORKER_DASHBOARD_SESSIONS[user_id] = worker_info
    
    keyboard = [
        ["🔍 Find Jobs\n🔍 ስራ ፈልግ"],
        ["📊 My Earnings\n📊 የእኔ ገቢ"],
        ["✏️ Profile\n✏️ መግለጫ"],
        ["🆘 Help/Admin\n🆘 እገዛ/አስተዳዳሪ"]
    ]
    
    await update.message.reply_text(
        get_msg("worker_dashboard"),
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    
    update_persistent_user_state(user_id, STATE_WORKER_DASHBOARD, {"worker_info": worker_info})

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = update.message.text
    
    logger.info(f"Message from {user_id}: {text}")
    
    if user_id in USER_STATE:
        state_info = USER_STATE[user_id]
    else:
        persistent_state = load_user_state_from_sheets(user_id)
        state_info = persistent_state
    
    state = state_info.get("state", STATE_NONE)
    data = state_info.get("data", {})
    
    user_record = get_user_by_id(user_id)
    if user_record and user_record.get("Status") == "Banned":
        await update.message.reply_text(get_msg("user_banned"))
        return
    
    if "Back to Dashboard" in text or "ወደ ዳሽቦርድ ተመለስ" in text:
        await show_worker_dashboard(update, context, user_id)
        return
    
    if "Back to Main Menu" in text or "ወደ ዋና ገጽ" in text:
        update_persistent_user_state(user_id, STATE_NONE, {})
        await start(update, context)
        return
    
    if user_id in WORKER_DASHBOARD_SESSIONS:
        worker_info = WORKER_DASHBOARD_SESSIONS[user_id]
        
        if "Find Jobs" in text or "ስራ ፈልግ" in text:
            orders = get_pending_orders()
            if orders:
                await update.message.reply_text(
                    f"🔍 Found {len(orders)} available jobs!\n🔍 {len(orders)} የሚገኙ ስራዎች ተገኝተዋል!\n\nYou will receive notifications when new jobs are posted.\nአዲስ ስራዎች ሲለጡ ማስታወቂያ ይደርስዎታል።"
                )
            else:
                await update.message.reply_text(
                    "🔍 No available jobs at the moment. Please wait.\n🔍 በአሁኑ ጊዜ ምንም ስራዎች የሉም። እባክዎን ይጠብቁ።"
                )
        
        elif "My Earnings" in text or "የእኔ ገቢ" in text:
            total_earnings = int(worker_info.get('Total_Earnings', 0) or 0)
            commission_paid = int(total_earnings * 0.25)
            net_income = total_earnings - commission_paid
            
            try:
                payouts = get_worksheet_data_optimized("Payouts")
                pending_payouts = sum(int(p.get("Amount", 0)) for p in payouts 
                                    if p.get("Worker_ID") == str(user_id) and p.get("Status") == "Pending")
            except:
                pending_payouts = 0
            
            earnings_text = (
                f"💰 **Earnings Summary**\n💰 **የገቢ ማጠቃለያ**\n"
                f"Total Earned/ጠቅላላ ገቢ: {total_earnings} ETB\n"
                f"Commission Paid/የተከፈለ ኮሚሽን: {commission_paid} ETB\n"
                f"Net Income/ንጹህ ገቢ: {net_income} ETB\n"
                f"Pending Payments/በጥበቃ ላይ ያሉ ክፍያዎች: {pending_payouts} ETB"
            )
            await update.message.reply_text(earnings_text, parse_mode="Markdown")
        
        elif "Profile" in text or "መግለጫ" in text:
            account_number = str(worker_info.get("Account_number", ""))
            last_four = account_number[-4:] if len(account_number) >= 4 else account_number
            
            profile_text = (
                f"👷‍♂️ **Worker Profile**\n👷‍♂️ **የሰራተኛ መግለጫ**\n"
                f"Name/ስም: {worker_info.get('Full_Name', 'N/A')}\n"
                f"Phone/ስልክ: {worker_info.get('Phone_Number', 'N/A')}\n"
                f"Telebirr/ቴሌቢር: {worker_info.get('Telebirr_number', 'N/A')}\n"
                f"Bank/ባንክ: {worker_info.get('Bank_type', 'N/A')} ••••{last_four}\n"
                f"Status/ሁኔታ: {worker_info.get('Status', 'N/A')}\n"
                f"Rating/ደረጃ: {worker_info.get('Rating', 'N/A')} ⭐\n"
                f"Jobs Completed/የተጠናቁ ስራዎች: {worker_info.get('Jobs_Completed', '0')}"
            )
            await update.message.reply_text(profile_text, parse_mode="Markdown")
        
        elif "Help/Admin" in text or "እገዛ/አስተዳዳሪ" in text:
            help_text = (
                "🆘 **Help & Support**\n🆘 **እገዛ እና ድጋፍ**\n\n"
                "For assistance, contact the admin:\nለእገዛ፣ አስተዳዳሪውን ያነጋግሩ፡\n"
                f"{ADMIN_TELEGRAM_USERNAME}\n\n"
                "Common issues:\nተደጋጋሚ ችግሮች፡\n"
                "• Job not showing? Make sure your status is 'Active'\n"
                "• Payment issues? Check your bank/Telebirr details\n"
                "• Location problems? Enable GPS and share live location\n\n"
                "• ስራ አይታይም? ሁኔታዎ 'ንቁ' መሆኑን ያረጋግጡ\n"
                "• የክፍያ ችግሮች? የባንክ/ቴሌቢር ዝርዝርዎን ያረጋግጡ\n"
                "• የቦታ ችግሮች? GPS ያብሩ እና ቀጥታ ቦታ ያጋሩ"
            )
            await update.message.reply_text(help_text, parse_mode="Markdown")
        
        return
    
    if "Client" in text or "ደንበኛ" in text:
        update_persistent_user_state(user_id, STATE_CLIENT_CITY, {})
        keyboard = []
        for city in ALL_CITIES:
            if city == "Addis Ababa":
                keyboard.append([f"{city}\nአዲስ አበባ"])
            else:
                keyboard.append([f"{city}\n{city}"])
        keyboard.append([get_msg("back_to_dashboard")])
        await update.message.reply_text(
            "📍 Choose city:\n📍 ከተማ ይምረጡ፡",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif "Worker" in text or "ሰራተኛ" in text:
        worker_info = get_worker_by_telegram_id(user_id)
        if worker_info and worker_info.get("Status") == "Active":
            await show_worker_dashboard(update, context, user_id)
        else:
            update_persistent_user_state(user_id, STATE_WORKER_NAME, {})
            keyboard = [[get_msg("back_to_dashboard")]]
            await update.message.reply_text(
                "👷 Send your full name:\n👷 ሙሉ ስምዎን ይላኩ:",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            )
    
    elif "Admin" in text and user_id == ADMIN_CHAT_ID:
        await update.message.reply_text(
            "👑 Admin Panel\n👑 የአስተዳዳሪ ፓነል\n"
            "Commands:\nትዕዛዞች፡\n"
            "/stats - Show statistics\n"
            "/flush - Flush all batch operations\n"
            "/cache - Clear cache\n"
            "/broadcast - Send message to all users"
        )
    
    elif state == STATE_CLIENT_CITY:
        city_name = text.split('\n')[0].strip()
        
        if re.search(r'\d', city_name):
            keyboard = []
            for city in ALL_CITIES:
                if city == "Addis Ababa":
                    keyboard.append([f"{city}\nአዲስ አበባ"])
                else:
                    keyboard.append([f"{city}\n{city}"])
            keyboard.append([get_msg("back_to_dashboard")])
            await update.message.reply_text(get_msg("invalid_city"))
            await update.message.reply_text(
                get_msg("choose_city"),
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return
        
        if city_name not in ACTIVE_CITIES:
            keyboard = []
            for city in ALL_CITIES:
                if city == "Addis Ababa":
                    keyboard.append([f"{city}\nአዲስ አበባ"])
                else:
                    keyboard.append([f"{city}\n{city}"])
            keyboard.append([get_msg("back_to_dashboard")])
            await update.message.reply_text(get_msg("city_not_active", city=city_name))
            await update.message.reply_text(
                get_msg("choose_city"),
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return
        
        data["city"] = city_name
        update_persistent_user_state(user_id, STATE_CLIENT_BUREAU, data)
        await update.message.reply_text(
            get_msg("enter_bureau"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_CLIENT_BUREAU:
        data["bureau"] = text.split('\n')[0].strip()
        update_persistent_user_state(user_id, STATE_CLIENT_LOCATION, data)
        await update.message.reply_text(
            get_msg("send_location"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Share Live Location\n📍 ቦታዎን ያጋሩ", request_location=True)], [get_msg("back_to_dashboard")]],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
    
    elif state == STATE_WORKER_NAME:
        data["name"] = text
        update_persistent_user_state(user_id, STATE_WORKER_PHONE, data)
        await update.message.reply_text(
            get_msg("worker_phone"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_PHONE:
        data["phone"] = text
        update_persistent_user_state(user_id, STATE_WORKER_TELEBIRR, data)
        await update.message.reply_text(
            "📱 Enter your Telebirr number:\n📱 የቴሌቢር ቁጥርዎን ይፃፉ፡",
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_TELEBIRR:
        data["telebirr"] = text
        update_persistent_user_state(user_id, STATE_WORKER_BANK, data)
        keyboard = [[f"{bank}\n{bank}"] for bank in BANKS]
        keyboard.append([get_msg("back_to_dashboard")])
        await update.message.reply_text(
            "🏦 Select your bank:\n🏦 የባንክዎን ይምረጡ፡",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_BANK:
        bank_name = text.split('\n')[0].strip()
        if bank_name not in BANKS:
            keyboard = [[f"{bank}\n{bank}"] for bank in BANKS]
            keyboard.append([get_msg("back_to_dashboard")])
            await update.message.reply_text(
                "⚠️ Please select from the bank list.\n⚠️ ከባንክ ዝርዝሩ ይምረጡ።",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return
        
        data["bank_type"] = bank_name
        update_persistent_user_state(user_id, STATE_WORKER_ACCOUNT_NUMBER, data)
        await update.message.reply_text(
            "🔢 Enter your account number:\n🔢 የአካውንት ቁጥርዎን ይፃፉ፡",
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_ACCOUNT_NUMBER:
        data["account_number"] = text
        update_persistent_user_state(user_id, STATE_WORKER_ACCOUNT_HOLDER, data)
        await update.message.reply_text(
            "👤 Enter your account holder name (as on bank):\n👤 የአካውንት ባለቤት ስም (በባንክ የሚታየው)",
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_ACCOUNT_HOLDER:
        data["account_holder"] = text
        update_persistent_user_state(user_id, STATE_WORKER_FYDA_FRONT, data)
        await update.message.reply_text(
            get_msg("worker_fyda_front"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_CLIENT_FINAL_HOURS:
        try:
            hours = int(text.split('\n')[0].strip())
            if 1 <= hours <= 12:
                data["hours"] = hours
                total = HOURLY_RATE * hours
                data["total"] = total
                update_persistent_user_state(user_id, STATE_CLIENT_FINAL_RECEIPT, data)
                await update.message.reply_text(
                    get_msg("final_payment", amount=total - 100),
                    reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], one_time_keyboard=True, resize_keyboard=True)
                )
            else:
                await update.message.reply_text(get_msg("final_hours"))
        except ValueError:
            await update.message.reply_text(get_msg("final_hours"))
    
    elif state == STATE_DISPUTE_REASON:
        reason = text
        order_id = data.get("order_id")
        
        if order_id:
            log_history_in_batch([
                str(datetime.now()),
                order_id,
                "Client",
                "Dispute_Submitted",
                f"Reason: {reason}"
            ])
            
            await update.message.reply_text(
                get_msg("dispute_submitted"),
                reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
            )
            
            update_persistent_user_state(user_id, STATE_NONE, {})
    
    elif state == STATE_RATING:
        try:
            rating = int(text.split('\n')[0].strip())
            if 1 <= rating <= 5:
                worker_id = data.get("worker_id")
                
                if worker_id:
                    workers = get_worksheet_data_optimized("Workers", use_cache=False)
                    for i, worker in enumerate(workers):
                        if str(worker.get("Telegram_ID")) == str(worker_id):
                            current_rating = float(worker.get("Rating", 3.0) or 3.0)
                            new_rating = (current_rating + rating) / 2
                            
                            row_index = i + 2
                            worksheet = get_worksheet("Workers")
                            headers = worksheet.row_values(1)
                            
                            if "Rating" in headers:
                                col_index = headers.index("Rating") + 1
                                add_to_batch("Workers", "update", (row_index, col_index, str(round(new_rating, 1))))
                            
                            break
                
                await update.message.reply_text(
                    get_msg("rating_thanks"),
                    reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
                )
                
                update_persistent_user_state(user_id, STATE_NONE, {})
            else:
                await update.message.reply_text("Please enter a rating between 1 and 5.\nእባክዎን ከ1 እስከ 5 ያለው ደረጃ ያስገቡ።")
        except ValueError:
            await update.message.reply_text("Please enter a number between 1 and 5.\nእባክዎን ከ1 እስከ 5 ያለው ቁጥር ያስገቡ።")
    
    elif state == STATE_WORKER_EXCHANGE_REQUEST:
        if "Request Exchange" in text or "መለዋወጥ ይጠይቁ" in text:
            order_id = data.get("order_id")
            
            if order_id:
                order = get_order_by_id(order_id)
                if order:
                    if can_worker_exchange(order, user_id):
                        worker_info = get_worker_by_telegram_id(user_id)
                        worker_name = worker_info.get("Full_Name", "Worker") if worker_info else "Worker"
                        bureau = order.get("Bureau_Name", "the bureau")
                        
                        await broadcast_exchange_request(context, order_id, worker_name, bureau)
                        
                        await update.message.reply_text(
                            "🔄 Exchange request sent! Other workers will be notified.\n🔄 የመለዋወጥ ጥያቄ ተልኳል! ሌሎች ሰራተኞች ይማገናሉ።",
                            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
                        )
                    else:
                        assignment_time_str = order.get("Assignment_Timestamp")
                        if assignment_time_str:
                            assignment_time = datetime.fromisoformat(assignment_time_str.replace('Z', '+00:00'))
                            current_time = datetime.now()
                            time_passed = (current_time - assignment_time).total_seconds()
                            remaining_minutes = max(0, (EXCHANGE_TIMEOUT_HOURS * 3600 - time_passed) / 60)
                            
                            await update.message.reply_text(
                                get_msg("exchange_time_wait", remaining=int(remaining_minutes)),
                                reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
                            )
    
    elif state == STATE_WORKER_AT_FRONT:
        if "I'm at the front of the line" in text or "የመስረቃ መስመር ላይ ነኝ" in text:
            order_id = data.get("order_id")
            
            if order_id:
                update_order_in_batch(order_id, {"Status": "At Front"})
                
                order = get_order_by_id(order_id)
                if order:
                    client_id = order.get("Client_TG_ID")
                    if client_id:
                        await context.bot.send_message(
                            chat_id=int(client_id),
                            text="✅ Worker is at the front of the line! Please proceed with your transaction.\n✅ ሰራተኛው የመስረቃ መስመር ላይ ነው! እባክዎን ንግድዎን ይቀጥሉ።"
                        )
                
                await update.message.reply_text(
                    "✅ Notified client! Waiting for client to complete transaction.\n✅ ደንበኛ ተማውቋል! ደንበኛ ንግዱን እንዲያጠናቅቅ በጥበቃ ላይ።",
                    reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
                )
                
                update_persistent_user_state(user_id, STATE_WORKER_JOB_FINISHED, {"order_id": order_id})
    
    elif state == STATE_WORKER_JOB_FINISHED:
        if "Job Finished" in text or "ስራ ጨርሰዋል" in text:
            order_id = data.get("order_id")
            
            if order_id:
                await update.message.reply_text(
                    "📍 Please share your live location to confirm job completion:\n📍 ስራውን እንደጨረሱ ለማረጋገጥ እባክዎን ቀጥታ ቦታዎን ያጋሩ:",
                    reply_markup=ReplyKeyboardMarkup([
                        [KeyboardButton("📍 Share Live Location\n📍 ቦታዎን ያጋሩ", request_location=True)],
                        [get_msg("back_to_dashboard")]
                    ], resize_keyboard=True)
                )
    
    elif state == STATE_CLIENT_CONFIRM_ARRIVAL:
        if "Confirm Arrival" in text or "መጣ ተብሎ ያረጋግጡ" in text:
            order_id = data.get("order_id")
            
            if order_id:
                order = get_order_by_id(order_id)
                if order:
                    worker_id = order.get("Assigned_Worker")
                    
                    update_order_in_batch(order_id, {
                        "Status": "Waiting for Payment",
                        "Booking_Fee_Paid": "Yes"
                    })
                    
                    await context.bot.send_message(
                        chat_id=int(worker_id),
                        text="✅ Client confirmed arrival! Please wait for them to complete their transaction.\n✅ ደንበኛ መጣ ብሎ አረጋግጧል! እባክዎን ንግዳቸውን እንዲያጠናቅቁ ይጠብቁ።"
                    )
                    
                    await update.message.reply_text(
                        "✅ Worker notified! Please proceed with your bureau transaction.\n✅ ሰራተኛ ተማውቋል! እባክዎን የቢሮ ንግድዎን ይቀጥሉ።",
                        reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
                    )
                    
                    update_persistent_user_state(user_id, STATE_CLIENT_MONITORING, {"order_id": order_id, "worker_id": worker_id})
    
    elif state == STATE_CLIENT_MONITORING:
        if "Request New Worker" in text or "ሌላ ሰራተኛ ይፈለግ" in text:
            order_id = data.get("order_id")
            
            if order_id:
                update_persistent_user_state(user_id, STATE_DISPUTE_REASON, {"order_id": order_id})
                
                keyboard = [
                    [get_msg("reason_no_show")],
                    [get_msg("reason_payment")],
                    [get_msg("reason_fake_photo")],
                    [get_msg("back_to_dashboard")]
                ]
                
                await update.message.reply_text(
                    get_msg("reassign_reason"),
                    reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
                )
    
    elif state == STATE_WORKER_CHECKIN_PHOTO:
        # Handled in photo handler
        pass
    
    elif state == STATE_WORKER_UPDATE_PHONE:
        data["new_phone"] = text
        worker_info = get_worker_by_telegram_id(user_id)
        
        if worker_info:
            workers = get_worksheet_data_optimized("Workers", use_cache=False)
            for i, worker in enumerate(workers):
                if str(worker.get("Telegram_ID")) == str(user_id):
                    row_index = i + 2
                    worksheet = get_worksheet("Workers")
                    headers = worksheet.row_values(1)
                    
                    if "Phone_Number" in headers:
                        col_index = headers.index("Phone_Number") + 1
                        add_to_batch("Workers", "update", (row_index, col_index, text))
                    
                    await update.message.reply_text(
                        "✅ Phone number updated!\n✅ የስልክ ቁጥር ተሻሽሏል!",
                        reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
                    )
                    
                    update_persistent_user_state(user_id, STATE_NONE, {})
                    break
    
    elif state == STATE_WORKER_UPDATE_TELEBIRR:
        data["new_telebirr"] = text
        worker_info = get_worker_by_telegram_id(user_id)
        
        if worker_info:
            workers = get_worksheet_data_optimized("Workers", use_cache=False)
            for i, worker in enumerate(workers):
                if str(worker.get("Telegram_ID")) == str(user_id):
                    row_index = i + 2
                    worksheet = get_worksheet("Workers")
                    headers = worksheet.row_values(1)
                    
                    if "Telebirr_number" in headers:
                        col_index = headers.index("Telebirr_number") + 1
                        add_to_batch("Workers", "update", (row_index, col_index, text))
                    
                    await update.message.reply_text(
                        "✅ Telebirr number updated!\n✅ የቴሌቢር ቁጥር ተሻሽሏል!",
                        reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
                    )
                    
                    update_persistent_user_state(user_id, STATE_NONE, {})
                    break
    
    else:
        await update.message.reply_text(
            "Please use the menu buttons.\nእባክዎን የምና ቁልፎችን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if not update.message.photo:
        return
    
    photo_file_id = update.message.photo[-1].file_id
    
    if user_id in USER_STATE:
        state_info = USER_STATE[user_id]
    else:
        persistent_state = load_user_state_from_sheets(user_id)
        state_info = persistent_state
    
    state = state_info.get("state", STATE_NONE)
    data = state_info.get("data", {})
    
    if state == STATE_WORKER_FYDA_FRONT:
        data["fyda_front"] = photo_file_id
        update_persistent_user_state(user_id, STATE_WORKER_FYDA_BACK, data)
        await update.message.reply_text(
            get_msg("worker_fyda_back"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_FYDA_BACK:
        data["fyda_back"] = photo_file_id
        update_persistent_user_state(user_id, STATE_WORKER_SELFIE, data)
        await update.message.reply_text(
            get_msg("worker_selfie"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], one_time_keyboard=True, resize_keyboard=True)
        )
    
    elif state == STATE_WORKER_SELFIE:
        data["selfie"] = photo_file_id
        worker_id = f"WRK{str(uuid4())[:8].upper()}"
        
        add_to_batch("Workers", "append", [
            worker_id,
            data.get("name", ""),
            data.get("phone", ""),
            str(user_id),
            "0",
            "0",
            "Pending",
            data.get("telebirr", ""),
            data.get("bank_type", ""),
            data.get("account_number", ""),
            data.get("account_holder", ""),
            "3.0",
            str(datetime.now())
        ])
        
        log_history_in_batch([
            str(datetime.now()),
            worker_id,
            "Worker",
            "Registration",
            f"New worker: {data.get('name', '')}"
        ])
        
        caption = get_msg("admin_approve_worker", name=data.get("name", ""), phone=data.get("phone", ""))
        
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_file_id,
            caption=caption,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{worker_id}")],
                [InlineKeyboardButton("❌ Decline", callback_data=f"decline_{user_id}")]
            ])
        )
        
        await update.message.reply_text(
            "📄 Registration submitted! Waiting for admin approval.\n📄 ምዝገባ ቀርቧል! የአስተዳዳሪ ማረጋገጫ በጥበቃ ላይ።"
        )
        
        update_persistent_user_state(user_id, STATE_NONE, {})
    
    elif state == STATE_WORKER_CHECKIN_PHOTO:
        data["checkin_photo"] = photo_file_id
        update_persistent_user_state(user_id, STATE_WORKER_CHECKIN_LOCATION, data)
        
        await update.message.reply_text(
            "📍 Now share your live location:\n📍 አሁን ቀጥታ ቦታዎን ያጋሩ:",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("📍 Share Live Location\n📍 ቦታዎን ያጋሩ", request_location=True)],
                [get_msg("back_to_dashboard")]
            ], resize_keyboard=True)
        )
    
    elif state == STATE_CLIENT_BOOKING_RECEIPT:
        worker_id = data.get("assigned_worker")
        if not worker_id:
            await update.message.reply_text("⚠️ No worker assigned. Please wait for a worker first.\n⚠️ ሰራተኛ አልተመደበም።")
            return
        
        workers = get_worksheet_data_optimized("Workers")
        worker_info = None
        for wr in workers:
            if str(wr.get("Worker_ID")) == str(worker_id):
                worker_info = wr
                break
        if not worker_info:
            await update.message.reply_text("⚠️ Worker not found.\n⚠️ ሰራተኛ አልተገኘም።")
            return
        
        caption = (
            f"🆕 PAYMENT VERIFICATION NEEDED\n🆕 የክፍያ ማረጋገጫ ያስፈልጋል\n"
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
        
        order_updates = {"Payment_Status": "Fully Paid"}
        if order_id:
            update_order_in_batch(order_id, order_updates)
        
        try:
            await context.bot.send_message(
                chat_id=int(worker_id),
                text=get_msg("commission_request", total=total, commission=commission)
            )
        except Exception as e:
            logger.error(f"Commission notification error: {e}")
        
        update_persistent_user_state(user_id, STATE_RATING, {"worker_id": worker_id})
        await update.message.reply_text(
            get_msg("rate_worker"),
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
        )
    
    else:
        await update.message.reply_text(
            "I don't understand what to do with this photo. Please use the menu.\nይህን ፎቶ ምን ማድረግ እንዳለብኝ አላውቅም። እባክዎን ምናውን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
        )

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if not update.message or not update.message.location:
        return
    
    location = update.message.location
    lat = location.latitude
    lon = location.longitude
    
    logger.info(f"Location from {user_id}: {lat}, {lon}")
    
    if user_id in USER_STATE:
        state_info = USER_STATE[user_id]
    else:
        persistent_state = load_user_state_from_sheets(user_id)
        state_info = persistent_state
    
    state = state_info.get("state", STATE_NONE)
    data = state_info.get("data", {})
    
    if state == STATE_CLIENT_LOCATION:
        data["location"] = (lat, lon)
        data["username"] = update.effective_user.username or ""
        order_id = f"YZL-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:4].upper()}"
        
        logger.info(f"Creating new order {order_id} for client {user_id}")
        
        create_order_in_batch([
            order_id,
            str(datetime.now()),
            data.get("username", ""),
            data.get("bureau", ""),
            "Pending",
            "",
            str(HOURLY_RATE),
            "No",
            "No",
            "Pending",
            str(datetime.now()),
            str(user_id),
            data.get("bureau", ""),
            data.get("city", ""),
            "1",
            str(HOURLY_RATE)
        ])
        
        log_history_in_batch([
            str(datetime.now()),
            order_id,
            "Order",
            "Created",
            f"Client {user_id} created order for {data.get('bureau', '')}"
        ])
        
        await update.message.reply_text(
            "✅ Order created! Notifying workers...\n✅ ትዕዛዝ ተፈጥሯል! ሰራተኛ እየፈለግን ነው..."
        )
        
        await broadcast_job_to_workers(context, order_id, data.get("bureau", ""), data.get("city", ""))
        
        update_persistent_user_state(user_id, STATE_NONE, {})
    
    elif state == STATE_WORKER_CHECKIN_LOCATION:
        data["checkin_location"] = (lat, lon)
        order_id = data.get("order_id")
        bureau = data.get("bureau", "")
        
        if order_id:
            update_order_in_batch(order_id, {"Status": "Checked In"})
            
            order = get_order_by_id(order_id)
            if order:
                client_id = order.get("Client_TG_ID")
                if client_id:
                    try:
                        await context.bot.send_message(
                            chat_id=int(client_id),
                            text="✅ Worker checked in! Live location active.\n✅ ሠራተኛ ተገኝቷል! የቀጥታ መገኛ አንስቶ ነው።"
                        )
                    except Exception as e:
                        logger.error(f"Client notification error: {e}")
            
            keyboard = [
                ["✅ I'm at the front of the line\n✅ የመስረቃ መስመር ላይ ነኝ"],
                [get_msg("back_to_dashboard")]
            ]
            await update.message.reply_text(
                "✅ Check-in complete! When you reach the front of the line, press the button below.\n✅ የመግቢያ ሂደት ተጠናቅቋል! የመስረቃ መስመር ላይ ሲደርሱ ከታች ያለውን ቁልፍ ይጫኑ።",
                reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            update_persistent_user_state(user_id, STATE_WORKER_AT_FRONT, {"order_id": order_id})
        else:
            await update.message.reply_text(
                "⚠️ Could not find your assigned order. Please contact admin.\n⚠️ የተመደበልዎ ትዕዛዝ ሊገኝ አልቻለም። አስተዳዳሪውን ያነጋግሩ።"
            )
    
    elif state == STATE_WORKER_EXCHANGE_CONFIRM:
        order_id = data.get("order_id")
        bureau = data.get("bureau", "")
        
        if order_id:
            order = get_order_by_id(order_id)
            if order:
                client_id = order.get("Client_TG_ID")
                if client_id:
                    await context.bot.send_message(
                        chat_id=int(client_id),
                        text=get_msg("client_handover_confirm"),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Confirm & Pay", callback_data=f"client_confirm_{order_id}")],
                            [InlineKeyboardButton("❌ Report Issue", callback_data=f"client_report_{order_id}")]
                        ])
                    )
                    
                    update_persistent_user_state(int(client_id), STATE_CLIENT_HANDOVER_CONFIRM, {
                        "order_id": order_id,
                        "worker_id": user_id
                    })
                    
                    await update.message.reply_text(
                        "✅ Location shared! Waiting for client confirmation.\n✅ ቦታ ተጋርቷል! የደንበኛ ማረጋገጫ በጥበቃ ላይ።",
                        reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
                    )
    
    elif state == STATE_WORKER_JOB_FINISHED:
        order_id = data.get("order_id")
        
        if order_id:
            order = get_order_by_id(order_id)
            if order:
                client_id = order.get("Client_TG_ID")
                if client_id:
                    await context.bot.send_message(
                        chat_id=int(client_id),
                        text=get_msg("client_handover_confirm"),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Confirm & Pay", callback_data=f"client_confirm_{order_id}")],
                            [InlineKeyboardButton("❌ Report Issue", callback_data=f"client_report_{order_id}")]
                        ])
                    )
                    
                    update_persistent_user_state(int(client_id), STATE_CLIENT_HANDOVER_CONFIRM, {
                        "order_id": order_id,
                        "worker_id": user_id
                    })
                    
                    await update.message.reply_text(
                        "✅ Location verified! Waiting for client confirmation.\n✅ ቦታ ተረጋግጧል! የደንበኛ ማረጋገጫ በጥበቃ ላይ።",
                        reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
                    )
    
    else:
        await update.message.reply_text(
            "Location received, but I'm not sure what to do with it. Please use the menu.\nመገኛዎ ተቀበልኩ፣ ነገር ግን ምን ማድረግ እንዳለብኝ አላውቅም። እባክዎን ምናውን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup([[get_msg("back_to_dashboard")]], resize_keyboard=True)
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = user.id
    
    data = query.data
    logger.info(f"Callback from {user_id}: {data}")
    
    if data.startswith("accept_"):
        order_id = data.replace("accept_", "")
        
        orders_data = bulk_get_sheets_data(["Orders", "Workers"])
        order = None
        
        for o in orders_data.get("Orders", []):
            if o.get("Order_ID") == order_id:
                order = o
                break
        
        if not order:
            await query.edit_message_text("⚠️ Job no longer available.\n⚠️ ስራው አሁን የለም።")
            return
        
        if order.get("Status") != "Pending":
            await query.edit_message_text("⚠️ Job already taken.\n⚠️ ስራው ቀድሞውኑ ተወስዷል።")
            return
        
        worker_info = None
        for worker in orders_data.get("Workers", []):
            if str(worker.get("Telegram_ID")) == str(user_id):
                worker_info = worker
                break
        
        if not worker_info:
            await query.edit_message_text("⚠️ Worker not found. Please register first.\n⚠️ ሰራተኛ አልተገኘም። መጀመሪያ ይመዝገቡ።")
            return
        
        success = update_order_in_batch(order_id, {
            "Status": "Assigned",
            "Assigned_Worker": str(user_id),
            "Assignment_Timestamp": str(datetime.now())
        })
        
        if success:
            log_history_in_batch([
                str(datetime.now()),
                order_id,
                "Order",
                "Assigned",
                f"Assigned to worker {user_id}"
            ])
            
            bureau = order.get("Bureau_Name", "the bureau")
            
            update_persistent_user_state(user_id, STATE_WORKER_ACTIVE_JOB, {
                "order_id": order_id,
                "bureau": bureau,
                "assignment_time": str(datetime.now())
            })
            
            keyboard = [
                ["📍 Check In\n📍 ምዝገባ"],
                ["🔄 Request Exchange\n🔄 መለዋወጥ ይጠይቁ"],
                ["🏁 Job Finished\n🏁 ስራ ጨርሰዋል"],
                [get_msg("back_to_dashboard")]
            ]
            
            await context.bot.send_message(
                chat_id=user_id,
                text=get_msg("worker_job_accepted", bureau=bureau),
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            )
            
            client_id = order.get("Client_TG_ID")
            if client_id:
                worker_name = worker_info.get("Full_Name", "Worker")
                await context.bot.send_message(
                    chat_id=int(client_id),
                    text=f"✅ Worker assigned!\n✅ ሰራተኛ ተመድቧል!\n\nName/ስም: {worker_name}\nPhone/ስልክ: {worker_info.get('Phone_Number', 'N/A')}\n\nThey are on their way to {bureau}.\nወደ {bureau} በመምጣት ላይ ናቸው።"
                )
            
            await query.edit_message_text(
                f"✅ You've accepted this job!\n✅ ይህን ስራ ተቀብለዋል!\n📍 Bureau/ቢሮ: {bureau}"
            )
            
            logger.info(f"Worker {user_id} accepted order {order_id}")
        else:
            await query.edit_message_text("⚠️ Error accepting job. Please try again.\n⚠️ ስራ መቀበል ላይ ስህተት። እንደገና ይሞክሩ።")
    
    elif data.startswith("exchange_accept_"):
        order_id = data.replace("exchange_accept_", "")
        order = get_order_by_id(order_id)
        
        if not order:
            await query.edit_message_text("⚠️ Exchange no longer available.\n⚠️ መለዋወጥ አሁን የለም።")
            return
        
        if order.get("Status") != "Assigned":
            await query.edit_message_text("⚠️ Exchange already completed.\n⚠️ መለዋወጥ ቀድሞውኑ ተጠናቅቋል።")
            return
        
        worker_info = get_worker_by_telegram_id(user_id)
        if not worker_info:
            await query.edit_message_text("⚠️ Worker not found.\n⚠️ ሰራተኛ አልተገኘም።")
            return
        
        bureau = order.get("Bureau_Name", "the bureau")
        
        log_history_in_batch([
            str(datetime.now()),
            order_id,
            "Exchange",
            f"From Worker {order.get('Assigned_Worker')} to Worker {user_id}",
            bureau
        ])
        
        success = update_order_in_batch(order_id, {
            "Assigned_Worker": str(user_id),
            "Assignment_Timestamp": str(datetime.now())
        })
        
        if success:
            await context.bot.send_message(
                chat_id=user_id,
                text=get_msg("exchange_accepted", bureau=bureau),
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("📍 Share Live Location\n📍 ቦታዎን ያጋሩ", request_location=True)],
                    [get_msg("back_to_dashboard")]
                ], resize_keyboard=True)
            )
            
            update_persistent_user_state(user_id, STATE_WORKER_EXCHANGE_CONFIRM, {
                "order_id": order_id,
                "bureau": bureau
            })
            
            original_worker = order.get("Assigned_Worker")
            if original_worker:
                await context.bot.send_message(
                    chat_id=int(original_worker),
                    text=f"✅ Exchange accepted! Please meet at {bureau} for handover.\n✅ መለዋወጥ ተቀባይነት አግኝቷል! ለመለዋወጥ በ{bureau} ይገናኙ።"
                )
            
            await query.edit_message_text("✅ Exchange accepted! Please proceed to the bureau.\n✅ መለዋወጥ ተቀባይነት አግኝቷል! እባክዎን ወደ ቢሮ ይሂዱ።")
            
            logger.info(f"Worker {user_id} accepted exchange for order {order_id}")
    
    elif data.startswith("client_confirm_"):
        order_id = data.replace("client_confirm_", "")
        order = get_order_by_id(order_id)
        
        if order:
            hours = int(order.get("Total_Hours", 1))
            total_amount = hours * HOURLY_RATE
            
            update_order_in_batch(order_id, {"Status": "Completed"})
            
            worker_id = order.get("Assigned_Worker")
            
            worker_amount = int(total_amount * 0.75)
            create_payout_in_batch([
                str(datetime.now()),
                order_id,
                str(worker_id),
                str(worker_amount),
                "Worker Payment",
                "Pending",
                ""
            ])
            
            commission = int(total_amount * COMMISSION_PERCENT)
            create_payout_in_batch([
                str(datetime.now()),
                order_id,
                "ADMIN",
                str(commission),
                "Commission",
                "Pending",
                ""
            ])
            
            await context.bot.send_message(
                chat_id=int(worker_id),
                text=get_msg("payment_calculated", hours=hours, amount=worker_amount) + "\n\n" +
                     get_msg("commission_notice", total=total_amount, commission=commission)
            )
            
            await query.edit_message_text("✅ Payment confirmed! Thank you for using Yazilign.\n✅ ክፍያ ተረጋግጧል! ያዝልኝን ስለተጠቀሙ እናመሰግናለን።")
            
            logger.info(f"Order {order_id} completed. Worker {worker_id} earned {worker_amount} ETB")
    
    elif data.startswith("client_report_"):
        order_id = data.replace("client_report_", "")
        
        await query.edit_message_text("⚠️ Issue reported. Admin will review shortly.\n⚠️ ችግር ሪፖርት ተደርጓል። አስተዳዳሪው በቅርቡ ይመለከተዋል።")
        
        log_history_in_batch([
            str(datetime.now()),
            order_id,
            "Client",
            "Issue_Reported",
            "Client reported issue with handover"
        ])
    
    elif data.startswith("approve_"):
        parts = data.split("_")
        if len(parts) < 3:
            return
        
        worker_tg_id = parts[1]
        worker_db_id = parts[2]
        
        workers = get_worksheet_data_optimized("Workers", use_cache=False)
        
        for i, worker in enumerate(workers):
            if worker.get("Worker_ID") == worker_db_id:
                row_index = i + 2
                worksheet = get_worksheet("Workers")
                headers = worksheet.row_values(1)
                
                if "Status" in headers:
                    col_index = headers.index("Status") + 1
                    add_to_batch("Workers", "update", (row_index, col_index, "Active"))
                
                await context.bot.send_message(
                    chat_id=int(worker_tg_id), 
                    text=get_msg("worker_approved")
                )
                await query.edit_message_caption(caption="✅ Approved!\n✅ ተፈቅዶልናል!")
                break
    
    elif data.startswith("decline_"):
        if len(data.split("_")) < 2:
            return
        
        worker_tg_id = data.split("_")[1]
        
        workers = get_worksheet_data_optimized("Workers", use_cache=False)
        
        for i, worker in enumerate(workers):
            if str(worker.get("Telegram_ID")) == str(worker_tg_id):
                row_index = i + 2
                worksheet = get_worksheet("Workers")
                headers = worksheet.row_values(1)
                
                if "Status" in headers:
                    col_index = headers.index("Status") + 1
                    add_to_batch("Workers", "update", (row_index, col_index, "Declined"))
                
                await context.bot.send_message(
                    chat_id=int(worker_tg_id), 
                    text=get_msg("worker_declined")
                )
                await query.edit_message_caption(caption="❌ Declined.\n❌ ተውግዷል።")
                break
    
    elif data.startswith("verify_"):
        parts = data.split("_")
        if len(parts) < 3:
            return
        
        client_id = int(parts[1])
        worker_id = parts[2]
        
        orders = get_worksheet_data_optimized("Orders", use_cache=False)
        
        for i, order in enumerate(orders):
            if str(order.get("Client_TG_ID")) == str(client_id) and order.get("Status") == "Assigned":
                row_index = i + 2
                worksheet = get_worksheet("Orders")
                headers = worksheet.row_values(1)
                
                if "Booking_Fee_Paid" in headers:
                    col_index = headers.index("Booking_Fee_Paid") + 1
                    add_to_batch("Orders", "update", (row_index, col_index, "Yes"))
                
                if "Status" in headers:
                    col_index = headers.index("Status") + 1
                    add_to_batch("Orders", "update", (row_index, col_index, "Verified"))
                
                await context.bot.send_message(
                    chat_id=client_id, 
                    text="✅ Payment verified! Job proceeding.\n✅ ክፍያ ተረጋግጧል! ስራ ተከዋል።"
                )
                await query.edit_message_caption(caption="✅ Verified!\n✅ ተረጋግጧል!")
                break
    
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
        if user_id in USER_STATE:
            state_info = USER_STATE[user_id]
        else:
            persistent_state = load_user_state_from_sheets(user_id)
            state_info = persistent_state
            
        order_id = state_info["data"].get("order_id")
        if order_id:
            order = get_order_by_id(order_id)
            if order:
                worker_id = order.get("Assigned_Worker")
                await context.bot.send_message(
                    chat_id=int(worker_id),
                    text="🔔 Client requested live location. Please turn it on now.\n🔔 ደንበኛው የቀጥታ መገኛ ጠየቀ። አሁን ያብሩ።"
                )
                await query.message.reply_text("📍 Request sent to worker.\n📍 ጥያቄ ለሰራተኛ ተልኳል።")

# ======================
# ADMIN COMMANDS
# ======================
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        return
    
    try:
        all_data = bulk_get_sheets_data(["Users", "Workers", "Orders", "Payouts"])
        
        users = all_data.get("Users", [])
        workers = all_data.get("Workers", [])
        orders = all_data.get("Orders", [])
        payouts = all_data.get("Payouts", [])
        
        active_users = len([u for u in users if u.get("Status") == "Active"])
        active_workers = len([w for w in workers if w.get("Status") == "Active"])
        pending_orders = len([o for o in orders if o.get("Status") in ["Pending", "Assigned"]])
        completed_orders = len([o for o in orders if o.get("Status") == "Completed"])
        
        total_revenue = 0
        for order in orders:
            if order.get("Status") == "Completed":
                hours = int(order.get("Total_Hours", 1))
                total_revenue += hours * HOURLY_RATE
        
        pending_payouts = sum(int(p.get("Amount", 0)) for p in payouts if p.get("Status") == "Pending")
        batch_queue_size = sum(len(ops) for ops in BATCH_OPERATIONS.values())
        
        stats_text = (
            f"📊 **Yazilign Statistics**\n\n"
            f"👥 **Users**: {len(users)} (Active: {active_users})\n"
            f"👷 **Workers**: {len(workers)} (Active: {active_workers})\n"
            f"📦 **Orders**: {len(orders)} (Pending: {pending_orders}, Completed: {completed_orders})\n"
            f"💰 **Revenue**: {total_revenue} ETB\n"
            f"💸 **Pending Payouts**: {pending_payouts} ETB\n"
            f"📝 **Batch Queue**: {batch_queue_size} operations\n"
            f"🕐 **Cache Age**: {(datetime.now() - LAST_BATCH_FLUSH).seconds}s\n"
            f"💾 **Memory States**: {len(USER_STATE)} users"
        )
        
        await update.message.reply_text(stats_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text(f"⚠️ Error: {str(e)}")

async def admin_flush(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        return
    
    try:
        flush_all_batches()
        await update.message.reply_text("✅ All batches flushed to sheets!")
    except Exception as e:
        logger.error(f"Flush error: {e}")
        await update.message.reply_text(f"⚠️ Flush error: {str(e)}")

async def admin_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        return
    
    try:
        invalidate_cache()
        await update.message.reply_text("✅ Cache cleared!")
    except Exception as e:
        logger.error(f"Cache clear error: {e}")
        await update.message.reply_text(f"⚠️ Cache error: {str(e)}")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        return
    
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /broadcast <message>\nExample: /broadcast Hello all users!")
            return
        
        message = " ".join(args)
        users = get_worksheet_data_optimized("Users")
        
        sent_count = 0
        for user in users:
            if user.get("Status") == "Active":
                try:
                    telegram_id = int(user.get("User_ID", 0))
                    if telegram_id:
                        await context.bot.send_message(
                            chat_id=telegram_id,
                            text=f"📢 **Admin Broadcast**\n\n{message}\n\n📢 **የአስተዳዳሪ ማስተላለፊያ**\n\n{message}"
                        )
                        sent_count += 1
                except:
                    continue
        
        await update.message.reply_text(f"✅ Broadcast sent to {sent_count} users!")
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        await update.message.reply_text(f"⚠️ Broadcast error: {str(e)}")

# ======================
# BACKGROUND TASKS
# ======================
def run_background_tasks():
    """Run background tasks in a separate thread"""
    def task_loop():
        while True:
            try:
                with BATCH_LOCK:
                    current_time = datetime.now()
                    time_since_flush = (current_time - LAST_BATCH_FLUSH).total_seconds()
                    
                    if time_since_flush >= BATCH_FLUSH_INTERVAL:
                        flush_all_batches()
                        logger.info("Auto-flushed batches")
                
                if datetime.now().minute == 0:
                    orders = get_worksheet_data_optimized("Orders")
                    current_time = datetime.now()
                    
                    for order in orders:
                        if order.get("Status") == "Assigned":
                            assignment_time_str = order.get("Assignment_Timestamp")
                            if assignment_time_str:
                                try:
                                    assignment_time = datetime.fromisoformat(assignment_time_str.replace('Z', '+00:00'))
                                    hours_passed = (current_time - assignment_time).total_seconds() / 3600
                                    
                                    if hours_passed > 12:
                                        order_id = order.get("Order_ID")
                                        worker_id = order.get("Assigned_Worker")
                                        
                                        update_order_in_batch(order_id, {"Status": "Ghosted"})
                                        
                                        create_payout_in_batch([
                                            str(datetime.now()),
                                            order_id,
                                            str(worker_id),
                                            "100",
                                            "Ghost Payment",
                                            "Pending",
                                            ""
                                        ])
                                        
                                        logger.info(f"Order {order_id} marked as ghosted")
                                except:
                                    continue
                
                if datetime.now().minute % 30 == 0:
                    payouts = get_worksheet_data_optimized("Payouts")
                    current_time = datetime.now()
                    
                    for payout in payouts:
                        if payout.get("Type") == "Commission" and payout.get("Status") == "Pending":
                            timestamp_str = payout.get("Timestamp")
                            if timestamp_str:
                                try:
                                    payout_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                    hours_passed = (current_time - payout_time).total_seconds() / 3600
                                    
                                    if hours_passed >= 2 and hours_passed < 3:
                                        worker_id = payout.get("Worker_ID")
                                        amount = payout.get("Amount", "0")
                                        
                                        logger.info(f"Commission reminder for worker {worker_id}: {amount} ETB due in 1 hour")
                                except:
                                    continue
                
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"Background task error: {e}")
                time.sleep(60)
    
    bg_thread = Thread(target=task_loop, daemon=True)
    bg_thread.start()
    logger.info("✅ Background tasks started")

# ======================
# APPLICATION SETUP
# ======================
def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("🚀 YAZILIGN BOT STARTING")
    logger.info(f"🤖 Token: {'*' * 20}{BOT_TOKEN[-4:] if BOT_TOKEN else 'NONE'}")
    logger.info(f"👑 Admin: {ADMIN_CHAT_ID}")
    logger.info(f"📊 Sheet: {SHEET_ID[:10]}..." if SHEET_ID else "📊 Sheet: NONE")
    logger.info(f"🌐 Port: {PORT}")
    logger.info("=" * 60)
    
    # Start background tasks
    run_background_tasks()
    
    logger.info("🤖 Starting bot in polling mode...")
    
    try:
        application = Application.builder() \
            .token(BOT_TOKEN) \
            .concurrent_updates(True) \
            .get_updates_read_timeout(30) \
            .get_updates_write_timeout(30) \
            .get_updates_connect_timeout(30) \
            .pool_timeout(30) \
            .read_timeout(30) \
            .write_timeout(30) \
            .build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stats", admin_stats))
        application.add_handler(CommandHandler("flush", admin_flush))
        application.add_handler(CommandHandler("cache", admin_cache))
        application.add_handler(CommandHandler("broadcast", admin_broadcast))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.LOCATION, handle_location))
        application.add_handler(CallbackQueryHandler(handle_callback))
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        logger.info("✅ Bot application created successfully")
        
        # Start a simple HTTP server for Render health checks
        def start_http_server():
            from http.server import HTTPServer, BaseHTTPRequestHandler
            
            class HealthHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    response = json.dumps({"status": "healthy", "bot": "running"}).encode()
                    self.wfile.write(response)
                
                def log_message(self, format, *args):
                    pass
            
            server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
            logger.info(f"🌐 HTTP health server started on port {PORT}")
            server.serve_forever()
        
        http_thread = Thread(target=start_http_server, daemon=True)
        http_thread.start()
        
        # Start bot polling
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "edited_message"]
        )
        
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()
