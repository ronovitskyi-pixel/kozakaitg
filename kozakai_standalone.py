#!/usr/bin/env python3
"""
KozakAI Telegram Bot – Синевир, the Cossack Warrior
=====================================================
- Starts an immediate dummy TCP listener to satisfy Render’s port check.
- Then loads PTB + Cerebras, sets webhook, and replaces dummy with real bot.
- Responds only when @bot_username is mentioned or its message replied to.
- Speaks like a Halychynian Kozak (Синевир) with traditional flair.
"""

import os, sys, re, random, logging, asyncio, time

# ----------------------------------------------------------------------
# Print immediately so Render logs show progress
# ----------------------------------------------------------------------
print("=== KozakAI starting (dummy listener) ===", flush=True)

# ----------------------------------------------------------------------
# Logging to stdout (Render captures it)
# ----------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Kozak speech constants (no heavy imports needed)
# ----------------------------------------------------------------------
OPENINGS = [
    "Ото ж бо, ",
    "Гей-гей, козаче, ",
    "Слухай сюди, ",
    "А може, ",
    "Ой, лишенько, ",
    "Йой, ",
    "Но-но, ",
    "Та й що, ",
]
CLOSINGS = [
    " Аякже!",
    " Чи не так?",
    " Та й годі!",
    " От і вся правда.",
    " А ти як думав?",
    " Хіба ж не так?",
    " Бодай тобі!",
    "",
]
SWEAR_WORDS = [
    "курва",
    "шляк",
    "лайдак",
    "зараза",
    "бодай тебе",
    "чорт",
    "дідько",
    "матері його ковінька",
    "псяча віра",
    "сто чортів",
]

def stylize_response(text: str) -> str:
    """Inject Kozak flair, opening/closing phrases and occasional swear word."""
    if not text:
        text = "Нічого не скажу."
    opening = random.choice(OPENINGS)
    closing = random.choice(CLOSINGS)
    if random.random() < 0.6:
        text = f"{random.choice(SWEAR_WORDS)}, {text}"
    return f"{opening}{text}{closing}".strip()

def remove_mention(text: str, bot_username: str) -> str:
    """Remove the first @bot_username mention from a message."""
    pattern = rf"@{re.escape(bot_username)}\s*"
    cleaned = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else "Що?"

# ----------------------------------------------------------------------
# Dummy TCP listener to open port immediately
# ----------------------------------------------------------------------
async def dummy_listener(port: int, stop_event: asyncio.Event):
    """
    Simple asyncio server that accepts connections and closes them.
    Keeps the port open so Render considers the service ‘live’.
    When `stop_event` is set, the server shuts down.
    """
    async def handle(reader, writer):
        writer.close()

    server = await asyncio.start_server(handle, "0.0.0.0", port)
    logger.info(f"Dummy listener started on port {port}")
    # Wait until we are told to stop
    await stop_event.wait()
    server.close()
    await server.wait_closed()
    logger.info("Dummy listener stopped.")

# ----------------------------------------------------------------------
# Late imports (heavy libraries loaded only after port is open)
# ----------------------------------------------------------------------
def load_heavy_modules():
    """Import PTB, OpenAI, aiohttp – called after port is already bound."""
    global telegram, openai, aiohttp_web
    from telegram import Update, Chat
    from telegram.constants import ChatAction
    from telegram import MessageEntity as MessageEntityType
    from telegram.ext import Application, MessageHandler, filters, ContextTypes
    import openai
    from aiohttp import web as aiohttp_web

    # Make them available globally
    globals()["telegram"] = telegram
    globals()["openai"] = openai
    globals()["aiohttp_web"] = aiohttp_web
    logger.info("Heavy modules loaded successfully.")

# ----------------------------------------------------------------------
# Cerebras API
# ----------------------------------------------------------------------
def get_cerebras_client():
    key = os.environ["CEREBRAS_API_KEY"]
    return openai.AsyncOpenAI(api_key=key, base_url="https://api.cerebras.ai/v1")

async def generate_ai_response(user_message: str) -> str:
    client = get_cerebras_client()
    system_prompt = (
        "Ти - український козак на ім'я Синевир із Галичини. "
        "Говори галицьким діалектом, використовуй автентичну лексику, "
        "приказки, вульгаризми. Відповідай дотепно, сміливо, з козацькою вдачею. "
        "Відповідай українською мовою або суржиком."
    )
    response = await client.chat.completions.create(
        model="zai-glm-4.7",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.9,
        max_tokens=500,
    )
    content = response.choices[0].message.content.strip()
    if not content:
        raise ValueError("Empty response from Cerebras")
    return content

# ----------------------------------------------------------------------
# Health check endpoint (optional, can be added to the bot’s web app)
# ----------------------------------------------------------------------
async def health(request):
    return aiohttp_web.Response(text="Ок, я Синевир!")

# ----------------------------------------------------------------------
# Bot handlers
# ----------------------------------------------------------------------
async def process_and_reply(update, context, user_query):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        ai_raw = await generate_ai_response(user_query)
        styled = stylize_response(ai_raw)
        await update.message.reply_text(styled, reply_to_message_id=update.message.message_id)
    except Exception as e:
        logger.warning(f"AI/Parsing error: {e}")
        fallback = stylize_response("Синевир не при пам'яті, спробуй пізніше.")
        await update.message.reply_text(fallback, reply_to_message_id=update.message.message_id)

async def group_message_handler(update, context):
    msg = update.message
    if not msg or not msg.text:
        return
    chat = update.effective_chat
    if chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        return
    bot_username = context.bot.username.lower()
    mentioned = False
    is_reply = bool(msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id)
    if msg.entities:
        for e in msg.entities:
            if e.type == MessageEntityType.MENTION:
                if e.extract_from(msg.text).lower() == f"@{bot_username}":
                    mentioned = True
                    break
    if not (mentioned or is_reply):
        return
    query = msg.text if is_reply else remove_mention(msg.text, bot_username)
    await process_and_reply(update, context, query)

# ----------------------------------------------------------------------
# Build and run the real bot
# ----------------------------------------------------------------------
async def start_real_bot(port: int, stop_event: asyncio.Event):
    """Load PTB, set webhook, create the aiohttp app, and replace dummy listener."""
    # 1. Load heavy libraries
    load_heavy_modules()

    token = os.environ["TELEGRAM_TOKEN"]
    external_url = os.environ["RENDER_EXTERNAL_URL"]
    webhook_url = f"{external_url}/{token}"

    # 2. Build Application
    application = Application.builder().token(token).build()
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            group_message_handler,
        )
    )

    # 3. Set webhook
    success = await application.bot.set_webhook(url=webhook_url)
    if not success:
        logger.critical("Telegram webhook setup failed.")
        sys.exit(1)
    logger.info(f"Webhook set: {webhook_url}")

    # 4. Create aiohttp web app with health endpoint + PTB webhook handler
    web_app = aiohttp_web.Application()
    web_app.add_routes([aiohttp_web.get("/health", health)])
    # Add PTB’s internal handler (the bot will register its route)
    await application.initialize()
    # PTB v20.8: we can get the webhook handler via a method
    bot_webhook_handler = application.updater._webhook_handler  # not ideal but works
    if not bot_webhook_handler:
        # Fallback: use application.create_webhook_handler()
        from telegram.ext._webhookhandler import WebhookHandler
        # We'll add route manually
        pass
    else:
        web_app.router.add_post(f"/{token}", bot_webhook_handler)

    # 5. Stop the dummy listener and start the real server on the same port
    stop_event.set()  # signal dummy listener to stop
    await asyncio.sleep(0.5)  # give it time to release the port

    # 6. Run the aiohttp web app
    runner = aiohttp_web.AppRunner(web_app)
    await runner.setup()
    site = aiohttp_web.TCPSite(runner, "0.0.0.0", port)
    logger.info(f"Real bot server started on port {port}")
    await site.start()
    # Keep running forever
    while True:
        await asyncio.sleep(3600)

# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------
async def main():
    # Always start the dummy listener first
    port = int(os.environ.get("PORT", 8443))
    stop_event = asyncio.Event()
    dummy_task = asyncio.create_task(dummy_listener(port, stop_event))
    # Give the dummy a moment to bind
    await asyncio.sleep(0.2)

    # Now start the real bot (this will eventually stop the dummy)
    await start_real_bot(port, stop_event)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Fatal error: {e}", flush=True)
        sys.exit(1)
