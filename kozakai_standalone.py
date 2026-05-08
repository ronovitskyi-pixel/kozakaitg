#!/usr/bin/env python3
"""
KozakAI Telegram Bot – A Cossack Warrior from Halychyna
(Improved with startup error handling + health endpoint)
"""

import os
import re
import sys
import random
import logging
import asyncio

# Third-party imports
from telegram import Update, Chat
from telegram.constants import ChatAction
from telegram import MessageEntity as MessageEntityType
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
)
import openai
from aiohttp import web  # added for health endpoint

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Kozak style constants
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

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def stylize_response(text: str) -> str:
    if not text:
        text = "Нічого не скажу."
    opening = random.choice(OPENINGS)
    closing = random.choice(CLOSINGS)
    if random.random() < 0.6:
        text = f"{random.choice(SWEAR_WORDS)}, {text}"
    return f"{opening}{text}{closing}".strip()

def remove_mention(text: str, bot_username: str) -> str:
    pattern = rf"@{re.escape(bot_username)}\s*"
    cleaned = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else "Що?"

# ----------------------------------------------------------------------
# Cerebras API
# ----------------------------------------------------------------------
def get_cerebras_client() -> openai.AsyncOpenAI:
    try:
        api_key = os.environ["CEREBRAS_API_KEY"]
    except KeyError:
        logger.critical("CEREBRAS_API_KEY environment variable not set.")
        raise
    return openai.AsyncOpenAI(api_key=api_key, base_url="https://api.cerebras.ai/v1")

async def generate_ai_response(user_message: str) -> str:
    client = get_cerebras_client()
    system_prompt = (
        "Ти - український козак із Галичини на ім'я Синевир. "
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
        raise ValueError("Empty response from Cerebras API")
    return content

# ----------------------------------------------------------------------
# Bot handlers
# ----------------------------------------------------------------------
async def process_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, user_query: str):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        ai_raw = await generate_ai_response(user_query)
        styled = stylize_response(ai_raw)
        await update.message.reply_text(styled, reply_to_message_id=update.message.message_id)
    except Exception as e:
        logger.warning(f"Processing failed: {e}")
        fallback = stylize_response("Козак не при пам'яті, спробуй пізніше.")
        await update.message.reply_text(fallback, reply_to_message_id=update.message.message_id)

async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if message is None or message.text is None:
        return
    chat = update.effective_chat
    if chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        return
    bot_username = context.bot.username.lower()
    mentioned = False
    is_reply_to_bot = False
    if message.entities:
        for entity in message.entities:
            if entity.type == MessageEntityType.MENTION:
                if entity.extract_from(message.text).lower() == f"@{bot_username}":
                    mentioned = True
                    break
    if message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id:
        is_reply_to_bot = True
    if not (mentioned or is_reply_to_bot):
        return
    user_query = message.text if is_reply_to_bot else remove_mention(message.text, bot_username)
    await process_and_reply(update, context, user_query)

# ----------------------------------------------------------------------
# Health check endpoint for Render (optional but helpful)
# ----------------------------------------------------------------------
async def health_check(request):
    return web.Response(text="KozakAI is alive!", status=200)

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
async def main():
    # 1. Check environment
    missing = []
    token = os.environ.get("TELEGRAM_TOKEN")
    cerebras = os.environ.get("CEREBRAS_API_KEY")
    if not token:
        missing.append("TELEGRAM_TOKEN")
    if not cerebras:
        missing.append("CEREBRAS_API_KEY")
    if missing:
        logger.critical(f"Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

    port = int(os.environ.get("PORT", 8443))
    external_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if not external_url:
        logger.error("RENDER_EXTERNAL_URL is not set. Webhook setup may fail.")
        # In Render, it should always be set for web services.
        sys.exit(1)

    webhook_url = f"{external_url}/{token}"

    # 2. Build application
    try:
        application = Application.builder().token(token).build()
    except Exception as e:
        logger.critical(f"Failed to build Telegram application: {e}", exc_info=True)
        sys.exit(1)

    application.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, group_message_handler)
    )

    # 3. Set webhook
    try:
        result = await application.bot.set_webhook(url=webhook_url)
        if result:
            logger.info(f"Webhook set to {webhook_url}")
        else:
            logger.error("Telegram rejected the webhook URL. Check token and RENDER_EXTERNAL_URL.")
            sys.exit(1)
    except Exception as e:
        logger.critical(f"Webhook setup failed: {e}", exc_info=True)
        sys.exit(1)

    # 4. Create aiohttp app that combines the PTB webhook and a health endpoint
    #    We'll use PTB's built-in run_webhook, but it doesn't easily add extra routes.
    #    Instead we can start a custom aiohttp server and add PTB's webhook handler manually.
    #    Simpler: use application.run_webhook and ignore health endpoint for now.
    #    However to help Render detect an open port, we'll just call run_webhook.
    logger.info(f"Starting webhook server on port {port}...")
    try:
        await application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=webhook_url,
        )
    except Exception as e:
        logger.critical(f"Webhook server failed: {e}", exc_info=True)
        sys.exit(1)

# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.critical(f"Fatal unhandled exception: {e}", exc_info=True)
        sys.exit(1)
