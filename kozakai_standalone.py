#!/usr/bin/env python3
"""
KozakAI Telegram Bot – Синевир, the Halychynian Cossack (with memory + keyword trigger)
=========================================================================================
- Responds in groups when someone writes @kozak_aibot, replies to the bot,
  or includes any of the trigger words (case‑insensitive) in the message:
    козак, козаче, друже, синевир, синевире, козакai, kozakai, синевирai
- Maintains the last 20 messages as conversation history (per chat).
- Deploys on Render.com (Python 3.12) using a dummy listener for instant port binding.
"""

import os
import sys
import re
import random
import logging
import asyncio

print("=== KozakAI Синевир starting ===", flush=True)

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
# Trigger keywords (any of these in a group message will activate the bot)
# ----------------------------------------------------------------------
TRIGGER_WORDS = [
    "козак", "козаче", "друже", "синевир", "синевире",
    "козакai", "kozakai", "синевирai",
]

def contains_trigger(text: str) -> bool:
    """Return True if the text contains any trigger word (case‑insensitive)."""
    lower = text.lower()
    return any(word in lower for word in TRIGGER_WORDS)

def remove_mention(text: str, bot_username: str) -> str:
    pattern = rf"@{re.escape(bot_username)}\s*"
    cleaned = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else "Що?"

# ----------------------------------------------------------------------
# Dummy TCP listener – keeps Render’s port alive while libraries load
# ----------------------------------------------------------------------
async def dummy_listener(port: int):
    async def handle(reader, writer):
        writer.close()
    server = await asyncio.start_server(handle, "0.0.0.0", port)
    logger.info(f"Dummy listener on port {port} for Render")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        server.close()
        await server.wait_closed()
        logger.info("Dummy listener stopped, port released.")

# ----------------------------------------------------------------------
# Heavy imports (load after port is open)
# ----------------------------------------------------------------------
def load_heavy_modules():
    global telegram, openai, ChatAction, MessageEntityType
    from telegram import Update, Chat
    from telegram.constants import ChatAction
    from telegram import MessageEntity as MessageEntityType
    from telegram.ext import Application, MessageHandler, filters, ContextTypes
    import openai
    logger.info("PTB & OpenAI loaded.")

# ----------------------------------------------------------------------
# Cerebras API & memory
# ----------------------------------------------------------------------
def get_cerebras_client():
    return openai.AsyncOpenAI(
        api_key=os.environ["CEREBRAS_API_KEY"],
        base_url="https://api.cerebras.ai/v1",
    )

# Maximum history length (number of messages), to keep API costs reasonable
MAX_HISTORY = 20

SYSTEM_PROMPT = (
    "Ти - український козак на ім'я Синевир із Галичини. "
    "Говори галицьким діалектом, використовуй автентичну лексику, "
    "приказки, вульгаризми. Відповідай дотепно, сміливо, з козацькою вдачею. "
    "Відповідай українською мовою або суржиком. "
    "Пам'ятай попередні повідомлення цієї розмови."
)

async def generate_ai_response(chat_data: dict, user_message: str) -> str:
    """Call Cerebras with conversation history from chat_data."""
    client = get_cerebras_client()

    # Retrieve or initialise history
    history = chat_data.setdefault("history", [])
    # Append the new user message
    history.append({"role": "user", "content": user_message})
    # Trim history if too long (keep the last MAX_HISTORY * 2 entries, i.e. user+assistant pairs)
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

    # Store assistant response in history
    history.append({"role": "assistant", "content": content})
    # Trim again after adding
    if len(history) > MAX_HISTORY * 2:
        history = history[-(MAX_HISTORY * 2):]
    chat_data["history"] = history

    return content

# ----------------------------------------------------------------------
# Bot handlers
# ----------------------------------------------------------------------
async def process_and_reply(update, context, user_query: str):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        ai_raw = await generate_ai_response(context.chat_data, user_query)
        styled = stylize_response(ai_raw)
        await update.message.reply_text(styled, reply_to_message_id=update.message.message_id)
    except Exception as e:
        logger.warning(f"AI or processing error: {e}")
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
    text = msg.text

    # Conditions to respond:
    # 1. @mention
    # 2. Direct reply to bot
    # 3. Contains any trigger word
    is_mention = False
    if msg.entities:
        for e in msg.entities:
            if e.type == MessageEntityType.MENTION:
                if e.extract_from(text).lower() == f"@{bot_username}":
                    is_mention = True
                    break

    is_reply_to_bot = (
        msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id
    )

    has_trigger = contains_trigger(text)

    if not (is_mention or is_reply_to_bot or has_trigger):
        return

    # Determine the actual query to send to the AI
    if is_reply_to_bot:
        # Use the whole message
        query = text
    elif is_mention and not has_trigger:
        # Only mention, remove it
        query = remove_mention(text, bot_username)
    elif has_trigger and not is_mention:
        # Only keyword, keep whole message
        query = text
    else:
        # Both mention and keyword – remove mention to avoid redundancy
        query = remove_mention(text, bot_username)

    await process_and_reply(update, context, query)

# ----------------------------------------------------------------------
# Main – dummy listener → load libs → set webhook → PTB server
# ----------------------------------------------------------------------
async def main():
    # 1. Check env
    token = os.environ.get("TELEGRAM_TOKEN")
    cerebras = os.environ.get("CEREBRAS_API_KEY")
    external_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not token or not cerebras or not external_url:
        logger.critical("Missing TELEGRAM_TOKEN, CEREBRAS_API_KEY, or RENDER_EXTERNAL_URL")
        sys.exit(1)
    port = int(os.environ.get("PORT", 8443))

    # 2. Dummy listener
    dummy_task = asyncio.create_task(dummy_listener(port))
    await asyncio.sleep(0.2)

    # 3. Load heavy libs
    load_heavy_modules()

    # 4. Build PTB app
    application = Application.builder().token(token).build()
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            group_message_handler,
        )
    )

    # 5. Set webhook
    webhook_url = f"{external_url}/{token}"
    try:
        ok = await application.bot.set_webhook(url=webhook_url)
        if not ok:
            logger.critical("Telegram rejected webhook")
            sys.exit(1)
        logger.info(f"Webhook set: {webhook_url}")
    except Exception as e:
        logger.critical(f"Webhook setup failed: {e}")
        sys.exit(1)

    # 6. Stop dummy, start PTB server
    dummy_task.cancel()
    try:
        await dummy_task
    except asyncio.CancelledError:
        pass
    logger.info(f"Port {port} released, starting PTB webhook server...")
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
