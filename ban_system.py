import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

def ban_user(phone_number=None, telegram_id=None):
    """
    Ban a user by phone number or Telegram ID
    
    Args:
        phone_number (str): Phone number to ban
        telegram_id (int): Telegram ID to ban
    """
    try:
        # Define the scope
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']

        # Authenticate using service account credentials
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            'credentials.json', scope
        )
        client = gspread.authorize(creds)

        # Open the spreadsheet
        spreadsheet = client.open('YazilignBot')

        # Get the Workers worksheet
        workers_sheet = spreadsheet.worksheet('Workers')
        workers_data = workers_sheet.get_all_values()

        # Find the worker and update their status to 'Banned'
        for i, worker in enumerate(workers_data):
            if len(worker) >= 3:  # Ensure we have phone and ID
                worker_phone = worker[2]  # Phone is in column 2
                worker_id = worker[1]     # ID is in column 1
                
                if (phone_number and worker_phone == phone_number) or \
                   (telegram_id and worker_id == str(telegram_id)):
                    # Update status to 'Banned'
                    workers_sheet.update_cell(i + 1, 4, 'Banned')  # Status is in column 4
                    print(f"User with {'phone: ' + phone_number if phone_number else 'ID: ' + str(telegram_id)} has been banned.")
                    return True

        print(f"User with {'phone: ' + phone_number if phone_number else 'ID: ' + str(telegram_id)} not found.")
        return False

    except Exception as e:
        print(f"Error banning user: {e}")
        return False

def check_reassignment_count(order_id, max_reassignments=1):
    """
    Check if an order has exceeded the maximum reassignment count
    
    Args:
        order_id (str): Order ID to check
        max_reassignments (int): Maximum allowed reassignments
    
    Returns:
        bool: True if reassignment count is within limit, False otherwise
    """
    try:
        # Define the scope
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']

        # Authenticate using service account credentials
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            'credentials.json', scope
        )
        client = gspread.authorize(creds)

        # Open the spreadsheet
        spreadsheet = client.open('YazilignBot')

        # Get the History worksheet to check reassignment count
        history_sheet = spreadsheet.worksheet('History')
        history_data = history_sheet.get_all_values()

        # Count reassignment events for this order
        reassignment_count = 0
        for entry in history_data:
            if len(entry) >= 4 and order_id in entry[3] and 'REASSIGNED' in entry[2].upper():
                reassignment_count += 1

        return reassignment_count < max_reassignments

    except Exception as e:
        print(f"Error checking reassignment count: {e}")
        return True  # Return True to allow reassignment if there's an error

def flag_worker_for_review(worker_id, reason="Multiple reassignments"):
    """
    Flag a worker for admin review due to multiple reassignments
    
    Args:
        worker_id (int): Worker ID to flag
        reason (str): Reason for flagging
    """
    try:
        # Define the scope
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']

        # Authenticate using service account credentials
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            'credentials.json', scope
        )
        client = gspread.authorize(creds)

        # Open the spreadsheet
        spreadsheet = client.open('YazilignBot')

        # Add to History sheet for admin review
        history_sheet = spreadsheet.worksheet('History')
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_data = [timestamp, str(worker_id), "FLAGGED_FOR_REVIEW", f"{reason} - Multiple reassignments detected"]
        
        history_sheet.append_row(history_data)
        print(f"Worker {worker_id} flagged for admin review: {reason}")

    except Exception as e:
        print(f"Error flagging worker for review: {e}")

if __name__ == "__main__":
    # Example usage
    from datetime import datetime
    
    # Example of banning a user
    # ban_user(phone_number="0912345678", telegram_id=123456789)
    
    # Example of checking reassignment count
    # is_allowed = check_reassignment_count("YZL-20230101-ABCD", max_reassignments=1)
    # print(f"Reassignment allowed: {is_allowed}")
    
    # Example of flagging a worker
    # flag_worker_for_review(123456789, "Multiple reassignments")