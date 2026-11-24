"""
Adya — ek sweet si Telegram bot 🤖💖
BTech 1st year wali friendly bot jo chat padh kar human jaise jawab deti hai,
aur uski pyaari si voice bhi hai 🎤

Setup ke liye README.md padho.
"""

import asyncio
import logging
import os
import random
import re
import tempfile

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from persona import PERSONA

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("httpcore").setLevel(logging.CRITICAL)
log = logging.getLogger("adya")

# ---------------- Settings (.env se aate hain) ----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

VOICE_ENABLED = os.getenv("VOICE_ENABLED", "false").lower() in ("1", "true", "yes")
VOICE_NAME = os.getenv("VOICE_NAME", "hi-IN-SwaraNeural")  # sweet female Indian voice
VOICE_MODE = os.getenv("VOICE_MODE", "both").lower()       # both | voice | text

# Hosting ke liye (Render apna URL khud deta hai RENDER_EXTERNAL_URL me)
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
PORT = int(os.getenv("PORT", "10000"))

MAX_HISTORY = 20  # kitni purani chat yaad rakhe

# ---------------- Gemini setup ----------------
genai_client = None
genai_types = None
if GEMINI_API_KEY:
    from google import genai
    from google.genai import types as genai_types

    genai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    log.warning("GEMINI_API_KEY nahi mili! .env file check karo.")

# chat_id -> conversation history (user ki chat padh kar yaad rakhti hai)
histories: dict[int, list] = {}


def get_history(chat_id: int) -> list:
    return histories.setdefault(chat_id, [])


async def ask_gemini(chat_id: int, user_text: str) -> str:
    """User ka message history me daal kar Gemini se jawab mangta hai."""
    history = get_history(chat_id)
    pending = {"role": "user", "text": user_text}

    contents = [
        genai_types.Content(
            role=m["role"], parts=[genai_types.Part(text=m["text"])]
        )
        for m in [*history[-(MAX_HISTORY // 2 * 2):], pending]
    ]

    def _call():
        resp = genai_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=PERSONA,
            ),
        )
        return (resp.text or "").strip()

    reply = await asyncio.to_thread(_call)
    if not reply:
        reply = "Sorry, abhi samajh nahi aaya 😅 thoda phir se bolo na?"
    history.extend([pending, {"role": "model", "text": reply}])
    del history[:-MAX_HISTORY]
    return reply


# ---------------- Voice (edge-tts) ----------------
def clean_for_voice(text: str) -> str:
    """Voice ke liye text saaf karo (emoji/markdown hatao)."""
    text = re.sub(r"[*_`#>\[\]()]", " ", text)
    text = re.sub(r"[^\w\s\.,!?;:'\"\-()]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:600]


async def make_voice(text: str) -> str | None:
    """Text ko sweet voice mp3 me badalta hai. File path ya None."""
    import edge_tts

    clean = clean_for_voice(text)
    if not clean:
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        await edge_tts.Communicate(clean, VOICE_NAME).save(tmp.name)
        return tmp.name
    except Exception as e:
        log.error(f"Voice banate time error: {e}")
        return None


def split_reply(text: str) -> list[str]:
    """Lambe jawab ko kabhi-kabhi 2 natural hisso me baant do (human jaisa)."""
    if len(text) < 220 or "\n" not in text:
        return [text]
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 2:
        return [text]
    mid = len(lines) // 2
    return ["\n".join(lines[:mid]), "\n".join(lines[mid:])]


# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name if user else "dost"
    await update.message.reply_text(
        f"Hii {name}! 😊 Main Adya hoon, BTech 1st year me padhti hoon. "
        "Aapse baat karke bahut achha lagega! Kuch bhi pucho, main yahin hoon 💖\n\n"
        "Commands:\n"
        "/reset — chat history saaf karo\n"
        "/voice — voice on/off karo"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bas mujhe message bhejo, main jawab dungi 😊\n"
        "/reset — purani chat bhool jao\n"
        "/voice — voice message on/off karo"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    histories.pop(update.effective_chat.id, None)
    await update.message.reply_text(
        "Purani chat bhool gayi! Ab fresh start 😊 Kuch naya pucho!"
    )


async def voice_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global VOICE_ENABLED
    VOICE_ENABLED = not VOICE_ENABLED
    await update.message.reply_text(
        "Voice ON kar di 🎤 Ab mere jawab voice me bhi milenge!"
        if VOICE_ENABLED
        else "Voice OFF kar di. Ab sirf text me jawab dungi 😊"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat = update.effective_chat
    user_text = update.message.text.strip()
    if not user_text:
        return

    # Human jaisa feel: typing dikhao + thoda delay
    await context.bot.send_chat_action(chat.id, ChatAction.TYPING)
    await asyncio.sleep(random.uniform(0.6, 1.4))

    try:
        reply = await ask_gemini(chat.id, user_text)
    except Exception as e:
        log.error("Gemini error: %s (code=%s, status=%s)", type(e).__name__, getattr(e, "code", None), getattr(e, "status", None))
        if str(getattr(e, "code", "")) == "400":
            detail = str(getattr(e, "message", "") or e).lower()
            checks = {
                "api_key": ("api key", "api_key_invalid"),
                "location": ("location", "region", "country"),
                "system_instruction": ("system instruction", "system_instruction", "systeminstruction", "developer instruction"),
                "model_or_api_version": ("model", "api version", "generatecontent"),
                "contents_or_roles": ("contents", "role", "parts"),
                "generation_config": ("generationconfig", "generation_config", "thinking", "temperature", "max_output_tokens"),
                "billing": ("billing", "paid tier"),
            }
            hints = [label for label, words in checks.items() if any(word in detail for word in words)]
            log.error("Gemini diagnostic: model_is_expected=%s; hints=%s", GEMINI_MODEL == "gemini-3.1-flash-lite", ",".join(hints) or "unknown")
        reply = "Oops! Thodi der baad try karo na 😅"

    # Jawab bhejo (text + voice, setting ke hisaab se)
    if VOICE_MODE in ("both", "text"):
        for part in split_reply(reply):
            await context.bot.send_chat_action(chat.id, ChatAction.TYPING)
            await asyncio.sleep(random.uniform(0.4, 0.9))
            await update.message.reply_text(part)

    if VOICE_ENABLED and VOICE_MODE in ("both", "voice"):
        await context.bot.send_chat_action(chat.id, ChatAction.RECORD_VOICE)
        voice_path = await make_voice(reply)
        if voice_path:
            try:
                with open(voice_path, "rb") as f:
                    await context.bot.send_voice(chat.id, voice=f)
            finally:
                os.unlink(voice_path)


def main():
    if not TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN nahi mila! .env file me token daalo.")
    if not genai_client:
        raise SystemExit("GEMINI_API_KEY nahi mili! .env file me API key daalo.")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("voice", voice_toggle))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Adya online hai! 💖")
    if WEBHOOK_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_TOKEN,
            webhook_url=f"{WEBHOOK_URL.rstrip('/')}/{TELEGRAM_TOKEN}",
        )
    else:
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
