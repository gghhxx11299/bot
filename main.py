# main.py
import os
import logging
from fastapi import FastAPI, Request, Response
from telegram.ext import Application
from telegram import Update
from bot_logic import setup_application

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = setup_application()
fastapi_app = FastAPI()

# Define the webhook path (for routing)
WEBHOOK_PATH = f"/webhook/{os.getenv('BOT_TOKEN')}"

@fastapi_app.on_event("startup")
async def on_startup():
    await app.initialize()
    await app.start()
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        await app.bot.set_webhook(url=webhook_url)
        logger.info(f"✅ Telegram webhook set to: {webhook_url}")
    else:
        logger.warning("⚠️ WEBHOOK_URL not set! Bot will not receive updates.")

@fastapi_app.on_event("shutdown")
async def on_shutdown():
    await app.stop()
    await app.shutdown()

@fastapi_app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    try:
        json_data = await request.json()
        update = Update.de_json(json_data, app.bot)
        await app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return Response(status_code=500)

@fastapi_app.get("/health")
async def health_check():
    return {"status": "ok", "bot": "running"}
