import os
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.errors import HttpError
from typing import List, Dict, Any, Optional
import json
import re

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
AWAITING_OFFICE, AWAITING_CITY, AWAITING_LOCATION, AWAITING_WORKER_ACCEPTANCE, AWAITING_PAYMENT = range(5)

# Define admin states
AWAITING_DECLINE_REASON = 1

# Approved cities
APPROVED_CITIES = [
    "Addis Ababa", "Hawassa", "Dire Dawa", "Mekelle", "Bahir Dar"
]

# Bilingual message system
MESSAGES = {
    'searching_workers': {
        'en': '🔍 Searching for workers…',
        'am': '🔍 ሰራተኞችን በመፈለግ ላይ…'
    },
    'worker_accepted_en': {
        'en': '✅ Worker accepted! Send 700 ETB to [CBE] and upload payment receipt.',
        'am': ''
    },
    'worker_accepted_am': {
        'en': '',
        'am': '✅ ሠራተኛ ተቀበለ! 700 ብር ይላክሱ እና ሲምበር ያስገቡ'
    },
    'invalid_receipt': {
        'en': 'Invalid receipt',
        'am': 'ያልሰለጠነ ሲምበር'
    },
    'receipt_declined': {
        'en': 'Receipt declined. Please try again.',
        'am': 'ሲምበሩ ተቀባይነት አላገኘም። እባክዎ እንደገና ይሞክሩ።'
    },
    'payment_confirmed': {
        'en': 'Payment confirmed! Worker will contact you soon.',
        'am': 'ክፍያ ተረጋግጧል! ሰራተኛዎ በቅርቡ ይደውሉልዎታል።'
    },
    'registration_welcome': {
        'en': 'Welcome! Please provide your full name.',
        'am': 'እንኳን ደህና መጡ! እባክዎ ሙሉ ስምዎን ያስገቡ።'
    },
    'enter_phone': {
        'en': 'Please provide your phone number.',
        'am': 'እባክዎ ስልክ ቁጥርዎን ያስገቡ።'
    },
    'registration_complete': {
        'en': 'Thank you! Your information has been submitted for review. You will be notified when approved.',
        'am': 'አመሰግናለሁ! መረጃዎ ለቅለ ተልኳል። ሲፃድ ይሳተማሉ።'
    },
    'not_approved': {
        'en': 'Your account is not yet approved. Please wait for admin approval.',
        'am': 'መለያዎ አሁንም አልፅድቀውም። ለአስተዳደር ፅድቅ ይጠብቁ።'
    },
    'job_posted': {
        'en': 'New job available!',
        'am': 'አዲስ ስራ ይገኛል!'
    },
    'order_accepted': {
        'en': 'You have accepted this order. Please contact the client.',
        'am': 'ይህን ትዕዛዝ ተቀብለዋል። እባክዎ ገዢውን ያነጋግሩ።'
    },
    'client_notified': {
        'en': 'Client has been notified of your acceptance.',
        'am': 'ገዢዎ ለቀበሉት ተሳታቷል።'
    },
    'receipt_received': {
        'en': 'Payment receipt received for order',
        'am': 'የክፍያ ሲምበር ተቀብሏል ለትዕዛዝ'
    },
    'receipt_approved': {
        'en': '✅ Receipt approved! Order marked as paid.',
        'am': '✅ ሲምበሩ ተቀብሏል! ትዕዛዙ እንደ የተከፈለ ተመዝግቧል።'
    },
    'receipt_declined': {
        'en': '❌ Receipt declined. Reason: ',
        'am': '❌ ሲምበሩ ተቀባይነት አላገኘም። ምክንያት: '
    },
    'dispute_logged': {
        'en': 'Dispute logged in history.',
        'am': 'ውይይቱ በታሪክ ውስጥ ተመዝግቧል።'
    },
    'invalid_receipt': {
        'en': 'Invalid receipt',
        'am': 'ያልሰለጠነ ሲምበር'
    },
    'wrong_amount': {
        'en': 'Wrong amount',
        'am': 'የተሳሳተ መጠን'
    },
    'receipt_uploaded': {
        'en': 'Receipt uploaded for review',
        'am': 'ሲምበሩ ለቅለ ተጭኗል'
    },
    'not_operating_city': {
        'en': '🚧 We\'re not operating in {city} yet! Expanding soon. Please choose Addis Ababa.',
        'am': '🚧 በ {city} ውስጥ አሁን የለም! በቅርቡ እየተዘረገተ ነው። እባክዎ አዲስ አበባ ይምረጡ።'
    },
    'worker_arrived': {
        'en': 'Worker arrived!',
        'am': 'ሰራተኛ ተመልቷል!'
    },
    'location_off_warning': {
        'en': '⚠️ Worker\'s location is off! [Turn On Location]',
        'am': '⚠️ የሰራተኛው ቦታ ጠፍቷል! [ቦታ ያብሩ]'
    },
    'location_requested': {
        'en': '🔔 Client requested live location. Please turn it on now.',
        'am': '🔔 ገዢ ቦታ ጠየቀዋል። እባክዎ አሁን ያብሩ።'
    },
    'commission_message': {
        'en': 'Send {commission} to @YourTelegram within 3 hours',
        'am': 'በ 3 ሰዓት ውስጥ {commission} ይላኩልን @YourTelegram'
    },
    'worker_missed_commission': {
        'en': '🚨 Worker {worker_id} missed commission',
        'am': '🚨 ሰራተኛ {worker_id} ክፍያ አልከፍለም'
    },
    'rate_worker': {
        'en': 'Rate worker (1–5 stars)',
        'am': 'ሰራተኛውን ይደገሙ (1-5 ኮከቦች)'
    },
    'cancel_button': {
        'en': '[Cancel]',
        'am': '[ይቻል]'
    },
    'proceed_button': {
        'en': '✅ Proceed',
        'am': '✅ ይቀጥሉ'
    },
    'request_new_worker_button': {
        'en': '🔄 Request New Worker',
        'am': '🔄 አዲስ ሰራተኛ ይጠይቁ'
    },
    'reopened_tag': {
        'en': '🔁 Reopened',
        'am': '🔁 እንደገና ተከፍቷል'
    }
}

def msg(key, lang='en'):
    """
    Get a message in the specified language.

    Args:
        key: The message key
        lang: Language code ('en' for English, 'am' for Amharic)

    Returns:
        The message in the requested language
    """
    if key in MESSAGES:
        if lang in MESSAGES[key]:
            return MESSAGES[key][lang]
        else:
            # Fallback to English if requested language not available
            return MESSAGES[key]['en']
    else:
        # Return the key itself if message not found
        return key

class GoogleSheetsManager:
    """
    A class to manage Google Sheets operations with secure authentication,
    rate limiting, and error handling.
    """

    def __init__(self, credentials_file: str = None, spreadsheet_name: str = None):
        """
        Initialize the Google Sheets manager with service account credentials.

        Args:
            credentials_file: Path to the service account credentials JSON file
            spreadsheet_name: Name of the Google Spreadsheet to use
        """
        self.credentials_file = credentials_file or os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
        self.spreadsheet_name = spreadsheet_name or os.getenv('SPREADSHEET_NAME', 'YazilignBot')
        self.worksheets = {}
        self.spreadsheet = None

        # Authenticate and connect to Google Sheets
        self._authenticate()

        # Define the required worksheets
        self.required_worksheets = [
            'Dashboard', 'Orders', 'Workers', 'History', 'Payouts', 'Expenses'
        ]

        # Create or get the required worksheets
        self._create_worksheets()

        logger.info("Google Sheets Manager initialized successfully")

    def _authenticate(self):
        """Authenticate with Google Sheets API using service account credentials."""
        try:
            # Define the scope
            scope = ['https://spreadsheets.google.com/feeds',
                     'https://www.googleapis.com/auth/drive']

            # Authenticate using service account credentials
            creds = ServiceAccountCredentials.from_json_keyfile_name(
                self.credentials_file, scope
            )
            client = gspread.authorize(creds)

            # Open the spreadsheet
            self.spreadsheet = client.open(self.spreadsheet_name)

            logger.info("Successfully authenticated with Google Sheets API")
        except FileNotFoundError:
            logger.error(f"Credentials file '{self.credentials_file}' not found")
            raise
        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            raise

    def _create_worksheets(self):
        """Create the required worksheets if they don't exist."""
        try:
            existing_sheets = [sheet.title for sheet in self.spreadsheet.worksheets()]

            for worksheet_name in self.required_worksheets:
                if worksheet_name not in existing_sheets:
                    self.spreadsheet.add_worksheet(title=worksheet_name, rows="1000", cols="26")
                    logger.info(f"Created worksheet: {worksheet_name}")

                # Store worksheet reference
                self.worksheets[worksheet_name] = self.spreadsheet.worksheet(worksheet_name)

            logger.info("All required worksheets are available")
        except Exception as e:
            logger.error(f"Error creating worksheets: {str(e)}")
            raise

    def _exponential_backoff(self, attempt: int, max_delay: float = 60.0):
        """
        Implement exponential backoff with jitter.

        Args:
            attempt: Current attempt number
            max_delay: Maximum delay in seconds
        """
        import random
        import time
        # Calculate base delay with exponential growth
        base_delay = min(max_delay, (2 ** attempt) + random.uniform(0, 1))
        logger.debug(f"Waiting {base_delay:.2f} seconds before retry {attempt + 1}")
        time.sleep(base_delay)

    def append_row(self, worksheet_name: str, row_data: List[Any], max_retries: int = 5) -> bool:
        """
        Safely append a row to the specified worksheet with retry on quota error.

        Args:
            worksheet_name: Name of the worksheet to append to
            row_data: Data to append as a list
            max_retries: Maximum number of retry attempts

        Returns:
            True if successful, False otherwise
        """
        for attempt in range(max_retries):
            try:
                worksheet = self.worksheets[worksheet_name]
                worksheet.append_row(row_data)

                logger.info(f"Successfully appended row to '{worksheet_name}': {row_data}")
                return True

            except HttpError as e:
                if e.resp.status == 429:  # Rate limit exceeded
                    logger.warning(f"Rate limit exceeded on attempt {attempt + 1}, retrying...")
                    if attempt < max_retries - 1:
                        self._exponential_backoff(attempt)
                        continue
                    else:
                        logger.error(f"Max retries reached when appending to '{worksheet_name}'")
                        return False
                elif e.resp.status in [500, 503]:  # Server errors
                    logger.warning(f"Server error on attempt {attempt + 1}, retrying...")
                    if attempt < max_retries - 1:
                        self._exponential_backoff(attempt)
                        continue
                    else:
                        logger.error(f"Max retries reached due to server error")
                        return False
                else:
                    logger.error(f"HTTP error when appending to '{worksheet_name}': {str(e)}")
                    return False

            except gspread.exceptions.APIError as e:
                if "quota" in str(e).lower():
                    logger.warning(f"Quota exceeded on attempt {attempt + 1}, retrying...")
                    if attempt < max_retries - 1:
                        self._exponential_backoff(attempt)
                        continue
                    else:
                        logger.error(f"Max retries reached due to quota error")
                        return False
                else:
                    logger.error(f"API error when appending to '{worksheet_name}': {str(e)}")
                    return False

            except Exception as e:
                logger.error(f"Unexpected error when appending to '{worksheet_name}': {str(e)}")
                return False

        return False

    def read_rows(self, worksheet_name: str, filter_func: callable = None) -> List[List[Any]]:
        """
        Read all rows from the specified worksheet, optionally filtered.

        Args:
            worksheet_name: Name of the worksheet to read from
            filter_func: Optional function to filter rows (takes a row as input, returns boolean)

        Returns:
            List of rows (each row is a list of values)
        """
        try:
            worksheet = self.worksheets[worksheet_name]
            rows = worksheet.get_all_values()

            # Apply filter if provided
            if filter_func:
                rows = [row for row in rows if filter_func(row)]

            logger.info(f"Successfully read {len(rows)} rows from '{worksheet_name}' with filter")
            return rows

        except Exception as e:
            logger.error(f"Error reading from '{worksheet_name}': {str(e)}")
            return []

    def update_row_by_id(self, worksheet_name: str, identifier_col: int, identifier_value: str,
                         update_data: List[Any], id_col_name: str = "Order_ID") -> bool:
        """
        Update a specific row by matching an identifier column value.

        Args:
            worksheet_name: Name of the worksheet to update
            identifier_col: Column index (0-based) to match the identifier
            identifier_value: Value to match in the identifier column
            update_data: New data to update the row with (should match the row structure)
            id_col_name: Name of the identifier column for logging purposes

        Returns:
            True if successful, False otherwise
        """
        for attempt in range(5):  # Retry up to 5 times
            try:
                worksheet = self.worksheets[worksheet_name]

                # Find the row that matches the identifier
                rows = worksheet.get_all_values()

                row_idx = None
                for i, row in enumerate(rows):
                    if len(row) > identifier_col and row[identifier_col] == identifier_value:
                        row_idx = i
                        break

                if row_idx is None:
                    logger.error(f"No row found with {id_col_name} = {identifier_value} in '{worksheet_name}'")
                    return False

                # Calculate the actual row number (Google Sheets is 1-indexed)
                actual_row_num = row_idx + 1

                # Update each cell in the row
                for col_idx, value in enumerate(update_data):
                    if col_idx < len(rows[row_idx]):  # Only update columns that exist
                        worksheet.update_cell(actual_row_num, col_idx + 1, str(value))

                logger.info(f"Successfully updated row with {id_col_name} {identifier_value} in '{worksheet_name}'")
                return True

            except HttpError as e:
                if e.resp.status == 429:  # Rate limit exceeded
                    logger.warning(f"Rate limit exceeded on attempt {attempt + 1}, retrying...")
                    if attempt < 4:  # 5 total attempts, so 4 more after this failure
                        self._exponential_backoff(attempt)
                        continue
                    else:
                        logger.error(f"Max retries reached when updating row in '{worksheet_name}'")
                        return False
                elif e.resp.status in [500, 503]:  # Server errors
                    logger.warning(f"Server error on attempt {attempt + 1}, retrying...")
                    if attempt < 4:
                        self._exponential_backoff(attempt)
                        continue
                    else:
                        logger.error(f"Max retries reached due to server error")
                        return False
                else:
                    logger.error(f"HTTP error when updating row in '{worksheet_name}': {str(e)}")
                    return False

            except gspread.exceptions.APIError as e:
                if "quota" in str(e).lower():
                    logger.warning(f"Quota exceeded on attempt {attempt + 1}, retrying...")
                    if attempt < 4:
                        self._exponential_backoff(attempt)
                        continue
                    else:
                        logger.error(f"Max retries reached due to quota error")
                        return False
                else:
                    logger.error(f"API error when updating row in '{worksheet_name}': {str(e)}")
                    return False

            except Exception as e:
                logger.error(f"Unexpected error when updating row in '{worksheet_name}': {str(e)}")
                return False

        return False

    def log_action(self, user_id: str, action: str, details: str, worksheet_name: str = "History"):
        """
        Log an action to the History sheet.

        Args:
            user_id: ID of the user performing the action
            action: Description of the action performed
            details: Additional details about the action
            worksheet_name: Name of the worksheet to log to (default: History)

        Returns:
            True if logging was successful, False otherwise
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_data = [timestamp, user_id, action, details]

            success = self.append_row(worksheet_name, log_data)
            if success:
                logger.info(f"Logged action: {action} by user {user_id}")
            else:
                logger.error(f"Failed to log action: {action} by user {user_id}")

            return success
        except Exception as e:
            logger.error(f"Error logging action: {e}")
            return False

    def read_rows_by_filter(self, worksheet_name: str, column_index: int,
                           filter_value: str, operator: str = "=") -> List[List[Any]]:
        """
        Read rows from a worksheet with a specific filter applied.

        Args:
            worksheet_name: Name of the worksheet to read from
            column_index: Index of the column to filter on (0-based)
            filter_value: Value to filter by
            operator: Comparison operator ('=', '!=', '>', '<', '>=', '<=')

        Returns:
            List of rows that match the filter
        """
        def filter_func(row):
            if len(row) <= column_index:
                return False

            cell_value = row[column_index]

            if operator == "=":
                return cell_value == filter_value
            elif operator == "!=":
                return cell_value != filter_value
            elif operator == ">":
                try:
                    return float(cell_value) > float(filter_value)
                except ValueError:
                    return False
            elif operator == "<":
                try:
                    return float(cell_value) < float(filter_value)
                except ValueError:
                    return False
            elif operator == ">=":
                try:
                    return float(cell_value) >= float(filter_value)
                except ValueError:
                    return False
            elif operator == "<=":
                try:
                    return float(cell_value) <= float(filter_value)
                except ValueError:
                    return False
            else:
                return False

        return self.read_rows(worksheet_name, filter_func)

class YazilignBot:
    def __init__(self, token: str, google_sheets_manager: GoogleSheetsManager):
        self.token = token
        self.sheets_manager = google_sheets_manager
        self.application = Application.builder().token(token).build()
        # Set worker channel ID to the specific value requested
        self.worker_channel_id = -1008322080514  # Changed to the specific worker channel ID (8322080514)
        self.admin_ids = [int(id.strip()) for id in os.getenv('ADMIN_CHAT_IDS', '').split(',') if id.strip()]

        # Track states
        self.client_conversations = {}  # user_id -> state
        self.admin_conversations = {}   # user_id -> state
        self.worker_conversations = {}  # user_id -> state

        # Track payment timeouts for expiration timer
        self.payment_deadlines = {}  # order_id -> deadline timestamp
        self.commission_deadlines = {}  # order_id -> deadline info
        
        # Track worker check-in mode
        self.worker_checkin_mode = {}  # worker_id -> order_id
        
        # Track reassignment counts
        self.reassignment_counts = {}  # order_id -> count

        self.setup_handlers()

    def setup_handlers(self):
        """Setup all bot handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("new_order", self.new_order))
        self.application.add_handler(CommandHandler("payouts", self.payouts))
        self.application.add_handler(CommandHandler("complete", self.worker_complete_job))
        self.application.add_handler(CommandHandler("check_in", self.worker_check_in))
        self.application.add_handler(CommandHandler("cancel", self.handle_cancel))

        # Message handlers
        self.application.add_handler(
            MessageHandler(filters.LOCATION, self.handle_location_messages)
        )
        self.application.add_handler(
            MessageHandler(filters.PHOTO, self.handle_photo_messages)
        )
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_general_message)
        )

        # Callback query handlers
        self.application.add_handler(
            CallbackQueryHandler(self.handle_job_acceptance)
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_admin_decision, pattern=r'^(approve|decline)_')
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_worker_rating, pattern=r'^rate_')
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_location_enforcement, pattern=r'^turn_on_location_')
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_dispute, pattern=r'^dispute_')
        )
        self.application.add_handler(
            CallbackQueryHandler(self.handle_reassignment_request, pattern=r'^reassign_')
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /start command"""
        user_id = update.effective_user.id
        user_role = context.user_data.get('role', 'unknown')

        if user_role == 'unknown':
            # First time user - ask for role
            await update.message.reply_text(
                "Welcome! Please select your role:\n\n"
                "/client - For placing orders\n"
                "/worker - For accepting jobs\n"
                "/admin - For administrative tasks"
            )
        elif user_role == 'client':
            await update.message.reply_text("Welcome back Client!")
        elif user_role == 'worker':
            # Check if worker is approved
            status = await self.get_worker_status(user_id)
            if status == 'Active':
                await update.message.reply_text("Welcome back Worker! You are active.")
            elif status == 'Pending':
                await update.message.reply_text(msg('not_approved', 'en'))
            elif status == 'Banned':
                await update.message.reply_text("Your account has been banned.")
            else:
                await update.message.reply_text("Welcome! Your account status is unknown.")
        elif user_role == 'admin':
            await update.message.reply_text("Welcome Admin!")

    async def new_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /new_order command"""
        user_id = update.effective_user.id

        # Check for duplicate orders (user shouldn't have active orders)
        if await self.has_active_order(user_id):
            await update.message.reply_text(
                "You already have an active order. Please complete or cancel your current order before creating a new one."
            )
            return

        # Log the interaction
        self.sheets_manager.log_action(str(user_id), "/new_order", "Client initiated new order")

        # Ask for city selection
        city_list = "\n".join([f"• {city}" for city in APPROVED_CITIES])
        await update.message.reply_text(
            f"Please select a city from the approved list:\n{city_list}\n\nOr send /cancel to cancel."
        )

        # Set conversation state to expect city name
        context.user_data['conversation_state'] = AWAITING_CITY
        context.user_data['user_id'] = user_id

        return AWAITING_CITY

    async def has_active_order(self, user_id: int) -> bool:
        """Check if a user has an active order"""
        try:
            # Read all orders to find active ones for this user
            orders = self.sheets_manager.read_rows("Orders")

            for order in orders:
                if len(order) >= 5:
                    order_user_id = order[2]  # User_ID is at index 2
                    status = order[7]         # Status is at index 7

                    # Check if this order belongs to the user and is active
                    if order_user_id == str(user_id) and status in ['Pending', 'Worker_Accepted', 'Paid', 'In Progress']:
                        return True

            return False
        except Exception as e:
            logger.error(f"Error checking active orders for user {user_id}: {e}")
            return False

    async def handle_location_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle location messages - route based on user type and state"""
        user_id = update.effective_user.id

        # Check if this is a worker checking in
        if hasattr(self, 'worker_checkin_mode') and user_id in self.worker_checkin_mode:
            await self.handle_worker_photo_and_location(update, context)
        else:
            # Default to client location handling
            await self.receive_location(update, context)

    async def handle_worker_photo_and_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle worker sending photo and live location for check-in"""
        worker_id = update.effective_user.id

        # Check if this is an active worker
        worker_status = await self.get_worker_status(worker_id)
        if worker_status != 'Active':
            return  # Ignore if not an active worker

        # Check if this worker is in check-in mode
        if not hasattr(self, 'worker_checkin_mode') or worker_id not in self.worker_checkin_mode:
            # Not in check-in mode, handle as regular payment receipt
            await self.receive_payment_receipt(update, context)
            return

        order_id = self.worker_checkin_mode[worker_id]

        # Validate that this is a real image
        if update.message.photo:
            # Get the highest resolution photo
            photo = update.message.photo[-1]

            # Check if location is also provided
            if update.message.location:
                location = update.message.location

                # Update order status to 'Worker_Arrived'
                await self.update_order_status(order_id, 'Worker_Arrived')

                # Notify client that worker has arrived
                await self.notify_client_worker_arrived(order_id, worker_id)

                # Remove worker from check-in mode
                del self.worker_checkin_mode[worker_id]

                await update.message.reply_text(
                    f"✅ Check-in confirmed for order {order_id}!\n"
                    f"Worker has arrived and shared location."
                )
            else:
                await update.message.reply_text(
                    "Please also share your live location along with the photo."
                )
        elif update.message.location:
            # If only location is sent, ask for photo too
            await update.message.reply_text(
                "Please send a photo along with your live location."
            )
        else:
            # Neither photo nor location - this shouldn't happen if the routing is correct
            await update.message.reply_text(
                "Please send both a photo and live location for check-in."
            )

    async def handle_photo_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo messages - route based on user type and state"""
        user_id = update.effective_user.id

        # Check if this is a worker checking in
        if hasattr(self, 'worker_checkin_mode') and user_id in self.worker_checkin_mode:
            await self.handle_worker_photo_and_location(update, context)
        else:
            # Default to client payment receipt handling
            await self.receive_payment_receipt(update, context)

    async def notify_client_worker_arrived(self, order_id: str, worker_id: int):
        """Notify client that worker has arrived"""
        try:
            # Get order details to find the client
            orders = self.sheets_manager.read_rows("Orders")
            client_user_id = None
            for order in orders:
                if len(order) >= 1 and order[0] == order_id:
                    if len(order) >= 3:  # Assuming User_ID is in column 2
                        client_user_id = int(order[2])
                    break

            if client_user_id:
                # Get worker details
                workers = self.sheets_manager.read_rows("Workers")
                worker_name = "Unknown"
                for worker in workers:
                    if len(worker) >= 2 and worker[1] == str(worker_id):
                        worker_name = worker[0]  # Name column
                        break

                # Send notification to client
                try:
                    lang = 'am' if await self.get_user_language(client_user_id) == 'am' else 'en'
                    message = f"👷‍♂️ {worker_name} has arrived for order {order_id}!"

                    if lang == 'am':
                        message = f"👷‍♂️ ሰራተኛ {worker_name} ለትዕዛዝ {order_id} ተመልቷል!"

                    await self.application.bot.send_message(
                        chat_id=client_user_id,
                        text=message
                    )

                    # Log the notification
                    self.sheets_manager.log_action(
                        str(client_user_id),
                        "WORKER_ARRIVED_NOTIFIED",
                        f"Notified client {client_user_id} that worker {worker_name} arrived for order {order_id}"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify client: {e}")
        except Exception as e:
            logger.error(f"Error notifying client of worker arrival: {e}")

    async def get_user_language(self, user_id: int) -> str:
        """Get user's preferred language"""
        # In a real implementation, you'd store user language preferences
        # For now, we'll default to English
        return 'en'

    async def update_order_status(self, order_id: str, new_status: str):
        """Update the status of an order"""
        try:
            # Get the order details
            orders = self.sheets_manager.read_rows("Orders")
            for i, order in enumerate(orders):
                if len(order) >= 1 and order[0] == order_id:  # Assuming Order_ID is in column 0
                    # Update the status
                    updated_order = order.copy()
                    updated_order[7] = new_status  # Status column (index 7)

                    # Update the row in the sheet
                    success = self.sheets_manager.update_row_by_id(
                        "Orders", 0, order_id,  # Assuming Order_ID is in column 0
                        updated_order,
                        "Order_ID"
                    )

                    return success
            return False
        except Exception as e:
            logger.error(f"Error updating order status: {e}")
            return False

    async def get_worker_status(self, worker_id: int) -> str:
        """Get the status of a worker"""
        try:
            workers = self.sheets_manager.read_rows("Workers")
            for worker in workers:
                if len(worker) >= 2 and worker[1] == str(worker_id):  # Assuming User_ID is in column 1
                    if len(worker) >= 4:  # Assuming Status is in column 3 (index 3)
                        return worker[3]
            return "Unknown"
        except Exception as e:
            logger.error(f"Error getting worker status: {e}")
            return "Unknown"

    async def process_payment_for_order(self, order_id: str):
        """Process payment for an order, including partial payments to previous workers"""
        try:
            # Get order details
            orders = self.sheets_manager.read_rows("Orders")
            order_details = None
            for order in orders:
                if len(order) >= 1 and order[0] == order_id:
                    order_details = order
                    break

            if not order_details:
                logger.error(f"Order {order_id} not found for payment processing")
                return

            # Get the full payment amount (the fee for the order)
            full_payment_str = order_details[9] if len(order_details) >= 10 else "700"  # Assuming fee is in column 9
            try:
                full_payment = float(full_payment_str)
            except ValueError:
                logger.error(f"Could not parse fee for order {order_id}: {full_payment_str}")
                full_payment = 700.0  # Default value

            # Check if there's a partial payment owed to a previous worker
            partial_payment = 0.0
            if len(order_details) > 10:  # If we have a partial payment column
                try:
                    partial_payment_str = order_details[10]  # Assuming partial payment is in column 10
                    if partial_payment_str:  # If there's a value
                        partial_payment = float(partial_payment_str)
                except (ValueError, TypeError):
                    partial_payment = 0.0

            # Calculate payments
            current_worker_payment = full_payment - partial_payment if partial_payment < full_payment else 0
            previous_worker_payment = min(partial_payment, full_payment)

            # Get current worker
            current_worker_name = order_details[8] if len(order_details) >= 9 else None

            # Get current worker's ID
            current_worker_id = None
            if current_worker_name:
                workers = self.sheets_manager.read_rows("Workers")
                for worker in workers:
                    if len(worker) >= 2 and worker[0] == current_worker_name:  # Assuming Name is in column 0
                        current_worker_id = int(worker[1])  # Assuming User_ID is in column 1
                        break

            # Process payment to current worker
            if current_worker_id and current_worker_payment > 0:
                # Add to Payouts sheet
                payout_data = [
                    order_id,
                    str(current_worker_id),
                    str(current_worker_payment),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Pending"  # Will be marked as paid later
                ]

                self.sheets_manager.append_row("Payouts", payout_data)

                # Notify current worker
                try:
                    lang = 'am' if await self.get_user_language(current_worker_id) == 'am' else 'en'
                    message = f"💰 You earned {current_worker_payment} ETB for order {order_id}."

                    if lang == 'am':
                        message = f"💰 ለትዕዛዝ {order_id} ብር {current_worker_payment} ገንዘብ የገኘዋቸው።"

                    await self.application.bot.send_message(
                        chat_id=current_worker_id,
                        text=message
                    )
                except Exception as e:
                    logger.error(f"Error notifying current worker: {e}")

            # Process payment to previous worker (if applicable)
            if previous_worker_payment > 0:
                # In a real implementation, you'd need to track who the previous worker was
                # For now, we'll log this as a special case
                self.sheets_manager.log_action(
                    "SYSTEM",
                    "PARTIAL_PAYMENT_PROCESSED",
                    f"Partial payment of {previous_worker_payment} ETB for order {order_id} to previous worker"
                )

            # Update order status to 'Paid'
            await self.update_order_status(order_id, "Paid")

            # Log the payment processing
            self.sheets_manager.log_action(
                "SYSTEM",
                "PAYMENT_PROCESSED",
                f"Processed payment for order {order_id}: Current worker {current_worker_payment} ETB, Previous worker {previous_worker_payment} ETB"
            )
        except Exception as e:
            logger.error(f"Error processing payment for order {order_id}: {e}")

    async def trigger_live_location_sharing(self, order_id: str):
        """Trigger live location sharing between client & worker"""
        try:
            # Get order details to find client and worker
            orders = self.sheets_manager.read_rows("Orders")
            order_data = None

            for order in orders:
                if len(order) >= 1 and order[0] == order_id:
                    order_data = order
                    break

            if order_data:
                # Extract necessary information
                client_user_id = order_data[2] if len(order_data) >= 3 else None  # Assuming User_ID is in column 2
                worker_name = order_data[8] if len(order_data) >= 9 else None     # Assuming Worker is in column 8
                client_lat = float(order_data[5]) if len(order_data) >= 6 and order_data[5] else None  # Assuming Latitude is in column 5
                client_lng = float(order_data[6]) if len(order_data) >= 7 and order_data[6] else None  # Assuming Longitude is in column 6

                if client_user_id and worker_name and client_lat and client_lng:
                    # Get worker's user ID
                    worker_user_id = await self.get_worker_user_id(worker_name)

                    if worker_user_id:
                        # Send live location sharing instructions to both parties
                        try:
                            # Send to client
                            lang = 'am' if await self.get_user_language(client_user_id) == 'am' else 'en'
                            client_msg = f"✅ Payment confirmed! Starting live location sharing for order {order_id}."
                            if lang == 'am':
                                client_msg = f"✅ ክፍያ ተረጋግጧል! ለትዕዛዝ {order_id} ቦታ መጻፍ ይጀምራል።"

                            await self.application.bot.send_message(
                                chat_id=client_user_id,
                                text=client_msg
                            )

                            # Send to worker
                            worker_msg = f"✅ Order {order_id} payment confirmed! Starting live location sharing."
                            if lang == 'am':
                                worker_msg = f"✅ ለትዕዛዝ {order_id} ክፍያ ተረጋግጧል! ቦታ መጻፍ ይጀምራል።"

                            await self.application.bot.send_message(
                                chat_id=worker_user_id,
                                text=worker_msg
                            )

                            # Send live location to both parties
                            await self.application.bot.send_location(
                                chat_id=client_user_id,
                                latitude=client_lat,
                                longitude=client_lng,
                                live_period=3600  # 1 hour
                            )

                            await self.application.bot.send_location(
                                chat_id=worker_user_id,
                                latitude=client_lat,
                                longitude=client_lng,
                                live_period=3600  # 1 hour
                            )
                        except Exception as e:
                            logger.error(f"Error sending live location: {e}")
        except Exception as e:
            logger.error(f"Error triggering live location sharing: {e}")

    async def get_worker_user_id(self, worker_name: str) -> int:
        """Get worker's user ID from the Workers sheet"""
        try:
            workers = self.sheets_manager.read_rows("Workers")
            for worker in workers:
                if len(worker) >= 2 and worker[0] == worker_name:  # Assuming Name is in column 0
                    return int(worker[1])  # Assuming User_ID is in column 1
            return None
        except Exception as e:
            logger.error(f"Error getting worker user ID for {worker_name}: {e}")
            return None

    async def register_new_worker(self, user_id: int, full_name: str, phone: str, telegram_id: str):
        """Register a new worker with Pending status"""
        try:
            # Check if worker already exists
            workers = self.sheets_manager.read_rows("Workers")
            for worker in workers:
                if len(worker) >= 2 and worker[1] == str(user_id):
                    # Worker already registered
                    return

            # Add new worker to Workers sheet
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            worker_data = [
                full_name,      # Name
                str(user_id),   # User_ID (Telegram ID)
                phone,          # Phone
                'Pending',      # Status
                '0',            # Total Earnings (initially 0)
                ''              # Ratings (initially empty)
            ]

            success = self.sheets_manager.append_row("Workers", worker_data)
            if success:
                logger.info(f"New worker registered: {full_name} (ID: {user_id})")
                self.sheets_manager.log_action(
                    str(user_id),
                    "WORKER_REGISTERED",
                    f"Worker {full_name} registered with Pending status"
                )
            else:
                logger.error(f"Failed to register worker: {full_name} (ID: {user_id})")
        except Exception as e:
            logger.error(f"Error registering worker: {e}")

    async def notify_client_of_approval(self, order_id: str, user_id: int):
        """Notify client that their payment receipt was approved"""
        try:
            lang = 'am' if await self.get_user_language(user_id) == 'am' else 'en'

            # Send bilingual confirmation
            en_msg = msg('receipt_approved_en', 'en')
            am_msg = msg('receipt_approved_am', 'am')

            await self.application.bot.send_message(
                chat_id=user_id,
                text=f"{en_msg}\n\n{am_msg}"
            )

            # Log the notification
            self.sheets_manager.log_action(
                str(user_id),
                "PAYMENT_APPROVED_NOTIFICATION",
                f"Sent payment approval notification to client for order {order_id}"
            )
        except Exception as e:
            logger.error(f"Error notifying client of approval: {e}")

    async def log_interaction(self, user_id: str, action: str, details: str):
        """Log interaction to History sheet"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_data = [timestamp, user_id, action, details]

            success = self.sheets_manager.append_row("History", log_data)
            if success:
                logger.info(f"Logged interaction: {action} by user {user_id}")
            else:
                logger.error(f"Failed to log interaction: {action} by user {user_id}")
        except Exception as e:
            logger.error(f"Error logging interaction: {e}")

    async def check_rate_limit(self, user_id: int) -> bool:
        """Check if user is within rate limit (max 5 messages per minute)"""
        now = datetime.now()

        # Initialize user message times if not exists
        if not hasattr(self, 'user_message_times'):
            self.user_message_times = {}

        if user_id not in self.user_message_times:
            self.user_message_times[user_id] = []

        # Clean old messages (older than 1 minute)
        one_minute_ago = now - timedelta(minutes=1)
        self.user_message_times[user_id] = [
            msg_time for msg_time in self.user_message_times[user_id]
            if msg_time > one_minute_ago
        ]

        # Check if user has exceeded the limit
        if len(self.user_message_times[user_id]) >= 5:  # MAX_MESSAGES_PER_MINUTE = 5
            return False

        # Add current message time
        self.user_message_times[user_id].append(now)
        return True

    async def generate_order_id(self) -> str:
        """Generate a unique Order_ID"""
        import random
        import string
        from datetime import datetime

        today = datetime.now().strftime("%Y%m%d")
        # Generate 4 random uppercase letters/numbers
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return f"YZL-{today}-{random_part}"

    async def mark_order_paid(self, order_id: str, amount: float = 700.0) -> bool:
        """Mark an order as paid in the Orders sheet with amount"""
        try:
            # Get the order details
            orders = self.sheets_manager.read_rows("Orders")
            for i, order in enumerate(orders):
                if len(order) >= 1 and order[0] == order_id:  # Assuming Order_ID is in column 0
                    # Update the status to 'Paid' and amount
                    updated_order = order.copy()
                    updated_order[7] = 'Paid'  # Status column (index 7)
                    
                    # Update the fee amount if provided
                    if len(updated_order) > 9:
                        updated_order[9] = str(amount)
                    else:
                        # Extend the row if needed
                        updated_order.extend([''] * (10 - len(updated_order)))
                        updated_order[9] = str(amount)

                    # Update the row in the sheet
                    success = self.sheets_manager.update_row_by_id(
                        "Orders", 0, order_id,  # Assuming Order_ID is in column 0
                        updated_order,
                        "Order_ID"
                    )

                    if success:
                        # Trigger the automatic notifications when order is marked as 'Paid'
                        await self.trigger_notifications_for_paid_order(order_id, updated_order)

                        # Handle post-payment commission flow
                        await self.handle_post_payment_commission(order_id, updated_order)

                    return success
            return False
        except Exception as e:
            logger.error(f"Error marking order as paid: {e}")
            return False

    async def trigger_notifications_for_paid_order(self, order_id: str, order_data: list):
        """Trigger automatic notifications when an order is marked as 'Paid'"""
        try:
            # Extract necessary information from order data
            client_user_id = order_data[2] if len(order_data) >= 3 else None  # Assuming User_ID is in column 2
            worker_name = order_data[8] if len(order_data) >= 9 else None     # Assuming Worker is in column 8
            client_lat = float(order_data[5]) if len(order_data) >= 6 and order_data[5] else None  # Assuming Latitude is in column 5
            client_lng = float(order_data[6]) if len(order_data) >= 7 and order_data[6] else None  # Assuming Longitude is in column 6

            if not client_user_id:
                logger.error(f"Could not find client user ID for order {order_id}")
                return

            # Get worker's user ID from the Workers sheet
            worker_user_id = await self.get_worker_user_id(worker_name)

            # Process payment for the order (including any partial payments to previous workers)
            await self.process_payment_for_order(order_id)

            # Send notification to client
            if client_user_id and worker_name:
                await self.send_notification_to_client(client_user_id, worker_name)

            # Send notification to worker
            if worker_user_id and client_lat and client_lng:
                await self.send_notification_to_worker(worker_user_id, client_lat, client_lng)

            # Log both actions to History
            self.sheets_manager.log_action(
                client_user_id,
                "NOTIFICATION_SENT_TO_CLIENT",
                f"Sent live location notification to client for order {order_id}"
            )

            if worker_user_id:
                self.sheets_manager.log_action(
                    worker_user_id,
                    "NOTIFICATION_SENT_TO_WORKER",
                    f"Sent live location request to worker {worker_name} for order {order_id}"
                )

        except Exception as e:
            logger.error(f"Error triggering notifications for paid order {order_id}: {e}")

    async def send_notification_to_client(self, client_user_id: str, worker_name: str):
        """Send notification to client when order is marked as 'Paid'"""
        try:
            # Send message to client
            lang = 'am' if await self.get_user_language(client_user_id) == 'am' else 'en'
            en_msg = f"✅ Worker {worker_name} has been assigned to your order!\n"
            en_msg += "Payment has been confirmed. Live location sharing has started."

            am_msg = f"✅ ሰራተኛ {worker_name} ለትዕዛዝዎ ተመድቧል!\n"
            am_msg += "ክፍያ ተረጋግጧል። ቦታ መጻፍ ተጀምሯል።"

            await self.application.bot.send_message(
                chat_id=client_user_id,
                text=f"{en_msg}\n\n{am_msg}"
            )

            logger.info(f"Sent notification to client {client_user_id} about worker {worker_name}")
        except Exception as e:
            logger.error(f"Error sending notification to client {client_user_id}: {e}")

    async def send_notification_to_worker(self, worker_user_id: str, client_lat: float, client_lng: float):
        """Send notification to worker when order is marked as 'Paid'"""
        try:
            # Send message to worker
            lang = 'am' if await self.get_user_language(worker_user_id) == 'am' else 'en'
            en_msg = f"💼 Client is at {client_lat}, {client_lng}. Share your live location."
            am_msg = f"💼 ገዢው በ {client_lat}, {client_lng} ላይ ነው። ቦታዎን ያጋሩ።"

            await self.application.bot.send_message(
                chat_id=worker_user_id,
                text=f"{en_msg}\n\n{am_msg}"
            )

            # Send live location to worker (the client's location)
            await self.application.bot.send_location(
                chat_id=worker_user_id,
                latitude=client_lat,
                longitude=client_lng,
                live_period=3600  # 1 hour in seconds
            )

            logger.info(f"Sent notification and location to worker {worker_user_id}")
        except Exception as e:
            logger.error(f"Error sending notification to worker {worker_user_id}: {e}")

    async def handle_admin_decision(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin's approve/decline decision on payment receipts"""
        query = update.callback_query
        await query.answer()

        # Parse the callback data
        data_parts = query.data.split('_')
        action = data_parts[0]  # 'approve' or 'decline'
        order_id = data_parts[1] if len(data_parts) > 1 else 'UNKNOWN'
        user_id = int(data_parts[2]) if len(data_parts) > 2 else 0

        if action == 'approve':
            # Mark order Status='Paid'
            success = await self.mark_order_paid(order_id)

            if success:
                # Process payment (including any partial payments to previous workers)
                await self.process_payment_for_order(order_id)

                # Trigger live location sharing between client & worker
                await self.trigger_live_location_sharing(order_id)

                # Send confirmation to admin
                await query.edit_message_text(f"✅ Order {order_id} marked as PAID")

                # Notify client
                await self.notify_client_of_approval(order_id, user_id)

                # Log to History
                self.sheets_manager.log_action(
                    str(query.from_user.id),
                    "RECEIPT_APPROVED",
                    f"Admin approved receipt for order {order_id}"
                )
            else:
                await query.edit_message_text(f"❌ Failed to update order {order_id}")
        elif action == 'decline':
            # Prompt admin for reason
            await query.edit_message_text(
                f"❌ Declining receipt for order {order_id}\n\n"
                f"Please provide a reason for declining:"
            )

            # Store order ID for later use
            context.user_data['awaiting_decline_reason'] = order_id
            context.user_data['admin_chat_id'] = query.message.chat_id

    async def handle_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /cancel command from any state"""
        user_id = update.effective_user.id
        state = context.user_data.get('conversation_state', 'unknown')

        # Log the cancellation
        self.sheets_manager.log_action(
            str(user_id),
            "USER_CANCELLED",
            f"User cancelled during state: {state}"
        )

        # Reset user's conversation state
        context.user_data.clear()

        # Send message and return to start
        await update.message.reply_text(
            "Operation cancelled. Use /start to begin again."
        )

        # Call start to show main menu
        await self.start(update, context)

    async def handle_post_payment_commission(self, order_id: str, order_data: list):
        """Handle the post-payment commission flow"""
        try:
            # Calculate 25% commission
            fee_str = order_data[9] if len(order_data) > 9 else "700"  # Assuming fee is in column 9
            try:
                fee = float(fee_str)
                commission = fee * 0.25  # 25% commission
            except ValueError:
                logger.error(f"Could not parse fee for order {order_id}: {fee_str}")
                return

            # Get worker assigned to this order
            worker_name = order_data[8] if len(order_data) >= 9 else "Unknown"

            # Find worker's user ID
            workers = self.sheets_manager.read_rows("Workers")
            worker_user_id = None
            for worker in workers:
                if len(worker) >= 2 and worker[0] == worker_name:  # Assuming Name is in column 0
                    worker_user_id = int(worker[1])  # Assuming User_ID is in column 1
                    break

            if worker_user_id:
                # Tell worker to send commission to @YourTelegram within 3 hours
                commission_msg = msg('commission_message', 'en').format(commission=commission)
                await self.application.bot.send_message(
                    chat_id=worker_user_id,
                    text=commission_msg
                )

                # Start 3-hour timer to check if commission was sent
                from datetime import datetime, timedelta
                deadline = datetime.now() + timedelta(hours=3)

                # Store commission deadline for this order
                if not hasattr(self, 'commission_deadlines'):
                    self.commission_deadlines = {}
                self.commission_deadlines[order_id] = {
                    'deadline': deadline.timestamp(),
                    'worker_id': worker_user_id,
                    'commission': commission
                }

                # Log the commission requirement
                self.sheets_manager.log_action(
                    str(worker_user_id),
                    "COMMISSION_REQUIRED",
                    f"Worker required to send {commission} ETB commission for order {order_id}"
                )
        except Exception as e:
            logger.error(f"Error handling post-payment commission for order {order_id}: {e}")

    async def check_commission_deadlines(self):
        """Check for orders where commission deadline has passed"""
        from datetime import datetime
        current_time = datetime.now().timestamp()

        overdue_orders = []
        for order_id, data in self.commission_deadlines.items():
            if current_time > data['deadline']:
                overdue_orders.append((order_id, data))

        for order_id, data in overdue_orders:
            # Remove from deadlines
            del self.commission_deadlines[order_id]

            # Alert Admin that worker missed commission
            worker_id = data['worker_id']
            commission = data['commission']

            # Find worker's name
            workers = self.sheets_manager.read_rows("Workers")
            worker_name = "Unknown"
            worker_phone = "Unknown"
            for worker in workers:
                if len(worker) >= 2 and worker[1] == str(worker_id):
                    worker_name = worker[0]  # Name column
                    if len(worker) >= 3:
                        worker_phone = worker[2]  # Phone column
                    break

            # Alert all admins
            for admin_id in self.admin_ids:
                try:
                    await self.application.bot.send_message(
                        chat_id=admin_id,
                        text=msg('worker_missed_commission', 'en').format(worker_id=worker_name)
                    )
                except Exception as e:
                    logger.error(f"Error alerting admin {admin_id} about missed commission: {e}")

            # Log the missed commission
            self.sheets_manager.log_action(
                "SYSTEM",
                "COMMISSION_MISSED",
                f"Worker {worker_name} missed commission of {commission} ETB for order {order_id}"
            )

            # After alerting admin, you could implement automatic banning
            # For now, we'll just log that the admin should call and potentially ban
            # In a real implementation, you might want to call the worker and if they refuse to pay,
            # automatically ban them by phone number and Telegram ID

    async def request_worker_rating(self, order_id: str, client_user_id: int, worker_name: str):
        """Request the client to rate the worker after job completion"""
        try:
            # Create inline keyboard with rating buttons (1-5 stars)
            keyboard = [
                [
                    InlineKeyboardButton("⭐", callback_data=f"rate_{order_id}_1"),
                    InlineKeyboardButton("⭐⭐", callback_data=f"rate_{order_id}_2"),
                    InlineKeyboardButton("⭐⭐⭐", callback_data=f"rate_{order_id}_3"),
                    InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"rate_{order_id}_4"),
                    InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rate_{order_id}_5")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self.application.bot.send_message(
                chat_id=client_user_id,
                text=f"How would you rate {worker_name}'s service for order {order_id}?",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error requesting worker rating: {e}")

    async def handle_general_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle general messages during the conversation"""
        user_id = update.effective_user.id
        message_text = update.message.text

        # Rate Limiting: Check if user has sent too many messages
        if not await self.check_rate_limit(user_id):
            await update.message.reply_text(
                f"You are sending messages too fast. Please slow down. "
                f"Maximum 5 messages per minute allowed."
            )
            return

        # Log the interaction
        await self.log_interaction(user_id, "MESSAGE", message_text)

        # Get user's role
        user_role = context.user_data.get('role')

        if not user_role:
            # If no role is set, ask for role selection
            await update.message.reply_text("Please select your role first using /start")
            return

        # Route message based on conversation state
        state = context.user_data.get('conversation_state')
        
        if state == AWAITING_CITY:
            # Check if the city is in the approved list
            selected_city = message_text.strip().title()
            if selected_city not in APPROVED_CITIES:
                # If city is not Addis Ababa, show restriction message
                if selected_city != "Addis Ababa":
                    await update.message.reply_text(
                        msg('not_operating_city', 'en').format(city=selected_city) + "\n\n" +
                        msg('not_operating_city', 'am').format(city=selected_city)
                    )
                    return
                else:
                    # City is not in the list but is not Addis Ababa restriction
                    city_list = "\n".join([f"• {city}" for city in APPROVED_CITIES])
                    await update.message.reply_text(
                        f"Invalid city. Please select from the approved list:\n{city_list}"
                    )
                    return
            
            # Store the selected city
            context.user_data['selected_city'] = selected_city

            # Ask for office name (free text input)
            await update.message.reply_text(
                "Please enter the office name:\n\nOr send /cancel to cancel."
            )

            # Set conversation state to expect office name
            context.user_data['conversation_state'] = AWAITING_OFFICE
            return

        elif state == AWAITING_OFFICE:
            # Store the selected office
            context.user_data['selected_office'] = message_text.strip()

            # Ask for live location
            await update.message.reply_text(
                "Please share your live location using the attachment button (📍) or send /cancel to cancel."
            )

            # Update conversation state
            context.user_data['conversation_state'] = AWAITING_LOCATION
            return

        # Route message based on role
        if user_role == 'client':
            await self.handle_client_message(update, context)
        elif user_role == 'worker':
            await self.handle_worker_message(update, context)
        elif user_role == 'admin':
            await self.handle_admin_message(update, context)

    async def handle_client_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages for clients"""
        user_id = update.effective_user.id
        message_text = update.message.text.lower()

        # Handle other client messages
        if 'order' in message_text:
            await update.message.reply_text("As a client, you can view your orders here.")
        elif 'support' in message_text:
            await update.message.reply_text("Contacting support...")
        else:
            await update.message.reply_text(f"Client: Received message - {update.message.text}")

    async def handle_worker_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages for workers"""
        user_id = update.effective_user.id
        message_text = update.message.text.lower()

        # Handle other worker messages
        if 'assignment' in message_text:
            await update.message.reply_text("Checking your assignments...")
        elif 'status' in message_text:
            await update.message.reply_text("Updating assignment status...")
        else:
            await update.message.reply_text(f"Worker: Received message - {update.message.text}")

    async def handle_admin_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages for admins"""
        user_id = update.effective_user.id
        message_text = update.message.text.lower()

        # Check if admin is awaiting a decline reason
        if context.user_data.get('awaiting_decline_reason'):
            order_id = context.user_data['awaiting_decline_reason']
            admin_chat_id = context.user_data['admin_chat_id']

            # Process the decline reason
            await self.process_decline_reason(order_id, message_text, admin_chat_id)

            # Clear the awaiting flag
            del context.user_data['awaiting_decline_reason']
            del context.user_data['admin_chat_id']

            await update.message.reply_text(f"Order {order_id} declined with reason: {message_text}")
            return

        # Handle other admin messages
        if 'report' in message_text:
            await update.message.reply_text("Generating reports...")
        elif 'user' in message_text:
            await update.message.reply_text("Managing users...")
        else:
            await update.message.reply_text(f"Admin: Received message - {update.message.text}")

    async def process_decline_reason(self, order_id: str, reason: str, admin_chat_id: int):
        """Process the reason for declining a payment receipt"""
        # Find the user who sent the receipt
        orders = self.sheets_manager.read_rows("Orders")
        user_id = None
        for order in orders:
            if len(order) >= 1 and order[0] == order_id:
                if len(order) >= 3:  # Assuming User_ID is in column 2
                    user_id = int(order[2])
                break

        if user_id:
            # Notify the client about the decline with reason
            try:
                lang = 'am' if update.effective_user.language_code == 'am' else 'en'
                en_msg = f"❌ Receipt for order {order_id} declined. Reason: {reason}"
                am_msg = f"❌ ለትዕዛዝ {order_id} ሲምበሩ ተቀባይነት አላገኘም። ምክንያት: {reason}"

                await self.application.bot.send_message(
                    chat_id=user_id,
                    text=f"{en_msg}\n\n{am_msg}"
                )

                # Log the decline
                self.sheets_manager.log_action(
                    str(user_id),
                    "RECEIPT_DECLINED",
                    f"Receipt for order {order_id} declined with reason: {reason}"
                )
            except Exception as e:
                logger.error(f"Failed to notify client of decline: {e}")

    async def receive_location(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle received location"""
        user_id = update.effective_user.id
        location = update.message.location

        # Check if we're expecting a location
        state = context.user_data.get('conversation_state')
        if state != AWAITING_LOCATION:
            return

        # Store the location
        context.user_data['location'] = {
            'latitude': location.latitude,
            'longitude': location.longitude
        }

        # Generate unique order ID
        order_id = await self.generate_order_id()

        # Save order to Orders sheet with Status='Pending'
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        username = update.effective_user.username or f"user_{user_id}"
        office = context.user_data.get('selected_office', 'Unknown')
        city = context.user_data.get('selected_city', 'Addis Ababa')  # Default to Addis Ababa

        # Combine office and city for the location field
        full_location = f"{office}, {city}"

        order_data = [
            order_id,           # Order_ID
            timestamp,          # Timestamp
            str(user_id),       # User_ID
            username,           # Username
            full_location,      # Office (now includes city)
            str(location.latitude),  # Latitude
            str(location.longitude), # Longitude
            'Pending',          # Status
            '',                 # Worker (empty initially)
            '700'               # Fee
        ]

        success = self.sheets_manager.append_row("Orders", order_data)

        if success:
            # Log the order creation
            self.sheets_manager.log_action(
                str(user_id),
                "ORDER_CREATED",
                f"Order {order_id} created for {full_location}"
            )

            # Broadcast job to private worker channel
            if self.worker_channel_id:
                try:
                    await self.post_job_to_worker_channel(order_id, full_location, '700')
                except Exception as e:
                    logger.error(f"Failed to broadcast to worker channel: {e}")

            # Reply to client with searching message
            lang = 'am' if context.user_data.get('language') == 'am' else 'en'
            await update.message.reply_text(msg('searching_workers', lang))

            # Update conversation state to expect worker acceptance (not payment yet)
            context.user_data['conversation_state'] = AWAITING_WORKER_ACCEPTANCE
            context.user_data['order_id'] = order_id

            # Inform client that payment will come after worker acceptance
            await update.message.reply_text(
                f"✅ Order {order_id} created successfully!\n\n"
                f"Waiting for a worker to accept your order. Payment will be requested after worker acceptance."
            )
        else:
            await update.message.reply_text("Sorry, there was an error creating your order. Please try again.")
            # Reset conversation state
            context.user_data['conversation_state'] = None

    async def post_job_to_worker_channel(self, order_id: str, office: str, fee: str, is_reopened: bool = False):
        """Post a job to the worker channel with accept button"""
        if not self.worker_channel_id:
            logger.error("WORKER_CHANNEL_ID not set in environment variables")
            return False

        try:
            # Create inline keyboard with accept button
            keyboard = [[InlineKeyboardButton("Accept", callback_data=order_id)]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Prepare the message text
            message_text = f"📍 {office}\n💰 {fee} ETB\n[Accept]"
            
            # Add reopened tag if it's a reassignment
            if is_reopened:
                message_text += f"\n{msg('reopened_tag', 'en')}"

            # Send job posting to worker channel
            await self.application.bot.send_message(
                chat_id=self.worker_channel_id,
                text=message_text,
                reply_markup=reply_markup
            )

            logger.info(f"Job posted to worker channel: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Error posting job to worker channel: {e}")
            return False

    async def receive_payment_receipt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle received payment receipt from client"""
        user_id = update.effective_user.id

        # Check if we're expecting a payment receipt
        state = context.user_data.get('conversation_state')
        if state != AWAITING_PAYMENT:
            return

        # Get the photo
        photo = update.message.photo[-1]  # Get highest resolution photo

        # Get admin chat IDs from environment
        admin_ids = [int(id.strip()) for id in os.getenv('ADMIN_CHAT_IDS', '').split(',') if id.strip()]

        if not admin_ids:
            # If no admin IDs are set, use a fallback
            await update.message.reply_text(
                "Payment receipt received. Waiting for admin approval..."
            )
            # For demo purposes, we'll simulate approval
            await self.simulate_admin_approval(context.user_data['order_id'], user_id, update)
        else:
            # Forward the photo to each admin with inline buttons
            for admin_id in admin_ids:
                try:
                    # Send the photo to admin
                    await self.application.bot.forward_message(
                        chat_id=admin_id,
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.message_id
                    )

                    # Send the inline buttons to admin
                    order_id = context.user_data.get('order_id', 'UNKNOWN')
                    keyboard = [
                        [
                            InlineKeyboardButton("Approve", callback_data=f"approve_{order_id}_{user_id}"),
                            InlineKeyboardButton("Decline", callback_data=f"decline_{order_id}_{user_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await self.application.bot.send_message(
                        chat_id=admin_id,
                        text=f"Payment receipt for Order {order_id} from User {user_id}",
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Failed to forward receipt to admin {admin_id}: {e}")

            await update.message.reply_text(
                "Payment receipt received. Waiting for admin approval..."
            )

    async def simulate_admin_approval(self, order_id: str, user_id: int, update: Update):
        """Simulate admin approval for demonstration purposes"""
        # Update order status to 'Paid' in the sheet
        # Find the order in the sheet to update
        orders = self.sheets_manager.read_rows("Orders")
        for i, order in enumerate(orders):
            if len(order) > 0 and order[0] == order_id:  # Assuming Order_ID is at index 0
                # Update the status to 'Paid'
                success = self.sheets_manager.update_row_by_id(
                    "Orders", 0, order_id,
                    order[:7] + ['Paid'] + order[8:],  # Update status at index 7
                    "Order_ID"
                )

                if success:
                    # Trigger the automatic notifications when order is marked as 'Paid'
                    await self.trigger_notifications_for_paid_order(order_id, order)

                    # Handle post-payment commission flow
                    await self.handle_post_payment_commission(order_id, order)

                    # Notify client of payment confirmation
                    lang = 'am' if update.effective_user.language_code == 'am' else 'en'
                    en_msg = msg('payment_confirmed_en', 'en')
                    am_msg = msg('payment_confirmed_am', 'am')

                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"{en_msg}\n\n{am_msg}"
                    )

                    # Log the payment confirmation
                    self.sheets_manager.log_action(
                        str(user_id),
                        "PAYMENT_APPROVED",
                        f"Admin approved receipt for order {order_id}"
                    )
                else:
                    await update.message.reply_text("There was an issue updating your order status.")
                break

    async def handle_job_acceptance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when a worker accepts a job"""
        query = update.callback_query
        await query.answer()

        # The callback data is just the order_id
        order_id = query.data
        worker_id = update.effective_user.id

        # Check if worker is active
        worker_status = await self.get_worker_status(worker_id)
        if worker_status != 'Active':
            await query.answer("You are not an active worker", show_alert=True)
            return

        # Check if order is still available (not already accepted)
        # This is a critical section - we need to check and update atomically
        order_status = await self.get_order_status(order_id)
        if order_status != 'Pending':
            await query.answer("This order has already been taken", show_alert=True)
            return

        # Attempt to lock the order by updating its status to 'Worker_Accepted'
        success = await self.lock_order(order_id, worker_id)
        if success:
            # Notify the client about the acceptance
            await self.notify_client_of_acceptance(order_id, worker_id)

            # Update the message to show it's taken
            await query.edit_message_text(
                f"✅ Order {order_id} accepted by worker {worker_id}\n"
                f"Please contact the client now."
            )

            # Send confirmation to worker
            lang = 'am' if update.effective_user.language_code == 'am' else 'en'
            await context.bot.send_message(
                chat_id=worker_id,
                text=msg('order_accepted', lang)
            )
        else:
            await query.answer("Failed to accept order", show_alert=True)

    async def get_order_status(self, order_id: str) -> str:
        """Get the status of an order"""
        try:
            orders = self.sheets_manager.read_rows("Orders")
            for order in orders:
                if len(order) >= 1 and order[0] == order_id:  # Assuming Order_ID is in column 0
                    if len(order) >= 8:  # Assuming Status is in column 7 (index 7)
                        return order[7]
            return "Not Found"
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return "Error"

    async def lock_order(self, order_id: str, worker_id: int) -> bool:
        """Lock an order by updating its status to 'Worker_Accepted'"""
        try:
            # Get the order details
            orders = self.sheets_manager.read_rows("Orders")
            for i, order in enumerate(orders):
                if len(order) >= 1 and order[0] == order_id:  # Assuming Order_ID is in column 0
                    # Double-check the status is still 'Pending' before updating
                    if len(order) >= 8 and order[7] != 'Pending':
                        # Another worker got it first
                        return False

                    # Update the status to 'Worker_Accepted' and assign the worker
                    updated_order = order.copy()
                    updated_order[7] = 'Worker_Accepted'  # Status column
                    updated_order[8] = str(worker_id)  # Worker column

                    # Find the worker's name
                    workers = self.sheets_manager.read_rows("Workers")
                    worker_name = "Unknown"
                    for worker in workers:
                        if len(worker) >= 2 and worker[1] == str(worker_id):
                            worker_name = worker[0]  # Name column
                            break

                    updated_order[8] = worker_name  # Worker name instead of ID

                    # Update the row in the sheet
                    success = self.sheets_manager.update_row_by_id(
                        "Orders", 0, order_id,  # Assuming Order_ID is in column 0
                        updated_order,
                        "Order_ID"
                    )

                    return success
            return False
        except Exception as e:
            logger.error(f"Error locking order: {e}")
            return False

    async def notify_client_of_acceptance(self, order_id: str, worker_id: int):
        """Notify the client that a worker has accepted their order"""
        try:
            # Get order details to find the client
            orders = self.sheets_manager.read_rows("Orders")
            client_user_id = None
            for order in orders:
                if len(order) >= 1 and order[0] == order_id:
                    if len(order) >= 3:  # Assuming User_ID is in column 2
                        client_user_id = int(order[2])
                    break

            if client_user_id:
                # Get worker details
                workers = self.sheets_manager.read_rows("Workers")
                worker_name = "Unknown"
                for worker in workers:
                    if len(worker) >= 2 and worker[1] == str(worker_id):
                        worker_name = worker[0]  # Name column
                        break

                # Create inline keyboard with [✅ Proceed] and [🔄 Request New Worker] buttons
                keyboard = [
                    [
                        InlineKeyboardButton(msg('proceed_button', 'en'), callback_data=f"proceed_{order_id}"),
                        InlineKeyboardButton(msg('request_new_worker_button', 'en'), callback_data=f"reassign_{order_id}")
                    ],
                    [
                        InlineKeyboardButton(msg('dispute_logged', 'en'), callback_data=f"dispute_{order_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Send notification to client with payment instructions and buttons
                try:
                    # Update the order status to 'Worker_Accepted' to indicate payment phase
                    await self.update_order_status(order_id, 'Worker_Accepted')

                    # Set payment deadline (30 minutes from now)
                    from datetime import datetime, timedelta
                    deadline = datetime.now() + timedelta(minutes=30)
                    self.payment_deadlines[order_id] = deadline.timestamp()

                    # Send bilingual message to client
                    en_msg = f"✅ Worker {worker_name} has accepted your order {order_id}!\n\n"
                    en_msg += "Please send 700 ETB to [CBE] and upload your payment receipt within 30 minutes."

                    am_msg = f"✅ ሰራተኛ {worker_name} ትዕዛዝዎን {order_id} ተቀብለዋል!\n\n"
                    am_msg += "እባክዎ 700 ብር ይላክሱ እና ሲምበር ያስገቡ በ 30 ደቂቃ ውስጥ።"

                    await self.application.bot.send_message(
                        chat_id=client_user_id,
                        text=f"{en_msg}\n\n{am_msg}",
                        reply_markup=reply_markup
                    )

                    # Log the notification
                    self.sheets_manager.log_action(
                        str(client_user_id),
                        "WORKER_ACCEPTED",
                        f"Worker {worker_name} accepted order {order_id}, payment requested"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify client: {e}")
        except Exception as e:
            logger.error(f"Error notifying client of acceptance: {e}")

    async def handle_reassignment_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when client requests a new worker"""
        query = update.callback_query
        await query.answer()

        # Extract order ID from callback data
        order_id = query.data.replace("reassign_", "")

        # Check if this order has already been reassigned once
        if not hasattr(self, 'reassignment_counts'):
            self.reassignment_counts = {}
        
        if order_id in self.reassignment_counts and self.reassignment_counts[order_id] >= 1:
            await query.answer("Only 1 reassignment allowed per order", show_alert=True)
            return

        # Get current worker assigned to this order
        orders = self.sheets_manager.read_rows("Orders")
        current_worker_name = None
        current_worker_id = None
        for order in orders:
            if len(order) >= 1 and order[0] == order_id:
                if len(order) >= 9:  # Assuming Worker name is in column 8
                    current_worker_name = order[8]
                    # Find the worker's ID
                    workers = self.sheets_manager.read_rows("Workers")
                    for worker in workers:
                        if len(worker) >= 2 and worker[0] == current_worker_name:
                            current_worker_id = int(worker[1])
                            break
                break

        if current_worker_id:
            # Notify the current worker that the job has been reopened
            try:
                await self.application.bot.send_message(
                    chat_id=current_worker_id,
                    text=f"⚠️ Job {order_id} has been reopened. You are no longer assigned to this order."
                )
            except Exception as e:
                logger.error(f"Failed to notify worker of reassignment: {e}")

        # Update the order status back to 'Pending'
        await self.update_order_status(order_id, 'Pending')

        # Increment reassignment counter
        if order_id not in self.reassignment_counts:
            self.reassignment_counts[order_id] = 0
        self.reassignment_counts[order_id] += 1

        # Re-post the job to the worker channel with "Reopened" tag
        if self.worker_channel_id:
            try:
                # Get the office location for this order
                for order in orders:
                    if len(order) >= 1 and order[0] == order_id:
                        office = order[4] if len(order) >= 5 else "Unknown"
                        fee = order[9] if len(order) > 9 else "700"
                        await self.post_job_to_worker_channel(order_id, office, fee, is_reopened=True)
                        break
            except Exception as e:
                logger.error(f"Failed to repost job to worker channel: {e}")

        # Update the message to confirm reassignment
        await query.edit_message_text(
            f"🔄 Order {order_id} has been reopened. Looking for a new worker..."
        )

        # Log the reassignment
        self.sheets_manager.log_action(
            query.from_user.id,
            "WORKER_REASSIGNED",
            f"Client requested new worker for order {order_id}"
        )

    async def handle_location_enforcement(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when client clicks the 'Turn On Location' button"""
        query = update.callback_query
        await query.answer()

        # Extract order ID from callback data
        order_id = query.data.replace("turn_on_location_", "")

        # Get worker assigned to this order
        orders = self.sheets_manager.read_rows("Orders")
        worker_id = None
        for order in orders:
            if len(order) >= 1 and order[0] == order_id:
                if len(order) >= 9:  # Check if worker is assigned
                    assigned_worker_name = order[8]
                    # Get worker's user ID
                    workers = self.sheets_manager.read_rows("Workers")
                    for worker in workers:
                        if len(worker) >= 2 and worker[0] == assigned_worker_name:
                            worker_id = int(worker[1])
                            break
                break

        if worker_id:
            # Send notification to worker
            try:
                await self.application.bot.send_message(
                    chat_id=worker_id,
                    text=msg('location_requested', 'en')
                )

                # Log the location request
                self.sheets_manager.log_action(
                    str(query.from_user.id),
                    "LOCATION_REQUESTED",
                    f"Client requested live location for order {order_id}"
                )
            except Exception as e:
                logger.error(f"Error sending location request to worker: {e}")

        # Update the message to confirm
        await query.edit_message_text("Location request sent to worker.")

    async def notify_client_location_off(self, order_id: str, client_user_id: int):
        """Notify client that worker's location is off"""
        try:
            # Create inline keyboard with 'Turn On Location' button
            keyboard = [
                [InlineKeyboardButton(msg('location_off_warning', 'en'), callback_data=f"turn_on_location_{order_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await self.application.bot.send_message(
                chat_id=client_user_id,
                text=msg('location_off_warning', 'en'),
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Error notifying client about location off: {e}")

    async def handle_dispute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle when user taps the dispute button"""
        query = update.callback_query
        await query.answer()

        # Extract order ID from callback data
        order_id = query.data.replace("dispute_", "")

        # Show dispute reasons
        keyboard = [
            [InlineKeyboardButton("Worker didn't show", callback_data=f"dispute_reason_{order_id}_no_show")],
            [InlineKeyboardButton("Payment issue", callback_data=f"dispute_reason_{order_id}_payment")],
            [InlineKeyboardButton("Fake photo", callback_data=f"dispute_reason_{order_id}_fake_photo")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text("Select dispute reason:", reply_markup=reply_markup)

    async def handle_worker_rating(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle worker rating submission"""
        query = update.callback_query
        await query.answer()

        # Parse the callback data
        data_parts = query.data.split('_')
        if len(data_parts) != 3 or data_parts[0] != 'rate':
            return

        order_id = data_parts[1]
        rating = int(data_parts[2])

        # Add the rating to the worker
        await self.add_worker_rating(order_id, rating)

        # Update the worker's average rating
        orders = self.sheets_manager.read_rows("Orders")
        worker_name = None
        for order in orders:
            if len(order) >= 1 and order[0] == order_id:
                if len(order) >= 9:  # Assuming worker name is in column 8
                    worker_name = order[8]
                break

        if worker_name:
            await self.update_worker_average_rating(worker_name)

        # Update the message to confirm rating
        await query.edit_message_text(f"Thank you for rating! You gave {rating} star{'s' if rating != 1 else ''}.")

        # Log the rating
        self.sheets_manager.log_action(
            str(query.from_user.id),
            "WORKER_RATED",
            f"User rated worker for order {order_id} with {rating} stars"
        )

    async def add_worker_rating(self, order_id: str, rating: int):
        """Add a rating for a worker after job completion"""
        try:
            # Get order details to find the worker
            orders = self.sheets_manager.read_rows("Orders")
            for order in orders:
                if len(order) >= 1 and order[0] == order_id:
                    worker_name = order[8] if len(order) >= 9 else "Unknown"

                    # Update the worker's rating in the Workers sheet
                    workers = self.sheets_manager.read_rows("Workers")
                    for i, worker in enumerate(workers):
                        if len(worker) >= 2 and worker[0] == worker_name:
                            # Add rating to existing ratings or create new
                            current_ratings = worker[5] if len(worker) >= 6 else ""  # Assuming ratings column is index 5
                            if current_ratings:
                                new_ratings = f"{current_ratings},{rating}"
                            else:
                                new_ratings = str(rating)

                            # Update the worker record
                            updated_worker = worker.copy()
                            updated_worker[5] = new_ratings  # Ratings column

                            success = self.sheets_manager.update_row_by_id(
                                "Workers", 1, worker[1],  # Assuming User_ID is in column 1
                                updated_worker,
                                "User_ID"
                            )

                            if success:
                                logger.info(f"Added rating {rating} for worker {worker_name}")
                            break
                    break
        except Exception as e:
            logger.error(f"Error adding worker rating: {e}")

    async def update_worker_average_rating(self, worker_name: str):
        """Update the average rating for a worker"""
        try:
            # Get all orders for this worker that have been rated
            orders = self.sheets_manager.read_rows("Orders")
            ratings = []

            for order in orders:
                if len(order) >= 10 and order[8] == worker_name:  # Assuming worker name is in column 8
                    # Check if this order has been rated (we'd need to track ratings separately)
                    # For this implementation, we'll assume ratings are stored in a separate column
                    # or we'd need to look at the History sheet for rating events
                    pass

            # In a real implementation, we'd calculate the average from stored ratings
            # For now, we'll just update the worker's rating field in the Workers sheet
            workers = self.sheets_manager.read_rows("Workers")
            for i, worker in enumerate(workers):
                if len(worker) >= 2 and worker[0] == worker_name:  # Assuming name is in column 0
                    # Calculate average rating from stored individual ratings
                    # This would require tracking all ratings for each worker
                    # For now, we'll just note that this is where the calculation would happen
                    break
        except Exception as e:
            logger.error(f"Error updating worker average rating for {worker_name}: {e}")

    async def worker_complete_job(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle worker completing a job"""
        worker_id = update.effective_user.id

        # Check if this is a worker
        worker_status = await self.get_worker_status(worker_id)
        if worker_status != 'Active':
            await update.message.reply_text("Access denied. Only active workers can use this command.")
            return

        # Extract order ID from command
        message_parts = update.message.text.split()
        if len(message_parts) < 2:
            await update.message.reply_text("Usage: /complete <order_id>")
            return

        order_id = message_parts[1]

        # Verify the worker is assigned to this order
        orders = self.sheets_manager.read_rows("Orders")
        order_found = False
        for order in orders:
            if len(order) >= 1 and order[0] == order_id:
                if len(order) >= 9:  # Check if worker is assigned
                    assigned_worker_name = order[8]
                    # Get worker's name to verify
                    workers = self.sheets_manager.read_rows("Workers")
                    worker_name = "Unknown"
                    for worker in workers:
                        if len(worker) >= 2 and worker[1] == str(worker_id):
                            worker_name = worker[0]
                            break

                    if assigned_worker_name == worker_name:
                        order_found = True
                        break

        if not order_found:
            await update.message.reply_text(f"Order {order_id} not found or not assigned to you.")
            return

        # Complete the order and request rating
        await self.complete_order_and_request_rating(order_id)

        await update.message.reply_text(f"Order {order_id} marked as completed. Client has been asked to rate your service.")

    async def worker_check_in(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle worker check-in with photo and live location"""
        worker_id = update.effective_user.id

        # Check if this is an active worker
        worker_status = await self.get_worker_status(worker_id)
        if worker_status != 'Active':
            await update.message.reply_text("Access denied. Only active workers can use this command.")
            return

        # Extract order ID from command
        message_parts = update.message.text.split()
        if len(message_parts) < 2:
            await update.message.reply_text("Usage: /check_in <order_id>")
            return

        order_id = message_parts[1]

        # Verify the worker is assigned to this order
        orders = self.sheets_manager.read_rows("Orders")
        order_found = False
        order_data = None
        for order in orders:
            if len(order) >= 1 and order[0] == order_id:
                if len(order) >= 9:  # Check if worker is assigned
                    assigned_worker_name = order[8]
                    # Get worker's name to verify
                    workers = self.sheets_manager.read_rows("Workers")
                    worker_name = "Unknown"
                    for worker in workers:
                        if len(worker) >= 2 and worker[1] == str(worker_id):
                            worker_name = worker[0]
                            break

                    if assigned_worker_name == worker_name:
                        order_found = True
                        order_data = order
                        break

        if not order_found:
            await update.message.reply_text(f"Order {order_id} not found or not assigned to you.")
            return

        # Put worker in check-in mode
        if not hasattr(self, 'worker_checkin_mode'):
            self.worker_checkin_mode = {}
        self.worker_checkin_mode[worker_id] = order_id

        # Ask worker to send a photo and start live location
        await update.message.reply_text(
            f"Please send a photo of yourself in line and start live location for order {order_id}."
        )

    async def complete_order_and_request_rating(self, order_id: str):
        """Complete an order and request worker rating"""
        try:
            # Update order status to 'Completed'
            await self.update_order_status(order_id, 'Completed')

            # Get order details to find the client and worker
            orders = self.sheets_manager.read_rows("Orders")
            client_user_id = None
            worker_name = None

            for order in orders:
                if len(order) >= 1 and order[0] == order_id:
                    if len(order) >= 3:  # Assuming User_ID is in column 2
                        client_user_id = int(order[2])
                    if len(order) >= 9:  # Assuming Worker name is in column 8
                        worker_name = order[8]
                    break

            if client_user_id and worker_name:
                # Request the client to rate the worker
                await self.request_worker_rating(order_id, client_user_id, worker_name)

                # Calculate and log the automatic payout
                order_fee_str = order[9] if len(order) > 9 else "700"  # Assuming fee is in column 9
                try:
                    order_fee = float(order_fee_str)
                    payout_info = await self.calculate_worker_payout(order_fee)

                    # Log the payout calculation
                    self.sheets_manager.log_action(
                        "SYSTEM",
                        "PAYOUT_CALCULATED",
                        f"Order {order_id}: Worker payout {payout_info['worker']}, Admin revenue {payout_info['admin']}"
                    )
                except ValueError:
                    logger.error(f"Could not parse order fee for order {order_id}: {order_fee_str}")
        except Exception as e:
            logger.error(f"Error completing order and requesting rating for {order_id}: {e}")

    async def calculate_worker_payout(self, order_fee: float) -> dict:
        """Calculate automatic payout distribution"""
        # Assuming 75% to worker, 25% to admin (adjustable)
        worker_percentage = 0.75
        admin_percentage = 0.25

        worker_payout = order_fee * worker_percentage
        admin_revenue = order_fee * admin_percentage

        return {
            "worker": worker_payout,
            "admin": admin_revenue,
            "worker_percentage": worker_percentage,
            "admin_percentage": admin_percentage
        }

    async def payouts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /payouts command to list completed orders"""
        user_id = update.effective_user.id

        # Check if user is admin
        if user_id not in self.admin_ids:
            await update.message.reply_text("Access denied. Admin privileges required.")
            return

        # Get completed orders (where status is 'Paid' or 'Completed')
        orders = self.sheets_manager.read_rows("Orders")
        completed_orders = []

        for order in orders:
            if len(order) >= 8:  # Assuming Status is in column 7
                status = order[7]
                if status in ['Paid', 'Completed']:
                    completed_orders.append(order)

        if completed_orders:
            # Create a list of completed orders
            orders_list = "💰 COMPLETED ORDERS FOR PAYOUT:\n\n"
            for order in completed_orders:
                order_id = order[0] if len(order) > 0 else "N/A"
                client_id = order[2] if len(order) > 2 else "N/A"
                fee = order[9] if len(order) > 9 else "N/A"
                status = order[7] if len(order) > 7 else "N/A"

                orders_list += f"Order: {order_id}\n"
                orders_list += f"Client: {client_id}\n"
                orders_list += f"Fee: {fee} ETB\n"
                orders_list += f"Status: {status}\n"
                orders_list += f"Action: /mark_paid_{order_id}\n\n"

            await update.message.reply_text(orders_list)
        else:
            await update.message.reply_text("No completed orders found for payout.")

    async def bot_crash_recovery(self):
        """Recover from bot crash by resyncing pending orders"""
        try:
            logger.info("Starting bot crash recovery...")

            # Read all orders to find those that need attention
            orders = self.sheets_manager.read_rows("Orders")

            for order in orders:
                if len(order) >= 8:
                    order_id = order[0]  # Order ID
                    status = order[7]    # Status
                    worker_id = order[8] if len(order) > 8 else None  # Worker ID

                    # Check for orders that are in inconsistent states
                    if status in ['Worker_Accepted'] and worker_id:
                        # Notify worker about the order if they're not already contacted
                        try:
                            await self.application.bot.send_message(
                                chat_id=int(worker_id),
                                text=f"Recovery: You have an accepted order {order_id}. Please contact the client."
                            )
                        except Exception as e:
                            logger.error(f"Could not notify worker {worker_id} during recovery: {e}")

            logger.info("Bot crash recovery completed.")
        except Exception as e:
            logger.error(f"Error during bot crash recovery: {e}")

    async def periodic_timeout_check(self):
        """Periodically check for payment timeouts and commission deadlines"""
        while True:
            try:
                await self.check_payment_timeouts()
                await self.check_commission_deadlines()
                # Check every 60 seconds
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                logger.info("Timeout checker task was cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic timeout check: {e}")
                await asyncio.sleep(60)  # Continue even if there's an error

    async def check_payment_timeouts(self):
        """Check for orders where payment deadline has passed"""
        from datetime import datetime
        current_time = datetime.now().timestamp()

        expired_orders = []
        for order_id, deadline in self.payment_deadlines.items():
            if current_time > deadline:
                expired_orders.append(order_id)

        # Remove from deadlines
        for order_id in expired_orders:
            del self.payment_deadlines[order_id]

        # Cancel the order and reopen for other workers
        for order_id in expired_orders:
            await self.cancel_expired_order(order_id)

    async def cancel_expired_order(self, order_id: str):
        """Cancel an order that has expired and reopen it for other workers"""
        try:
            # Update order status to 'Expired'
            await self.update_order_status(order_id, 'Expired')

            # Get the worker who accepted the order to notify them
            orders = self.sheets_manager.read_rows("Orders")
            for order in orders:
                if len(order) >= 1 and order[0] == order_id:
                    worker_name = order[8] if len(order) >= 9 else "Unknown"

                    # Find worker's user ID
                    workers = self.sheets_manager.read_rows("Workers")
                    worker_user_id = None
                    for worker in workers:
                        if len(worker) >= 2 and worker[0] == worker_name:
                            worker_user_id = int(worker[1])
                            break

                    # Notify worker that order has expired
                    if worker_user_id:
                        try:
                            await self.application.bot.send_message(
                                chat_id=worker_user_id,
                                text=f"⏰ Order {order_id} has expired. Client did not submit payment within 30 minutes."
                            )
                        except Exception as e:
                            logger.error(f"Failed to notify worker about expired order: {e}")

                    # Log the expiration
                    self.sheets_manager.log_action(
                        "SYSTEM",
                        "ORDER_EXPIRED",
                        f"Order {order_id} expired due to payment timeout"
                    )

                    # Reopen the order by changing status back to 'Pending'
                    await self.update_order_status(order_id, 'Pending')

                    # Resend the job to the worker channel
                    office = order[4] if len(order) >= 5 else "Unknown"
                    fee = order[9] if len(order) > 9 else "700"
                    await self.post_job_to_worker_channel(order_id, office, fee)

                    break
        except Exception as e:
            logger.error(f"Error canceling expired order {order_id}: {e}")

    async def run(self):
        """Start the bot"""
        logger.info("Starting Yazilign bot...")

        # Perform crash recovery
        await self.bot_crash_recovery()

        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

        # Start the payment timeout checker in the background
        timeout_checker_task = asyncio.create_task(self.periodic_timeout_check())

        # Keep the bot running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping Yazilign bot...")
            timeout_checker_task.cancel()  # Cancel the timeout checker task
            await self.application.stop()
            await self.application.shutdown()


def main():
    """Main function to run the bot"""
    # Get bot token from environment variable
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set.")
        print("Please set it with: export TELEGRAM_BOT_TOKEN='your_bot_token_here'")
        return

    # Check if required environment variables are set
    worker_channel_id = os.getenv('WORKER_CHANNEL_ID')
    if not worker_channel_id:
        print("Warning: WORKER_CHANNEL_ID environment variable not set.")
        print("Please set it with: export WORKER_CHANNEL_ID='@channel_username'")

    admin_ids = os.getenv('ADMIN_CHAT_IDS')
    if not admin_ids:
        print("Warning: ADMIN_CHAT_IDS environment variable not set.")
        print("Please set it with: export ADMIN_CHAT_IDS='admin_id1,admin_id2,...'")

    # Initialize Google Sheets manager
    try:
        sheets_manager = GoogleSheetsManager()
    except Exception as e:
        print(f"Error initializing Google Sheets: {e}")
        print("Make sure you have credentials.json and proper access to the spreadsheet.")
        return

    # Create and run the bot
    bot = YazilignBot(token, sheets_manager)

    print("Yazilign Bot is starting...")
    print("Make sure you have set the required environment variables.")

    try:
        import asyncio
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("\nYazilign Bot stopped by user.")


if __name__ == '__main__':
    main()