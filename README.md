# FineData NFC Cards Telegram Bot

A Telegram bot for ordering NFC business cards with integrated AI support.

## Features

- **Order Processing**: Users can order NFC business cards with options for quantity, design uploads, and customizations
- **Multi-language Support**: Messages provided in both English and Amharic
- **Tiered Pricing**: Based on quantity (1-4: 1,200 ETB each, 5-9: 1,100 ETB each, 10+: 1,000 ETB each)
- **Design Upload**: Users can upload front and back designs for their cards
- **AI-Powered Support**: Integrated Groq AI for customer service
- **Human Support Option**: Users can request to speak with a human representative
- **Order Tracking**: Users can check the status of their orders
- **Google Sheets Integration**: Orders are saved to Google Sheets for business management

## AI Chat Integration

The bot now includes AI-powered support using Groq's API:

- Users can choose to chat with an AI assistant or contact a human
- The AI is trained on the business context of NFC card services
- Maintains conversation history for contextual responses
- Includes error handling and fallback to human support

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables in `.env` file (see `.env.example`)
4. Run the bot: `python main.py`

## Environment Variables

- `BOT_TOKEN`: Your Telegram bot token
- `ADMIN_ID`: Your Telegram user ID for receiving notifications
- `GROQ_API_KEY`: Your Groq API key for AI functionality
- `GOOGLE_SHEETS_CREDENTIALS`: JSON credentials for Google Sheets access
- `WEBHOOK_URL`: (Optional) Webhook URL for production

## Dependencies

- python-telegram-bot==20.7
- fastapi==0.115.0
- groq==0.4.1
- openai==1.12.0
- gspread==6.1.2
- oauth2client==4.1.3