#!/usr/bin/env python3
"""
SIMPLEST DEBUG BOT – writes to /tmp/bot.log AND stdout
"""

import sys, os, asyncio, time, traceback

# Create a log file early
LOG = open("/tmp/bot.log", "w")
def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()

log("=== BOT STARTING (minimal) ===")

# 1. Check env
for var in ["TELEGRAM_TOKEN", "CEREBRAS_API_KEY", "RENDER_EXTERNAL_URL"]:
    if var not in os.environ:
        log(f"MISSING ENV: {var}")
        sys.exit(1)

log("ENV vars present")
port = int(os.environ.get("PORT", 8443))
log(f"PORT={port}")

# 2. Try importing aiohttp alone
try:
    log("Importing aiohttp...")
    from aiohttp import web
    log("aiohttp imported OK")
except Exception as e:
    log(f"aiohttp import FAILED: {e}")
    traceback.print_exc(file=LOG)
    sys.exit(1)

# 3. Start minimal HTTP server
async def health(request):
    return web.Response(text="OK")

async def start_health():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log(f"Health server running on port {port}")
    return runner, site

# 4. Try importing PTB components one by one
async def test_imports():
    log("Importing telegram...")
    from telegram import Update
    log("Importing telegram.ext...")
    from telegram.ext import Application
    log("Importing ChatAction...")
    from telegram.constants import ChatAction
    log("All telegram imports OK")
    return Application

async def main():
    runner, site = await start_health()

    # Test PTB import
    try:
        app_class = await test_imports()
        log("PTB imports successful")
    except Exception as e:
        log(f"PTB import failed: {e}")
        traceback.print_exc(file=LOG)
        # keep health server alive so we can see logs
        while True:
            await asyncio.sleep(3600)

    # Build minimal bot that only answers /ping
    token = os.environ["TELEGRAM_TOKEN"]
    ext_url = os.environ["RENDER_EXTERNAL_URL"]
    webhook_url = f"{ext_url}/{token}"

    application = app_class.builder().token(token).build()

    async def ping(update, context):
        await update.message.reply_text("PONG")
        log("Ping replied")

    from telegram.ext import CommandHandler
    application.add_handler(CommandHandler("ping", ping))

    await application.initialize()
    await application.start()
    log("Application started")

    ok = await application.bot.set_webhook(url=webhook_url)
    log(f"Webhook set: {webhook_url} result={ok}")

    if not ok:
        log("Webhook failed, exiting")
        sys.exit(1)

    # Stop health server
    await site.stop()
    await runner.cleanup()
    log("Health server stopped, starting PTB webhook...")

    await application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=webhook_url,
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        log(f"FATAL: {e}")
        traceback.print_exc(file=LOG)
