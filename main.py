# main.py
import os
import logging
from fastapi import FastAPI, Request, Response
from telegram.ext import Application
from telegram import Update
from bot_logic import setup_application

logging.basicConfig(level=logging.INFO)
app = setup_application()
fastapi_app = FastAPI()

WEBHOOK_PATH = f"/webhook/{os.getenv('BOT_TOKEN', 'test')}"

@fastapi_app.on_event("startup")
async def startup():
    await app.initialize()
    await app.start()
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        await app.bot.set_webhook(url=webhook_url)
        logging.info(f"Webhook set to {webhook_url}")

@fastapi_app.on_event("shutdown")
async def shutdown():
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
        logging.error(f"Webhook error: {e}")
        return Response(status_code=500)

@fastapi_app.get("/health")
async def health():
    return {"status": "ok"}
