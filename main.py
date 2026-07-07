import logging
import traceback

from dotenv import load_dotenv

# load_dotenv MUST run before any module that reads env vars at import time
load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402

from ai_agent import generate_email_draft  # noqa: E402
from gmail_integration import create_draft  # noqa: E402
from telegram_integration import send_message, download_file  # noqa: E402

# ---------------------------------------------------------------------------
# Logging — structured timestamps and log levels visible in Cloud Run logs
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming webhook updates from Telegram."""
    update = await request.json()

    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return {"status": "ignored", "reason": "No chat id"}

    text = message.get("text", "")
    caption = message.get("caption", "")
    photos = message.get("photo", [])

    # Prefer explicit text; fall back to photo caption
    job_text = text or caption

    send_message(chat_id, "⚙️ Processing your job description. Drafting email now...")

    image_bytes = None
    try:
        if photos:
            # Telegram provides photo sizes in ascending order — take the largest
            file_id = photos[-1]["file_id"]
            image_bytes = download_file(file_id)

        if not job_text and not image_bytes:
            send_message(chat_id, "Please send a job description text or a screenshot.")
            return {"status": "error", "reason": "No content"}

        # 1. Generate the draft via Gemini
        draft_response = generate_email_draft(job_text, image_bytes)

        # 2. Save it to Gmail Drafts
        create_draft(
            subject=draft_response.subject,
            body=draft_response.body,
            to_email=draft_response.recruiter_email,
        )

        # 3. Notify the user
        to_display = draft_response.recruiter_email or "[Blank]"
        success_msg = (
            f"✅ **Draft Created successfully!**\n\n"
            f"**To:** {to_display}\n"
            f"**Subject:** {draft_response.subject}\n\n"
            "Check your Gmail Drafts folder to review and send."
        )
        send_message(chat_id, success_msg)
        return {"status": "ok"}

    except Exception as e:
        logger.error("Error processing request:\n%s", traceback.format_exc())
        error_msg = f"❌ **Error processing request:**\n`{e}`"
        try:
            send_message(chat_id, error_msg)
        except Exception as notify_err:
            # Best-effort notification; log if it fails so we're not flying blind
            logger.warning("Failed to send error notification to user: %s", notify_err)
        return {"status": "error", "reason": str(e)}


@app.get("/")
def health_check():
    """Simple health-check endpoint."""
    return {"status": "healthy", "bot": "Vibe Coding Cold Emailer"}
