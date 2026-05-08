#!/usr/bin/env python3
"""
KozakAI – Синевир (guaranteed webhook fix)
============================================
- Single aiohttp server that starts instantly (port opens immediately).
- Loads PTB + Cerebras after port is open.
- Adds Telegram webhook route dynamically.
- Answers in groups when:
    * @kozak_aibot is mentioned
    * you reply to the bot
    * text contains: козак, козаче, друже, синевир, синевире, козакai, kozakai, синевирai
- Memory: last 20 messages per chat.
- /ping command to test connectivity.
"""

import os, sys, re, random, logging, asyncio

# ----------------------------------------------------------------------
# Immediate setup (no heavy imports)
# ----------------------------------------------------------------------
print("=== Синевир v2 starting ===", flush=True)

logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("Синевир")

# Character constants
OPENINGS = ["Ото ж бо, ", "Гей-гей, козаче, ", "Слухай сюди, ", "А може, ",
            "Ой, лишенько, ", "Йой, ", "Но-но, ", "Та й що, "]
CLOSINGS = [" Аякже!", " Чи не так?", " Та й годі!", " От і вся правда.",
            " А ти як думав?", " Хіба ж не так?", " Бодай тобі!", ""]
SWEAR_WORDS = ["курва", "шляк", "лайдак", "зараза", "бодай тебе",
               "чорт", "дідько", "матері його ковінька", "псяча віра", "сто чортів"]

# Trigger keywords
TRIGGERS = ["козак", "козаче", "друже", "синевир", "синевире",
            "козакai", "kozakai", "синевирai"]

def stylize(text: str) -> str:
    if not text:
        text = "Нічого не скажу."
    opening = random.choice(OPENINGS)
    closing = random.choice(CLOSINGS)
    if random.random() < 0.6:
        text = f"{random.choice(SWEAR_WORDS)}, {text}"
    return f"{opening}{text}{closing}".strip()

def has_trigger(text: str) -> bool:
    return any(w in text.lower() for w in TRIGGERS)

def remove_mention(text: str, bot_uname: str) -> str:
    pattern = rf"@{re.escape(bot_uname)}\s*"
    cleaned = re.sub(pattern, "", text, 1, flags=re.IGNORECASE).strip()
    return cleaned or "Що?"

# ----------------------------------------------------------------------
# Light health‑check server (opens the port immediately)
# ----------------------------------------------------------------------
from aiohttp import web

async def health(request):
    return web.Response(text="OK")

# We'll store the real webhook handler here later
WEBHOOK_HANDLER = None

async def webhook_route(request):
    """Forward the POST request to PTB's webhook handler."""
    if WEBHOOK_HANDLER is None:
        return web.Response(text="Not ready", status=503)
    return await WEBHOOK_HANDLER(request)

async def start_initial_server(port: int) -> web.Application:
    """Create an aiohttp app with /health and a placeholder webhook route."""
    app = web.Application()
    app.router.add_get("/health", health)
    # The webhook route will be added later (POST) – we add it now as a placeholder
    app.router.add_post("/{token}", webhook_route)
    return app

# ----------------------------------------------------------------------
# Heavy imports (done after port is bound)
# ----------------------------------------------------------------------
def load_libraries():
    global telegram, openai, ChatAction, MessageEntityType
    from telegram import Update, Chat
    from telegram.constants import ChatAction
    from telegram import MessageEntity as MessageEntityType
    from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
    import openai
    logger.info("Libraries loaded")

# ----------------------------------------------------------------------
# Cerebras & memory
# ----------------------------------------------------------------------
SYSTEM_PROMPT = (
    "Ти - український козак на ім'я Синевир із Галичини. "
    "Говори галицьким діалектом, використовуй автентичну лексику, "
    "приказки, вульгаризми. Відповідай дотепно, сміливо, з козацькою вдачею. "
    "Пам'ятай попередні повідомлення цієї розмови."
)

async def generate_ai(chat_data: dict, user_msg: str) -> str:
    client = openai.AsyncOpenAI(
        api_key=os.environ["CEREBRAS_API_KEY"],
        base_url="https://api.cerebras.ai/v1",
    )
    history = chat_data.setdefault("history", [])
    history.append({"role": "user", "content": user_msg})
    while len(history) > 40:          # keep last 20 exchanges
        history.pop(0)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    resp = await client.chat.completions.create(
        model="zai-glm-4.7", messages=messages, temperature=0.9, max_tokens=500
    )
    content = resp.choices[0].message.content.strip()
    if not content:
        raise ValueError("Empty Cerebras response")
    history.append({"role": "assistant", "content": content})
    while len(history) > 40:
        history.pop(0)
    return content

# ----------------------------------------------------------------------
# Bot handlers
# ----------------------------------------------------------------------
async def ping_cmd(update, context):
    await update.message.reply_text("Я тут! Синевир на зв'язку. ⚔️")

async def group_handler(update, context):
    msg = update.message
    if not msg or not msg.text:
        return
    chat = update.effective_chat
    logger.info(f"Msg: chat={chat.id} user={msg.from_user.username} text={msg.text[:50]}")

    if chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        return

    text = msg.text
    bot_uname = context.bot.username.lower()
    is_mention = any(
        e.type == MessageEntityType.MENTION and
        e.extract_from(text).lower() == f"@{bot_uname}"
        for e in (msg.entities or [])
    )
    is_reply = msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id
    has_kw = has_trigger(text)

    logger.info(f"Flags: mention={is_mention}, reply={is_reply}, keyword={has_kw}")

    if not (is_mention or is_reply or has_kw):
        return

    # Build query
    if is_reply:
        query = text
    elif is_mention and not has_kw:
        query = remove_mention(text, bot_uname)
    else:
        query = text if not is_mention else remove_mention(text, bot_uname)

    logger.info(f"Processing: {query}")
    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
    try:
        ai_reply = await generate_ai(context.chat_data, query)
        await msg.reply_text(stylize(ai_reply))
        logger.info("Reply sent")
    except Exception as e:
        logger.warning(f"AI error: {e}")
        await msg.reply_text(stylize("Синевир не при пам'яті, спробуй пізніше."))

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
async def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    cerebras = os.environ.get("CEREBRAS_API_KEY")
    ext_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not token or not cerebras or not ext_url:
        logger.critical("Missing TELEGRAM_TOKEN, CEREBRAS_API_KEY or RENDER_EXTERNAL_URL")
        sys.exit(1)
    port = int(os.environ.get("PORT", 8443))

    # 1. Start initial server (port opens immediately)
    app = await start_initial_server(port)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Initial HTTP server listening on port {port}")

    # 2. Load PTB & OpenAI (port stays open)
    load_libraries()

    # 3. Build PTB application
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("ping", ping_cmd))
    # Catch all text messages in groups – our handler will filter internally
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.TEXT, group_handler)
    )

    await application.initialize()
    await application.start()

    # 4. Set webhook
    webhook_url = f"{ext_url}/{token}"
    ok = await application.bot.set_webhook(url=webhook_url)
    if not ok:
        logger.critical("Telegram rejected webhook URL")
        sys.exit(1)
    logger.info(f"Webhook set → {webhook_url}")

    # Log webhook info
    info = await application.bot.get_webhook_info()
    logger.info(f"Webhook info: {info}")

    # 5. Replace placeholder webhook route with real PTB handler
    global WEBHOOK_HANDLER
    # Get the internal aiohttp handler from PTB's updater
    WEBHOOK_HANDLER = application.updater._webhook_handler
    # The route is already defined as POST /{token} → webhook_route, which now forwards
    logger.info("Webhook route activated")

    # Keep running forever
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical(f"Fatal: {e}", exc_info=True)
        sys.exit(1)
