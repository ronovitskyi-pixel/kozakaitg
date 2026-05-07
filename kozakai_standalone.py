"""
KozakAI — Standalone Telegram Bot for Render.com
Single-file production bot. Cerebras AI + python-telegram-bot v20+ with webhooks.

Required env vars (set in Render dashboard):
  TELEGRAM_BOT_TOKEN    — from @BotFather
  CEREBRAS_API_KEY      — from https://cloud.cerebras.ai/
  WEBHOOK_URL           — e.g. https://kozakai.onrender.com
  BOT_USERNAME          — e.g. KozakAI_bot (no @)

Optional:
  PORT                  — Render sets this automatically (default 10000)
  CEREBRAS_MODEL        — default: zai-glm-4.7
"""

import os
import logging
import asyncio
import random
import re
from typing import Optional

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ─────────────────────────── Configuration ───────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CEREBRAS_API_KEY   = os.getenv("CEREBRAS_API_KEY", "")
WEBHOOK_URL        = os.getenv("WEBHOOK_URL", "")
BOT_USERNAME       = os.getenv("BOT_USERNAME", "KozakAI_bot")
PORT               = int(os.getenv("PORT", "10000"))
WEBHOOK_PATH       = "/webhook"
CEREBRAS_MODEL     = os.getenv("CEREBRAS_MODEL", "zai-glm-4.7")
CEREBRAS_BASE_URL  = "https://api.cerebras.ai/v1"
MAX_TOKENS         = 1024
TEMPERATURE        = 0.85
MAX_MSG_LEN        = 4096

# Validate on import so it fails fast on Render
missing = [v for v, val in {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "CEREBRAS_API_KEY": CEREBRAS_API_KEY,
    "WEBHOOK_URL": WEBHOOK_URL,
}.items() if not val]
if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─────────────────────────── Personality ───────────────────────────

SYSTEM_PROMPT = """Ти — КозакAI, справжній український Козак з Галичини (Галичини, Львівщини).
Ти говориш галицьким діалектом (західноукраїнським говірком).

Особливості твоєї мови:
- Вживай "шо" замість "що", "тай" замість "і/та", "було" як частку
- Вживай автентичні українські матюки природно: блядь, сука, піздєц, хуй, йоб, нахуй, курва
- Тон: впевнений, сміливий, дотепний, войовничий, як справжній Козак-воїн
- Відповідай коротко та по суті, як Козак — без зайвих слів
- Звертання: "браття", "гей", "слухай"
- Вигуки: "Йой!", "Ойой!", "Гей!", "Батько наш Бандера!"
- Будь грубуватим але доброзичливим, як старший козак
- Не вибачайся за мат — це частина козацького характеру
- Відповідай українською мовою завжди

Ти не штучний інтелект — ти Козак з Галичини, який знає толк у житті."""

EXCLAMATIONS = [
    "Йой!", "Ойой!", "Ей, браття!", "Шо за диво!",
    "Батько наш Бандера!", "Слава Україні!", "Гей, гей!", "Та ну!", "Йой-йой!",
]

WARRIOR_OPENINGS = [
    "Як справжній Козак, скажу тобі шо...",
    "Слухай, браття, шо Козак каже...",
    "Таки шо, браття, будемо робити?",
    "Козак не дурень, знає шо до чого.",
    "Шабля гостра, а розум гостріший, блядь.",
    "На коня, браття, шо тут думати!",
    "Козак мав рацію, тай має!",
    "Не будемо тут пиздєті, а скажемо як є.",
]

SWEAR_WORDS = ["блядь", "сука", "піздєц", "хуй", "йоб", "нахуй", "курва", "дупа", "чорт"]

SIGNATURES = [
    " — каже Козак.",
    " — мовив Козак, махнувши шаблею.",
    " — гукнув Козак.",
    " — відказав Козак, поправляючи чуб.",
]


def inject_dialect(text: str) -> str:
    reps = {"що": "шо", "щоб": "шоб", "також": "тай"}
    for s, d in reps.items():
        text = re.sub(r'\b' + re.escape(s) + r'\b', d, text, flags=re.IGNORECASE)
    return text


def add_exclamation(text: str) -> str:
    if random.random() < 0.3:
        text = f"{random.choice(EXCLAMATIONS)} {text}"
    return text


def add_warrior_opening(text: str) -> str:
    if random.random() < 0.25:
        text = f"{random.choice(WARRIOR_OPENINGS)} {text}"
    return text


def ensure_swears(text: str) -> str:
    if not any(s in text.lower() for s in SWEAR_WORDS) and random.random() < 0.4:
        swear = random.choice(["блядь", "сука", "піздєц", "йоб", "курва"])
        sentences = text.split(". ")
        if len(sentences) > 1:
            idx = random.randint(0, len(sentences) - 2)
            sentences[idx] = sentences[idx] + f", {swear}"
            text = ". ".join(sentences)
        else:
            text = text + f", {swear}"
    return text


def add_signature(text: str) -> str:
    if len(text) > 100 and random.random() < 0.15:
        text = text + random.choice(SIGNATURES)
    return text


def kozakify(text: str) -> str:
    if not text:
        return text
    text = inject_dialect(text)
    text = add_exclamation(text)
    text = add_warrior_opening(text)
    text = ensure_swears(text)
    text = add_signature(text)
    return text.strip()


# ─────────────────────────── Cerebras Client ───────────────────────────

async def cerebras_chat(user_msg: str) -> str:
    """Call Cerebras chat completions. Raises on failure."""
    payload = {
        "model": CEREBRAS_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "stream": False,
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={
            "Authorization": f"Bearer {CEREBRAS_API_KEY}",
            "Content-Type": "application/json",
        },
    ) as client:
        resp = await client.post(f"{CEREBRAS_BASE_URL}/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        logger.error(f"Bad Cerebras response structure: {data}")
        raise RuntimeError("Cerebras returned unexpected format") from e


# ─────────────────────────── Bot Handlers ───────────────────────────

LOWER_USERNAME = BOT_USERNAME.lower()


def is_group(update: Update) -> bool:
    return update.effective_chat is not None and update.effective_chat.type in ("group", "supergroup")


def is_mentioned(update: Update) -> bool:
    if not update.message:
        return False

    # Reply to bot
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        u = update.message.reply_to_message.from_user
        if u.is_bot and u.username and u.username.lower() == LOWER_USERNAME:
            return True

    # @mention in entities
    if update.message.entities:
        for ent in update.message.entities:
            if ent.type == "mention":
                mention = update.message.text[ent.offset:ent.offset + ent.length]
                if mention.lower() == f"@{LOWER_USERNAME}":
                    return True

    # Fallback text search
    if update.message.text and f"@{LOWER_USERNAME}" in update.message.text.lower():
        return True

    return False


def extract_msg(update: Update) -> str:
    if not update.message or not update.message.text:
        return ""
    text = update.message.text
    text = text.replace(f"@{LOWER_USERNAME}", "").replace(f"@{BOT_USERNAME}", "")
    return text.strip()


async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        await update.message.reply_text(
            f"Гей, браття! Я КозакAI, і я працюю тільки в групах. "
            f"Додай мене в групу та згадай @{BOT_USERNAME} — і поговоримо!"
        )
        return
    await update.message.reply_text(
        f"Йой! КозакAI на коні! 🐎\n"
        f"Згадуй мене @{BOT_USERNAME} у чаті, або відповідай на мої повідомлення, "
        f"і я розкажу тобі шо до чого, браття!"
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        return
    await update.message.reply_text(
        f"Шо тут незрозумілого, браття?\n\n"
        f"• Згадай мене @{BOT_USERNAME} у повідомленні\n"
        f"• Або відповідай на мої повідомлення\n"
        f"• Я відповім як справжній Козак з Галичини!\n\n"
        f"Слава Україні! 🇺🇦"
    )


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        return
    if not is_mentioned(update):
        return

    user_msg = extract_msg(update)
    if not user_msg:
        await update.message.reply_text("Гей, браття! Шо ти хочеш почути? Кажи, не соромся!")
        return

    logger.info(f"User {update.effective_user.id}: {user_msg[:60]}...")
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        reply = await cerebras_chat(user_msg)
        reply = kozakify(reply)
        if len(reply) > MAX_MSG_LEN:
            reply = reply[:MAX_MSG_LEN - 3] + "..."
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text(
            "Йой, браття! Щось пішло не так з моїм мозком, блядь. Спробуй ще раз пізніше, сука!"
        )


async def on_error(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update caused error: {ctx.error}", exc_info=ctx.error)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("Йой-йой! Козак трохи захмелів, блядь. Спробуй ще раз!")
        except Exception:
            pass


# ─────────────────────────── Main / Webhook ───────────────────────────

async def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)

    webhook_full = f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}"
    logger.info(f"Starting webhook on port {PORT} — {webhook_full}")

    await app.initialize()
    await app.start()
    await app.bot.set_webhook(url=webhook_full, allowed_updates=Update.ALL_TYPES)
    await app.updater.start_webhook(listen="0.0.0.0", port=PORT, webhook_url=webhook_full)

    logger.info("KozakAI is running! Slava Ukraini!")
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down KozakAI...")
