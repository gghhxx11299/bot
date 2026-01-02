# main.py
import os
import logging
from fastapi import FastAPI, Request, Response
from telegram.ext import Application
from telegram import Update
from bot_logic import setup_application

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the Telegram bot application (handlers, states, etc.)
app = setup_application()
fastapi_app = FastAPI()

# Define webhook path using BOT_TOKEN from environment
WEBHOOK_PATH = f"/webhook/{os.getenv('BOT_TOKEN')}"

@fastapi_app.on_event("startup")
async def on_startup():
    """Initialize bot and set webhook on startup"""
    await app.initialize()
    await app.start()
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        await app.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Telegram webhook successfully set to: {webhook_url}")
    else:
        logger.warning("⚠️ WEBHOOK_URL not set! Bot will not receive updates.")

@fastapi_app.on_event("shutdown")
async def on_shutdown():
    """Gracefully shut down the bot"""
    await app.stop()
    await app.shutdown()

@fastapi_app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates via webhook"""
    try:
        json_data = await request.json()
        update = Update.de_json(json_data, app.bot)
        await app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}")
        return Response(status_code=500)

# ✅ HEALTH ENDPOINT (supports both GET and HEAD)
@fastapi_app.get("/health")
async def health_get():
    """Respond to GET /health (for debugging and some monitors)"""
    return {"status": "ok", "bot": "running"}

@fastapi_app.head("/health")
async def health_head():
    """Respond to HEAD /health (used by UptimeRobot, etc.)"""
    return Response(status_code=200)
