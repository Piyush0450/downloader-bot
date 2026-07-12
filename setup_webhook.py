import asyncio
from config.settings import BOT_MODE, WEBHOOK_URL
from bot import application

async def main():
    if BOT_MODE == "webhook" and WEBHOOK_URL:
        webhook_full_url = f"{WEBHOOK_URL}/webhook"
        print(f"Setting webhook to: {webhook_full_url}", flush=True)
        await application.initialize()
        await application.bot.set_webhook(url=webhook_full_url)
        await application.shutdown()
        print("Webhook set successfully.", flush=True)
    else:
        print("Not in webhook mode or WEBHOOK_URL is missing. Skipping webhook setup.", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
