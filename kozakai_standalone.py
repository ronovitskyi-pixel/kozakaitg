#!/usr/bin/env python3
"""
KozakAI Telegram Bot – A Cossack Warrior from Halychyna
========================================================
A Python Telegram bot that responds only when mentioned in group chats,
integrates with Cerebras AI (zai-glm-4.7 model), and speaks with
a traditional Halychynian (Western Ukrainian) Kozak dialect,
including authentic swear words and colloquialisms.

Deployment on Render.com:
  1. Create a new Web Service on Render.
  2. Add environment variables:
       TELEGRAM_TOKEN   – Your Telegram bot token
       CEREBRAS_API_KEY – Your Cerebras API key
     (No PORT or WEBHOOK_URL needed; Render sets them automatically.)
  3. Build command: pip install -r requirements.txt
  4. Start command: python kozakai_standalone.py
  5. The bot will set its webhook to https://<your-service>.onrender.com/<TOKEN>

Requirements (create a requirements.txt with these contents):
    python-telegram-bot>=20.0,<21
    openai>=1.0.0
    aiohttp

Run tests locally:
    python kozakai_standalone.py --test
"""

import os
import re
import sys
import json
import random
import logging
import asyncio

# Third-party imports
# Fix: ChatAction is now in telegram.constants (python-telegram-bot >=20.0)
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

# ----------------------------------------------------------------------
# Logging configuration
# ----------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Kozak speech style constants
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
# Helper functions
# ----------------------------------------------------------------------
def stylize_response(text: str) -> str:
    """
    Inject Halychynian Kozak flair into the given text.
    Adds a random opening phrase, closing phrase, and sometimes a swear word.
    """
    if not text:
        text = "Нічого не скажу."

    opening = random.choice(OPENINGS)
    closing = random.choice(CLOSINGS)
    insert_swear = random.random() < 0.6

    if insert_swear:
        swear = random.choice(SWEAR_WORDS)
        # Prepend the swear word before the original text.
        text = f"{swear}, {text}"

    result = f"{opening}{text}{closing}".strip()
    # Make sure we don't start or end awkwardly
    return result


def remove_mention(text: str, bot_username: str) -> str:
    """
    Remove the first occurrence of @bot_username (case-insensitive) from the text.
    Returns the cleaned string.
    """
    # Simple regex substitution, case-insensitive, whole mention.
    pattern = rf"@{re.escape(bot_username)}\s*"
    cleaned = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else "Що?"


# ----------------------------------------------------------------------
# Cerebras API integration
# ----------------------------------------------------------------------
def get_cerebras_client() -> openai.AsyncOpenAI:
    """Create and return an authenticated AsyncOpenAI client for Cerebras."""
    try:
        api_key = os.environ["CEREBRAS_API_KEY"]
    except KeyError:
        logger.critical("CEREBRAS_API_KEY environment variable not set.")
        raise
    return openai.AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.cerebras.ai/v1",
    )


async def generate_ai_response(user_message: str) -> str:
    """
    Call the Cerebras API with the zai-glm-4.7 model.
    The system prompt already sets the Kozak character, so the AI
    replies in dialect. Post-processing adds extra flavour.
    """
    client = get_cerebras_client()
    system_prompt = (
        "Ти - український козак із Галичини на ім'я Вася. "
        "Говори галицьким діалектом, використовуй автентичну лексику, "
        "приказки, вульгаризми. Відповідай дотепно, сміливо, з козацькою вдачею. "
        "Відповідай українською мовою або суржиком."
        "Відповідай як філософ часто курячи сигару"
    )
    try:
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
    except Exception as exc:
        logger.error(f"Cerebras API call failed: {exc}", exc_info=True)
        raise  # Re-raise to be caught by caller


# ----------------------------------------------------------------------
# Bot logic
# ----------------------------------------------------------------------
async def process_and_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_query: str
) -> None:
    """Core handler: send typing action, call AI, style response, reply."""
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        ai_raw = await generate_ai_response(user_query)
        styled = stylize_response(ai_raw)
        await update.message.reply_text(
            styled, reply_to_message_id=update.message.message_id
        )
    except Exception as exc:
        logger.warning(f"Processing failed for query '{user_query}': {exc}")
        fallback = stylize_response("Козак не при пам'яті, спробуй пізніше.")
        await update.message.reply_text(
            fallback, reply_to_message_id=update.message.message_id
        )


async def group_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handler for all text messages in groups/supergroups.
    Filters out messages that do not mention the bot (by @username)
    or are not replies to the bot's own messages.
    """
    message = update.message
    if message is None or message.text is None:
        return

    chat = update.effective_chat
    if chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        return

    bot_username = context.bot.username.lower()
    mentioned = False
    is_reply_to_bot = False

    # Check for @bot_username in message entities
    if message.entities:
        for entity in message.entities:
            if entity.type == MessageEntityType.MENTION:
                mentioned_user = entity.extract_from(message.text).lower()
                if mentioned_user == f"@{bot_username}":
                    mentioned = True
                    break

    # Check if the message is a reply to one of the bot's messages
    if (
        message.reply_to_message
        and message.reply_to_message.from_user.id == context.bot.id
    ):
        is_reply_to_bot = True

    if not (mentioned or is_reply_to_bot):
        return  # Ignore the message

    # Remove mention when triggered by @username
    user_query = message.text
    if mentioned:
        user_query = remove_mention(message.text, bot_username)

    await process_and_reply(update, context, user_query)


# ----------------------------------------------------------------------
# Webhook setup and application entry point
# ----------------------------------------------------------------------
async def main() -> None:
    """Configure the bot, set webhook, and start the webhook server."""
    # Read mandatory environment variables
    try:
        token = os.environ["TELEGRAM_TOKEN"]
        cerebras_key = os.environ["CEREBRAS_API_KEY"]
    except KeyError as e:
        logger.critical(f"Missing environment variable: {e}")
        sys.exit(1)

    # Build the PTB Application without updater (webhook mode)
    application = Application.builder().token(token).build()

    # Register the handler for group text messages (non-commands)
    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            group_message_handler,
        )
    )

    # Determine port and webhook URL (Render sets PORT, provides RENDER_EXTERNAL_URL)
    port = int(os.environ.get("PORT", 8443))
    external_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not external_url:
        logger.warning(
            "RENDER_EXTERNAL_URL not set – using default https://example.com"
        )
        external_url = "https://example.com"
    webhook_url = f"{external_url}/{token}"

    # Set the webhook with Telegram
    await application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

    # Run the webhook server (this call blocks)
    await application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=token,
        webhook_url=webhook_url,
    )


# ----------------------------------------------------------------------
# Unit tests (run with python kozakai_standalone.py --test)
# ----------------------------------------------------------------------
def run_tests() -> None:
    """Run unit tests for core functions."""
    import unittest
    from unittest.mock import AsyncMock, MagicMock, patch

    class TestKozakAI(unittest.TestCase):
        # ---------- stylize_response ----------
        def test_stylize_returns_string(self):
            result = stylize_response("Hello")
            self.assertIsInstance(result, str)

        def test_stylize_contains_opening_or_closing(self):
            result = stylize_response("Щось")
            has_opening = any(op in result for op in OPENINGS)
            has_closing = any(cl in result for cl in CLOSINGS)
            self.assertTrue(has_opening or has_closing, msg="No Kozak flair injected")

        def test_stylize_empty_input(self):
            result = stylize_response("")
            self.assertIn("Нічого не скажу", result)

        # ---------- remove_mention ----------
        def test_remove_mention_case_insensitive(self):
            text = "Привіт @KozakAI як справи?"
            cleaned = remove_mention(text, "kozakai")
            self.assertNotIn("@KozakAI", cleaned)
            self.assertIn("Привіт", cleaned)
            self.assertIn("як справи?", cleaned)

        def test_remove_mention_no_mention_returns_unchanged(self):
            text = "Звичайне повідомлення"
            cleaned = remove_mention(text, "kozakai")
            self.assertEqual(cleaned, text)

        def test_remove_mention_only_mention_returns_default(self):
            text = "@KozakAI"
            cleaned = remove_mention(text, "kozakai")
            self.assertEqual(cleaned, "Що?")

        # ---------- generate_ai_response ----------
        @patch.dict(os.environ, {"CEREBRAS_API_KEY": "test-key"})
        async def test_generate_ai_response_success(self):
            mock_response = MagicMock()
            mock_response.choices = [
                MagicMock(message=MagicMock(content="  Відповідь козака  "))
            ]
            mock_client = AsyncMock()
            mock_client.chat.completions.create.return_value = mock_response

            with patch("openai.AsyncOpenAI", return_value=mock_client) as mc:
                response = await generate_ai_response("Чи ти козак?")
                self.assertEqual(response, "Відповідь козака")
                mc.assert_called_once_with(
                    api_key="test-key", base_url="https://api.cerebras.ai/v1"
                )

        @patch.dict(os.environ, {"CEREBRAS_API_KEY": "test-key"})
        async def test_generate_ai_response_empty_content_raises(self):
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content="   "))]
            mock_client = AsyncMock()
            mock_client.chat.completions.create.return_value = mock_response
            with patch("openai.AsyncOpenAI", return_value=mock_client):
                with self.assertRaises(ValueError):
                    await generate_ai_response("Hello")

        @patch.dict(os.environ, {"CEREBRAS_API_KEY": "test-key"})
        async def test_generate_ai_response_api_error(self):
            mock_client = AsyncMock()
            mock_client.chat.completions.create.side_effect = openai.APIError(
                "Server error"
            )
            with patch("openai.AsyncOpenAI", return_value=mock_client):
                with self.assertRaises(openai.APIError):
                    await generate_ai_response("Hello")

    # Run the tests (handles async tests correctly)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestKozakAI)

    # Make the async tests run in the event loop
    for test_case in suite:
        for test in test_case:
            if asyncio.iscoroutinefunction(test._testMethodName):
                orig = getattr(test_case, test._testMethodName)
                def make_wrapper(m=orig):
                    def wrapper(tc):
                        return asyncio.run(m(tc))
                    return wrapper
                setattr(test_case, test._testMethodName, make_wrapper())

    unittest.TextTestRunner(verbosity=2).run(suite)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_tests()
    else:
        asyncio.run(main())
