#!/usr/bin/env python3
"""
KOZAKAI – Синевир (final production bot)
==========================================
- Binds port IMMEDIATELY → Render sees live service.
- After loading PTB, seamlessly switches to the real webhook server.
- Replies in group chats when:
    * @kozak_aibot is mentioned
    * you reply to one of its messages
    * text contains: козак, козаче, друже, синевир, синевире, козакai, kozakai, синевирai
- Memory: last 20 messages per chat.
- Commands: /ping → "Я тут!", /status → webhook info.
"""

import os, sys, re, random, logging, asyncio, signal

# ----------------------------------------------------------------------
# IMMEDIATE OUTPUT (Render logs)
# ----------------------------------------------------------------------
print("=== Синевир v3 STARTING ===", flush=True)

logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("Синевир")

# ----------------------------------------------------------------------
# Kozak flavour constants
# ----------------------------------------------------------------------
OPENINGS = [
    "Ото ж бо, ", "Гей-гей, козаче, ", "Слухай сюди, ", "А може, ",
    "Ой, лишенько, ", "Йой, ", "Но-но, ", "Та й що, ",
]
CLOSINGS = [
    " Аякже!", " Чи не так?", " Та й годі!", " От і вся правда.",
    " А ти як думав?", " Хіба ж не так?", " Бодай тобі!", "",
]
SWEAR_WORDS = [
    "курва", "шляк", "лайдак", "зараза", "бодай тебе",
    "чорт", "дідько", "матері його ковінька", "псяча віра", "сто чортів",
]

def stylize(text: str) -> str:
    if not text:
        text = "Нічого не скажу."
    opening = random.choice(OPENINGS)
    closing = random.choice(CLOSINGS)
    if random.random() < 0.6:
        text = f"{random.choice(SWEAR_WORDS)}, {text}"
    return f"{opening}{text}{closing}".strip()

# ----------------------------------------------------------------------
# Trigger keywords
# ----------------------------------------------------------------------
TRIGGERS = [
    "козак", "козаче", "друже", "синевир", "синевире",
    "козакai", "kozakai", "синевирai",
]

def has_trigger(text: str) -> bool:
    return any(w in text.lower() for w in TRIGGERS)

def remove_mention(text: str, bot_uname: str) -> str:
    pattern = rf"@{re.escape(bot_uname)}\s*"
    cleaned = re.sub(pattern, "", text, 1, flags=re.IGNORECASE).strip()
    return cleaned or "Що?"

# ----------------------------------------------------------------------
# Minimal aiohttp server that opens the port IMMEDIATELY
# ----------------------------------------------------------------------
from aiohttp import web

async def health_check(request):
    return web.Response(text="Healthy")

async def start_health_server(port: int):
    """Start an aiohttp server that only serves /health."""
    app = web.Application()
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"⚡ Health server bound to port {port}")
    return runner, site

# ----------------------------------------------------------------------
# Heavy imports (loaded AFTER port is open)
# ----------------------------------------------------------------------
def load_libraries():
    global telegram, openai, ChatAction, MessageEntityType
    from telegram import Update, Chat
    from telegram.constants import ChatAction
    from telegram import MessageEntity as MessageEntityType
    from telegram.ext import (
        Application, MessageHandler, filters, ContextTypes, CommandHandler,
    )
    import openai
    logger.info("📚 Libraries loaded")

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
    # Keep last 20 exchanges (40 messages)
    while len(history) > 40:
        history.pop(0)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    resp = await client.chat.completions.create(
        model="zai-glm-4.7",
        messages=messages,
        temperature=0.9,
        max_tokens=500,
    )
    content = resp.choices[0].message.content.strip()
    if not content:
        raise ValueError("Empty response from Cerebras")
    history.append({"role": "assistant", "content": content})
    while len(history) > 40:
        history.pop(0)
    return content

# ----------------------------------------------------------------------
# Bot handlers
# ----------------------------------------------------------------------
async def ping_cmd(update, context):
    await update.message.reply_text("Я тут! Синевир на зв'язку. ⚔️")

async def status_cmd(update, context):
    try:
        info = await context.bot.get_webhook_info()
        msg = f"Webhook URL: {info.url}\nPending: {info.pending_update_count}\nLast error: {info.last_error_message}"
    except Exception as e:
        msg = f"Не можу отримати статус: {e}"
    await update.message.reply_text(msg)

async def group_handler(update, context):
    msg = update.message
    if not msg or not msg.text:
        return
    chat = update.effective_chat
    text = msg.text
    logger.info(f"📩 [{chat.id}] {msg.from_user.first_name}: {text[:60]}")

    if chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        return

    bot_uname = context.bot.username.lower()
    is_mention = any(
        e.type == MessageEntityType.MENTION and
        e.extract_from(text).lower() == f"@{bot_uname}"
        for e in (msg.entities or [])
    )
    is_reply = msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id
    is_keyword = has_trigger(text)

    if not (is_mention or is_reply or is_keyword):
        return

    # Build the query to send to AI
    if is_reply:
        query = text
    elif is_mention and not is_keyword:
        query = remove_mention(text, bot_uname)
    else:
        query = text if not is_mention else remove_mention(text, bot_uname)

    logger.info(f"🧠 Processing: {query}")
    await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
    try:
        ai_reply = await generate_ai(context.chat_data, query)
        await msg.reply_text(stylize(ai_reply))
        logger.info("✅ Reply sent")
    except Exception as e:
        logger.error(f"AI error: {e}")
        await msg.reply_text(stylize("Синевир не при пам'яті, спробуй пізніше."))

# ----------------------------------------------------------------------
# Main orchestration
# ----------------------------------------------------------------------
async def main():
    # Environment checks
    token = os.environ.get("TELEGRAM_TOKEN")
    cerebras = os.environ.get("CEREBRAS_API_KEY")
    ext_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not token or not cerebras or not ext_url:
        logger.critical("❌ Missing TELEGRAM_TOKEN, CEREBRAS_API_KEY, or RENDER_EXTERNAL_URL")
        sys.exit(1)
    port = int(os.environ.get("PORT", 8443))

    # 1. Start health server IMMEDIATELY
    health_runner, health_site = await start_health_server(port)

    # 2. Now load heavy libraries (port stays open)
    load_libraries()

    # 3. Build PTB application
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("ping", ping_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.TEXT, group_handler)
    )

    await application.initialize()
    await application.start()

    # 4. Set webhook
    webhook_url = f"{ext_url}/{token}"
    ok = await application.bot.set_webhook(url=webhook_url)
    if not ok:
        logger.critical("❌ Telegram rejected webhook")
        sys.exit(1)
    logger.info(f"🌐 Webhook set → {webhook_url}")

    # 5. Stop health server, release port
    await health_site.stop()
    await health_runner.cleanup()
    logger.info("🛑 Health server stopped, port released")

    # 6. Start PTB webhook server on the same port (this call blocks forever)
    logger.info(f"🚀 Starting PTB webhook server on port {port}")
    await application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=webhook_url,
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical(f"💥 Fatal: {e}", exc_info=True)
        sys.exit(1)
