# from telegram import Update
# from openai import OpenAI
# import json

# from telegram.ext import (
#     ApplicationBuilder,
#     CommandHandler,
#     MessageHandler,
#     ContextTypes,
#     filters,
# )

# from dotenv import load_dotenv
# import os

# # Load variables from .env
# load_dotenv()

# AIPIPE_TOKEN = os.getenv("AIPIPE_TOKEN")

# client = OpenAI(
#     api_key=AIPIPE_TOKEN,
#     base_url="https://aipipe.org/openai/v1"
# )

# BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# # /start command
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     await update.message.reply_text("Bot is running!")


# # Echo every text message
# async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     user_message = update.message.text

#     try:
#         response = client.chat.completions.create(
#             model="gpt-5-nano",
#             messages=[
#                 {
#                     "role": "system",
#                     "content": (
#                         "You are a data analysis assistant. "
#                         "Always answer using valid JSON only."
#                     )
#                 },
#                 {
#                     "role": "user",
#                     "content": user_message
#                 }
#             ]
#         )

#         answer = response.choices[0].message.content

#         await update.message.reply_text(answer)

#     except Exception as e:
#         await update.message.reply_text(f"Error: {e}")


# app = ApplicationBuilder().token(BOT_TOKEN).build()

# app.add_handler(CommandHandler("start", start))
# app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

# print("Bot is running...")

# app.run_polling()


from telegram import Update
from openai import OpenAI
import json
import os
from datetime import datetime

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from dotenv import load_dotenv

# -------------------------
# Load Environment Variables
# -------------------------
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AIPIPE_TOKEN = os.getenv("AIPIPE_TOKEN")

# -------------------------
# OpenAI Client (AIPipe)
# -------------------------
client = OpenAI(
    api_key=AIPIPE_TOKEN,
    base_url="https://aipipe.org/openai/v1"
)

# -------------------------
# Conversation Memory
# -------------------------
conversation_history = {}

# -------------------------
# Log File
# -------------------------
LOG_FILE = "run.jsonl"


def write_log(entry):
    """Append one JSON object per line to run.jsonl"""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# -------------------------
# /start Command
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running!")


# -------------------------
# Main Chat Function
# -------------------------
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    user_message = update.message.text

    # Create memory for new user
    if chat_id not in conversation_history:
        conversation_history[chat_id] = [
            {
                "role": "system",
                "content": (
                    "You are a data analysis assistant.\n\n"
                    "Read the user's instructions carefully.\n"
                    "Return exactly ONE valid JSON object.\n"
                    "The user will specify the required JSON structure. Follow that structure exactly.\n"
                    "Do not add markdown.\n"
                    "Do not add explanations.\n"
                    "Do not add any text before or after the JSON.\n"
                    "Ensure the output is valid JSON."
                )
            }
        ]

    # Add user message to history
    conversation_history[chat_id].append(
        {
            "role": "user",
            "content": user_message
        }
    )

    # Log user message
    write_log({
        "timestamp": datetime.utcnow().isoformat(),
        "chat_id": chat_id,
        "event": "user_message",
        "message": user_message
    })

    try:

        response = client.chat.completions.create(
            model="gpt-5-nano",
            messages=conversation_history[chat_id]
        )

        answer = response.choices[0].message.content

        # Save assistant reply in memory
        conversation_history[chat_id].append(
            {
                "role": "assistant",
                "content": answer
            }
        )

        # Log assistant reply
        write_log({
            "timestamp": datetime.utcnow().isoformat(),
            "chat_id": chat_id,
            "event": "assistant_reply",
            "reply": answer
        })

        await update.message.reply_text(answer)

    except Exception as e:

        write_log({
            "timestamp": datetime.utcnow().isoformat(),
            "chat_id": chat_id,
            "event": "error",
            "error": str(e)
        })

        await update.message.reply_text(f"Error: {e}")


# -------------------------
# Telegram App
# -------------------------
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

print("Bot is running...")

app.run_polling()