#!/usr/bin/env python3
"""
KozakAI Telegram Bot – Синевир (debug‑enhanced)
================================================
- Logs EVERY group message to stdout (so you see them in Render logs).
- Prints webhook info on startup.
- Replies to /ping (anywhere) for connectivity test.
- All previous features: triggers, mentions, memory.
"""

import os
import sys
import re
import random
import logging
import asyncio

print("=== KozakAI Синевир starting (debug) ===", flush=True)

logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Kozak flair constants
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
TRIGGER_WORDS = [
    "козак", "козаче", "друже", "синевир", "синевире",
    "козакai", "kozakai", "синевирai",
]

def contains_trigger(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in TRIGGER_WORDS)

def remove_mention(text: str, bot_username: str) -> str:
    pattern = rf"@{re.escape(bot_username)}\s*"
    cleaned = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else "Що?"

# ----------------------------------------------------------------------
# Dummy listener (port open immediately)
# ----------------------------------------------------------------------
async def dummy_listener(port: int):
    async def handle(reader, writer):
        writer.close()
    server = await asyncio.start_server(handle, "0.0.0.0", port)
    logger.info(f"Dummy listener on port {port}")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        server.close()
        await server.wait_closed()
        logger.info("Dummy listener stopped")

# ----------------------------------------------------------------------
# Heavy imports
# ----------------------------------------------------------------------
def load_heavy_modules():
    global telegram, openai, ChatAction, MessageEntityType
    from telegram import Update, Chat
    from telegram.constants import ChatAction
    from telegram import MessageEntity as MessageEntityType
    from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
    import openai
    logger.info("PTB & OpenAI loaded.")

# ----------------------------------------------------------------------
# Cerebras & memory
# ----------------------------------------------------------------------
def get_cerebras_client():
    return openai.AsyncOpenAI(
        api_key=os.environ["CEREBRAS_API_KEY"],
        base_url="https://api.cerebras.ai/v1",
    )

MAX_HISTORY = 20
SYSTEM_PROMPT = (
    "Ти - український козак на ім'я Синевир із Галичини. "
    "Говори галицьким діалектом, використовуй автентичну лексику, "
    "приказки, вульгаризми. Відповідай дотепно, сміливо, з козацькою вдачею. "
    "Відповідай українською мовою або суржиком. "
    "Пам'ятай попередні повідомлення цієї розмови."
)

async def generate_ai_response(chat_data: dict, user_message: str) -> str:
    client = get_cerebras_client()
    history = chat_data.setdefault("history", [])
    history.append({"role": "user", "content": user_message})
    if len(history) > MAX_HISTORY * 2:
        history = history[-(MAX_HISTORY * 2):]
        chat_data["history"] = history
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    response = await client.chat.completions.create(
        model="zai-glm-4.7",
        messages=messages,
        temperature=0.9,
        max_tokens=500,
    )
    content = response.choices[0].message.content.strip()
    if not content:
        raise ValueError("Empty response from Cerebras")
    history.append({"role": "assistant", "content": content})
    if len(history) > MAX_HISTORY * 2:
        history = history[-(MAX_HISTORY * 2):]
    chat_data["history"] = history
    return content

# ----------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------
async def ping_command(update, context):
    """A simple ping command to test connectivity."""
    await update.message.reply_text("Я тут, як дуб у лісі! Синевир на зв'язку.")

async def log_all_group_messages(update, context):
    """
    This handler just logs every group message for debugging.
    It does nothing else – we'll first try the real handler, then if it
    doesn't match, this logging handler will still fire (if both are used).
    Actually, we'll attach a separate handler to log, but PTB will call
    the first matching handler; we'll combine into one.
    For debugging, we'll simply log inside group_message_handler before any return.
    """

async def group_message_handler(update, context):
    msg = update.message
    if not msg or not msg.text:
        logger.info("Group message without text ignored.")
        return

    chat = update.effective_chat
    logger.info(f"Message in {chat.type} {chat.id} from {msg.from_user.username}: '{msg.text}'")

    if chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        logger.info("Not a group/supergroup, ignoring.")
        return

    bot_username = context.bot.username.lower()
    text = msg.text

    # Check triggers
    is_mention = False
    if msg.entities:
        for e in msg.entities:
            if e.type == MessageEntityType.MENTION:
                mentioned = e.extract_from(text).lower()
                if mentioned == f"@{bot_username}":
                    is_mention = True
                    logger.info(f"Mention detected: {mentioned}")
                    break

    is_reply_to_bot = (
        msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id
    )
    has_trigger = contains_trigger(text)

    logger.info(f"Flags: mention={is_mention}, reply_to_bot={is_reply_to_bot}, trigger={has_trigger}")

    if not (is_mention or is_reply_to_bot or has_trigger):
        logger.info("Message ignored – no trigger, mention, or reply.")
        return

    # Determine query
    if is_reply_to_bot:
        query = text
    elif is_mention and not has_trigger:
        query = remove_mention(text, bot_username)
    elif has_trigger and not is_mention:
        query = text
    else:
        query = remove_mention(text, bot_username)

    logger.info(f"Processing query: '{query}'")
    await process_and_reply(update, context, query)

async def process_and_reply(update, context, user_query: str):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        ai_raw = await generate_ai_response(context.chat_data, user_query)
        styled = stylize_response(ai_raw)
        await update.message.reply_text(styled, reply_to_message_id=update.message.message_id)
        logger.info("Reply sent successfully.")
    except Exception as e:
        logger.warning(f"AI error: {e}")
        fallback = stylize_response("Синевир не при пам'яті, спробуй пізніше.")
        await update.message.reply_text(fallback, reply_to_message_id=update.message.message_id)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
async def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    cerebras = os.environ.get("CEREBRAS_API_KEY")
    external_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not token or not cerebras or not external_url:
        logger.critical("Missing env vars.")
        sys.exit(1)
    port = int(os.environ.get("PORT", 8443))

    # Dummy listener
    dummy_task = asyncio.create_task(dummy_listener(port))
    await asyncio.sleep(0.2)

    load_heavy_modules()

    # Build Application
    application = Application.builder().token(token).build()

    # Register /ping command handler (works in private and groups)
    application.add_handler(CommandHandler("ping", ping_command))

    # Register group message handler (no command filter, but we'll still ignore commands manually)
    # We'll use a filter that accepts all text messages in groups (including those that might be commands)
    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.TEXT, group_message_handler)
    )

    # Set webhook
    webhook_url = f"{external_url}/{token}"
    success = await application.bot.set_webhook(url=webhook_url)
    if not success:
        logger.critical("Webhook setup returned False")
        sys.exit(1)
    logger.info(f"Webhook set to {webhook_url}")

    # Fetch and log webhook info
    try:
        info = await application.bot.get_webhook_info()
        logger.info(f"Webhook info: url={info.url}, pending_update_count={info.pending_update_count}, last_error_date={info.last_error_date}, last_error_message={info.last_error_message}")
    except Exception as e:
        logger.warning(f"Couldn't fetch webhook info: {e}")

    # Stop dummy
    dummy_task.cancel()
    try:
        await dummy_task
    except asyncio.CancelledError:
        pass
    logger.info("Starting PTB webhook server...")
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
        print(f"Fatal: {e}", flush=True)
        sys.exit(1)
