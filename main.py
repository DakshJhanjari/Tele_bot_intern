import logging
import traceback
import requests

from dotenv import load_dotenv

# load_dotenv MUST run before any module that reads env vars at import time
load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402

from ai_agent import generate_email_draft  # noqa: E402
from gmail_integration import create_draft  # noqa: E402
from telegram_integration import send_message, download_file  # noqa: E402
from a2a_protocol import AGENT_CARD  # noqa: E402
from a2a_router import router as a2a_router  # noqa: E402

# ---------------------------------------------------------------------------
# Logging — structured timestamps and log levels visible in Cloud Run logs
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()

# Mount the A2A protocol router
app.include_router(a2a_router)


@app.on_event("startup")
async def on_startup():
    """Run startup tasks: register Telegram webhook and populate A2A agent card URL."""
    import os

    # --- Populate the A2A agent card URL ---
    base_url = (
        os.environ.get("RENDER_EXTERNAL_URL")
        or os.environ.get("BASE_URL")
        or ""
    )
    AGENT_CARD["url"] = base_url.rstrip("/")
    if base_url:
        logger.info("A2A agent card URL set to: %s", AGENT_CARD["url"])
    else:
        logger.info("BASE_URL / RENDER_EXTERNAL_URL not set — A2A agent card URL is empty.")

    # --- Register Telegram webhook ---
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    render_url = os.environ.get("RENDER_EXTERNAL_URL")  # Injected automatically by Render

    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — skipping webhook registration.")
        return
    if not render_url:
        logger.info("RENDER_EXTERNAL_URL not set — skipping webhook registration (local dev mode).")
        return

    webhook_url = f"{render_url}/webhook"
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={"url": webhook_url},
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            logger.info("Telegram webhook registered: %s", webhook_url)
        else:
            logger.error("Failed to set webhook: %s", data)
    except Exception:
        logger.exception("Exception while registering Telegram webhook")


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
