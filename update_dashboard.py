import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

def update_dashboard():
    """
    Update the Dashboard worksheet with revenue metrics
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

        # Get the Dashboard worksheet
        dashboard_sheet = spreadsheet.worksheet('Dashboard')

        # Get the Orders worksheet to calculate metrics
        orders_sheet = spreadsheet.worksheet('Orders')
        orders_data = orders_sheet.get_all_values()

        # Calculate metrics
        total_orders = len(orders_data) - 1  # Subtract header row
        paid_orders = 0
        total_revenue = 0.0
        active_workers = 0

        # Count paid orders and calculate revenue
        for order in orders_data[1:]:  # Skip header
            if len(order) >= 8:  # Ensure we have enough columns
                status = order[7]  # Status is in column 7
                if status.lower() in ['paid', 'completed']:
                    paid_orders += 1
                    if len(order) > 9:  # Fee is in column 9
                        try:
                            fee = float(order[9])
                            total_revenue += fee
                        except ValueError:
                            pass  # Skip invalid fee values

        # Calculate admin revenue (25% commission)
        admin_revenue = total_revenue * 0.25

        # Get top bureau (most orders)
        bureau_counts = {}
        for order in orders_data[1:]:
            if len(order) >= 5:  # Office is in column 4
                bureau = order[4]
                if bureau in bureau_counts:
                    bureau_counts[bureau] += 1
                else:
                    bureau_counts[bureau] = 1

        top_bureau = max(bureau_counts, key=bureau_counts.get) if bureau_counts else "N/A"

        # Get Workers worksheet to count active workers
        workers_sheet = spreadsheet.worksheet('Workers')
        workers_data = workers_sheet.get_all_values()
        
        for worker in workers_data[1:]:  # Skip header
            if len(worker) >= 4:  # Status is in column 3
                if worker[3].lower() == 'active':
                    active_workers += 1

        # Prepare dashboard data
        dashboard_data = [
            ['Metric', 'Value'],
            ['Total Orders', total_orders],
            ['Paid Orders', paid_orders],
            ['Total Revenue (ETB)', round(total_revenue, 2)],
            ['Admin Revenue (25%)', round(admin_revenue, 2)],
            ['Active Workers', active_workers],
            ['Top Bureau', top_bureau],
            ['Last Updated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
        ]

        # Clear the dashboard sheet and update with new data
        dashboard_sheet.clear()
        dashboard_sheet.append_rows(dashboard_data)

        print("Dashboard updated successfully!")
        print(f"Total Orders: {total_orders}")
        print(f"Paid Orders: {paid_orders}")
        print(f"Total Revenue: {round(total_revenue, 2)} ETB")
        print(f"Admin Revenue: {round(admin_revenue, 2)} ETB")
        print(f"Active Workers: {active_workers}")
        print(f"Top Bureau: {top_bureau}")

    except Exception as e:
        print(f"Error updating dashboard: {e}")

if __name__ == "__main__":
    update_dashboard()