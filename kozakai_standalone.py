#!/usr/bin/env python3
import os
import sys
import re
import random
import logging
import asyncio
from aiohttp import web

# Імпортуємо все одразу, щоб уникнути проблем з областю видимості
from telegram import Update, Chat, MessageEntity
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
)
import openai

# Налаштування логування
logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("Синевир")

# --- Козацький антураж ---
OPENINGS = ["Ото ж бо, ", "Гей-гей, козаче, ", "Слухай сюди, ", "А може, ", "Ой, лишенько, ", "Йой, ", "Но-но, ", "Та й що, "]
CLOSINGS = [" Аякже!", " Чи не так?", " Та й годі!", " От і вся правда.", " А ти як думав?", " Хіба ж не так?"]
SWEAR_WORDS = ["курва", "шляк", "лайдак", "зараза", "дідько", "псяча віра", "сто чортів"]

def stylize(text):
    if not text: text = "Нічого не скажу."
    opening = random.choice(OPENINGS)
    closing = random.choice(CLOSINGS)
    if random.random() < 0.6:
        text = f"{random.choice(SWEAR_WORDS)}, {text}"
    return f"{opening}{text}{closing}".strip()

TRIGGERS = ["козак", "козаче", "друже", "синевир", "синевире", "kozakai"]

def has_trigger(text):
    return any(w in text.lower() for w in TRIGGERS)

# --- AI Логіка ---
SYSTEM_PROMPT = (
    "Ти - український козак на ім'я Синевир із Галичини. "
    "Говори галицьким діалектом, використовуй автентичну лексику. "
    "Відповідай дотепно, з козацькою вдачею."
)

async def generate_ai(chat_data, user_msg):
    key = os.environ.get("CEREBRAS_API_KEY")
    if not key: raise Exception("CEREBRAS_API_KEY missing")

    client = openai.AsyncOpenAI(api_key=key, base_url="https://api.cerebras.ai/v1")
    history = chat_data.setdefault("history", [])
    history.append({"role": "user", "content": user_msg})
    
    # Тримаємо історію короткою (20 повідомлень = 10 діалогів)
    if len(history) > 20: history = history[-20:]
    chat_data["history"] = history

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    resp = await client.chat.completions.create(
        model="llama3.1-8b", # Переконайтеся, що назва моделі вірна для Cerebras
        messages=messages,
        temperature=0.9,
    )
    content = resp.choices[0].message.content.strip()
    history.append({"role": "assistant", "content": content})
    return content

# --- Обробники ---
async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Я тут! Синевир на зв'язку. ⚔️")

async def group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text: return
    
    text = msg.text
    bot_uname = context.bot.username.lower()
    
    # Визначаємо, чи звертаються до бота
    is_mention = any(e.type == MessageEntity.MENTION and e.extract_from(text).lower() == f"@{bot_uname}" for e in (msg.entities or []))
    is_reply = msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id
    is_keyword = has_trigger(text)

    if not (is_mention or is_reply or is_keyword): return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        query = re.sub(rf"@{bot_uname}\s*", "", text, flags=re.IGNORECASE).strip() or "Що?"
        ai_reply = await generate_ai(context.chat_data, query)
        await msg.reply_text(stylize(ai_reply))
    except Exception as e:
        logger.error(f"AI error: {e}")
        await msg.reply_text("Синевир не при пам'яті, спробуй пізніше.")

# --- Main (Render Optimized) ---
async def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    ext_url = os.environ.get("RENDER_EXTERNAL_URL")
    port = int(os.environ.get("PORT", 8443))

    if not token or not ext_url:
        logger.critical("Missing TELEGRAM_TOKEN or RENDER_EXTERNAL_URL")
        sys.exit(1)

    # Побудова додатку
    application = Application.builder().token(token).build()
    
    # Хендлери
    application.add_handler(CommandHandler("ping", ping_cmd))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, group_handler))

    # Запуск Webhook через вбудований метод PTB
    # Це автоматично створить веб-сервер, який задовольнить Render
    logger.info(f"Starting bot on port {port}")
    
    await application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token, # Використовуємо токен як секретний шлях
        webhook_url=f"{ext_url}/{token}"
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.fatal(f"Startup failed: {e}")
