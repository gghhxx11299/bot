# Yazilign Worker Assignment Bot

A Telegram bot for connecting clients with workers for office tasks in Ethiopia.

## Features

- **Client-Worker Matching**: Connects clients who need office tasks done with available workers
- **Location Sharing**: Live location sharing between clients and workers
- **Commission System**: Admin receives 25% commission from workers after client payment
- **Multi-language Support**: Messages provided in both English and Amharic
- **Worker Management**: Assigns jobs to workers, handles reassignment requests
- **Payment Tracking**: Tracks payments and commissions for workers and admins
- **Rating System**: Clients rate workers after job completion
- **Dispute Resolution**: Built-in dispute system for handling conflicts
- **Ban System**: Prevents abuse with phone number and Telegram ID blocking
- **Google Sheets Integration**: Logs all activities to Google Sheets for business management

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables in `.env` file (see `.env.example`)
4. Run the bot: `python start.py`

## Environment Variables

- `BOT_TOKEN`: Your Telegram bot token
- `ADMIN_ID`: Your Telegram user ID for receiving notifications and managing the system
- `GOOGLE_SHEETS_CREDENTIALS`: JSON credentials for Google Sheets access

## Files

- `yazilign_bot_system.py`: Main bot implementation
- `ban_system.py`: User banning functionality
- `update_dashboard.py`: Dashboard metrics updater
- `FINAL_SUMMARY.md`: Complete feature audit checklist

## Business Model

- Clients pay workers directly (cash/Telebirr)
- Admin receives 25% commission from workers after client pays
- No payment = no worker earnings
- All financial risk is on client/worker - admin never handles money
