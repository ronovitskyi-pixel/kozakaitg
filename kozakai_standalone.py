#!/usr/bin/env python3
"""
KozakAI Telegram Bot – with startup diagnosis
"""

import os, sys, re, random, logging, asyncio

# Print immediately to diagnose startup
print("=== KozakAI starting ===", flush=True)

# ----------------------------------------------------------------------
# Logging (to stdout only)
# ----------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Third-party imports
# ----------------------------------------------------------------------
try:
    print("Importing libraries...", flush=True)
    from telegram import Update, Chat
    from telegram.constants import ChatAction
    from telegram import MessageEntity as MessageEntityType
    from telegram.ext import Application, MessageHandler, filters, ContextTypes
    import openai
    from aiohttp import web
    print("Imports OK", flush=True)
except Exception as e:
    print(f"Import error: {e}", flush=True)
    sys.exit(1)

# ----------------------------------------------------------------------
# Kozak style constants
# ----------------------------------------------------------------------
OPENINGS = ["Ото ж бо, ", "Гей-гей, козаче, ", "Слухай сюди, ", "А може, ", "Ой, лишенько, ", "Йой, ", "Но-но, ", "Та й що, "]
CLOSINGS = [" Аякже!", " Чи не так?", " Та й годі!", " От і вся правда.", " А ти як думав?", " Хіба ж не так?", " Бодай тобі!", ""]
SWEAR_WORDS = ["курва", "шляк", "лайдак", "зараза", "бодай тебе", "чорт", "дідько", "матері його ковінька", "псяча віра", "сто чортів"]

def stylize_response(text):
    if not text:
        text = "Нічого не скажу."
    opening = random.choice(OPENINGS)
    closing = random.choice(CLOSINGS)
    if random.random() < 0.6:
        text = f"{random.choice(SWEAR_WORDS)}, {text}"
    return f"{opening}{text}{closing}".strip()

def remove_mention(text, bot_username):
    pattern = rf"@{re.escape(bot_username)}\s*"
    cleaned = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else "Що?"

# ----------------------------------------------------------------------
# Cerebras API
# ----------------------------------------------------------------------
def get_cerebras_client():
    key = os.environ.get("CEREBRAS_API_KEY")
    if not key:
        print("ERROR: CEREBRAS_API_KEY not set", flush=True)
        sys.exit(1)
    return openai.AsyncOpenAI(api_key=key, base_url="https://api.cerebras.ai/v1")

async def generate_ai_response(user_message):
    client = get_cerebras_client()
    system_prompt = (
        "Ти - український козак із Галичини на ім'я Синевир. "
        "Говори галицьким діалектом, використовуй автентичну лексику, "
        "приказки, вульгаризми. Відповідай дотепно, сміливо, з козацькою вдачею. "
        "Відповідай українською мовою або суржиком."
    )
    response = await client.chat.completions.create(
        model="zai-glm-4.7",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        temperature=0.9, max_tokens=500,
    )
    content = response.choices[0].message.content.strip()
    if not content:
        raise ValueError("Empty response from Cerebras")
    return content

# ----------------------------------------------------------------------
# Bot handlers
# ----------------------------------------------------------------------
async def process_and_reply(update, context, user_query):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    try:
        ai_raw = await generate_ai_response(user_query)
        await update.message.reply_text(stylize_response(ai_raw), reply_to_message_id=update.message.message_id)
    except Exception as e:
        logger.warning(f"AI failed: {e}")
        await update.message.reply_text(stylize_response("Козак не при пам'яті, спробуй пізніше."), reply_to_message_id=update.message.message_id)

async def group_message_handler(update, context):
    msg = update.message
    if not msg or not msg.text:
        return
    if update.effective_chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        return
    bot_username = context.bot.username.lower()
    mentioned = False
    is_reply = bool(msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id)
    if msg.entities:
        for e in msg.entities:
            if e.type == MessageEntityType.MENTION and e.extract_from(msg.text).lower() == f"@{bot_username}":
                mentioned = True
                break
    if not (mentioned or is_reply):
        return
    query = msg.text if is_reply else remove_mention(msg.text, bot_username)
    await process_and_reply(update, context, query)

# ----------------------------------------------------------------------
# Simple health endpoint (to test port binding)
# ----------------------------------------------------------------------
async def health(request):
    return web.Response(text="OK")

# ----------------------------------------------------------------------
# Main with complete diagnostics
# ----------------------------------------------------------------------
async def main():
    print("Checking environment...", flush=True)
    token = os.environ.get("TELEGRAM_TOKEN")
    cerebras = os.environ.get("CEREBRAS_API_KEY")
    external_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    port = int(os.environ.get("PORT", 8443))

    if not token:
        print("CRITICAL: TELEGRAM_TOKEN missing. Starting dummy health server on port to verify connectivity...", flush=True)
        app = web.Application()
        app.add_routes([web.get("/", health)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        print(f"Starting dummy server on port {port} – check Render's open port detection.", flush=True)
        await site.start()
        while True:
            await asyncio.sleep(3600)  # keep alive
    if not cerebras:
        print("CRITICAL: CEREBRAS_API_KEY missing", flush=True)
        sys.exit(1)

    print(f"Telegram token present (length {len(token)}), Cerebras key present, external URL: {external_url}", flush=True)
    webhook_url = f"{external_url}/{token}"

    # Build PTB application
    try:
        application = Application.builder().token(token).build()
    except Exception as e:
        print(f"Failed to build Application: {e}", flush=True)
        sys.exit(1)

    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, group_message_handler))

    # Set webhook
    try:
        result = await application.bot.set_webhook(url=webhook_url)
        print(f"Webhook set returned: {result}, url: {webhook_url}", flush=True)
        if not result:
            print("Webhook rejected by Telegram. Exiting.", flush=True)
            sys.exit(1)
    except Exception as e:
        print(f"Webhook setup exception: {e}", flush=True)
        sys.exit(1)

    # Start webhook server
    print(f"Starting webhook server on 0.0.0.0:{port}, path /{token}", flush=True)
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
        print(f"Fatal exception: {e}", flush=True)
        sys.exit(1)
