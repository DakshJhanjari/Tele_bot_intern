import logging
import time
import traceback
import uuid
import requests

from dotenv import load_dotenv

# load_dotenv MUST run before any module that reads env vars at import time
load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402

from ai_agent import generate_email_draft  # noqa: E402
from gmail_integration import create_draft, send_email  # noqa: E402
from telegram_integration import (  # noqa: E402
    send_message,
    edit_message_text,
    answer_callback_query,
    download_file,
)
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

# ---------------------------------------------------------------------------
# In-memory storage for pending drafts awaiting user confirmation
# Maps draft_id -> { "subject", "body", "recruiter_email", "job_text", "created_at" }
# ---------------------------------------------------------------------------
_PENDING_DRAFTS: dict[str, dict] = {}


def _cleanup_old_drafts():
    """Remove drafts older than 2 hours to keep memory compact."""
    now = time.time()
    if len(_PENDING_DRAFTS) > 100:
        expired = [
            k for k, v in _PENDING_DRAFTS.items()
            if now - v.get("created_at", 0) > 7200
        ]
        for k in expired:
            _PENDING_DRAFTS.pop(k, None)


def _build_preview_markup(draft_id: str) -> dict:
    """Build the inline keyboard with Send, Draft, Regenerate, and Discard buttons."""
    return {
        "inline_keyboard": [
            [
                {"text": "📧 Send Email", "callback_data": f"send:{draft_id}"},
                {"text": "💾 Save as Draft", "callback_data": f"draft:{draft_id}"},
            ],
            [
                {"text": "🔄 Regenerate", "callback_data": f"regen:{draft_id}"},
                {"text": "❌ Discard", "callback_data": f"discard:{draft_id}"},
            ],
        ]
    }


def _format_preview_text(recruiter_email: str, subject: str, body: str) -> str:
    """Format the draft preview message for Telegram."""
    to_display = recruiter_email or "_Not detected (save as draft to add recipient)_"
    return (
        f"📬 *Cold Email Draft Preview*\n\n"
        f"👤 *To:* {to_display}\n"
        f"📌 *Subject:* {subject}\n\n"
        f"📝 *Body:*\n{body}\n\n"
        f"────────────────────────\n"
        f"Choose an action below:"
    )


async def handle_callback_query(callback_query: dict):
    """Handle interactive button clicks from the preview inline keyboard."""
    query_id = callback_query.get("id")
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")

    if not query_id or not chat_id or not message_id:
        return {"status": "ignored"}

    action, _, draft_id = data.partition(":")
    draft = _PENDING_DRAFTS.get(draft_id)

    if not draft and action in ("send", "draft", "regen"):
        answer_callback_query(
            query_id,
            text="⚠️ This draft has expired or was already processed. Please submit the job again.",
            show_alert=True,
        )
        return {"status": "expired"}

    try:
        if action == "send":
            recruiter_email = draft.get("recruiter_email")
            if not recruiter_email:
                answer_callback_query(
                    query_id,
                    text="⚠️ No recruiter email found in the job post! Use 'Save as Draft' to add the recipient in Gmail.",
                    show_alert=True,
                )
                return {"status": "no_recipient"}

            answer_callback_query(query_id, text="🚀 Sending email via Gmail...")
            send_email(
                subject=draft["subject"],
                body=draft["body"],
                to_email=recruiter_email,
            )
            _PENDING_DRAFTS.pop(draft_id, None)

            sent_msg = (
                f"✅ *Email Sent Successfully!*\n\n"
                f"👤 *To:* {recruiter_email}\n"
                f"📌 *Subject:* {draft['subject']}\n\n"
                f"The email has been sent directly from your Gmail account."
            )
            edit_message_text(chat_id, message_id, sent_msg, reply_markup=None)
            return {"status": "ok"}

        elif action == "draft":
            answer_callback_query(query_id, text="💾 Saving to Gmail Drafts...")
            create_draft(
                subject=draft["subject"],
                body=draft["body"],
                to_email=draft.get("recruiter_email", ""),
            )
            _PENDING_DRAFTS.pop(draft_id, None)

            to_display = draft.get("recruiter_email") or "[Blank]"
            saved_msg = (
                f"✅ *Saved to Gmail Drafts!*\n\n"
                f"👤 *To:* {to_display}\n"
                f"📌 *Subject:* {draft['subject']}\n\n"
                f"Check your Gmail Drafts folder to review and send."
            )
            edit_message_text(chat_id, message_id, saved_msg, reply_markup=None)
            return {"status": "ok"}

        elif action == "regen":
            answer_callback_query(query_id, text="🔄 Regenerating draft with Gemini...")
            job_text = draft.get("job_text", "")
            new_draft = generate_email_draft(job_description_text=job_text)

            # Update cache with new generated draft
            _PENDING_DRAFTS[draft_id]["subject"] = new_draft.subject
            _PENDING_DRAFTS[draft_id]["body"] = new_draft.body
            _PENDING_DRAFTS[draft_id]["recruiter_email"] = new_draft.recruiter_email

            new_preview = _format_preview_text(
                new_draft.recruiter_email, new_draft.subject, new_draft.body
            )
            edit_message_text(
                chat_id,
                message_id,
                new_preview,
                reply_markup=_build_preview_markup(draft_id),
            )
            return {"status": "ok"}

        elif action == "discard":
            answer_callback_query(query_id, text="Draft discarded.")
            _PENDING_DRAFTS.pop(draft_id, None)
            edit_message_text(chat_id, message_id, "❌ *Draft discarded.*", reply_markup=None)
            return {"status": "ok"}

        else:
            answer_callback_query(query_id, text="Unknown action.")
            return {"status": "unknown_action"}

    except Exception as exc:
        logger.exception("Error handling callback query action=%s: %s", action, exc)
        answer_callback_query(query_id, text=f"❌ Error: {exc}", show_alert=True)
        return {"status": "error", "reason": str(exc)}


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
    """Handle incoming webhook updates from Telegram (messages and callback queries)."""
    update = await request.json()

    # 1. Handle Inline Button Clicks
    if "callback_query" in update:
        return await handle_callback_query(update["callback_query"])

    # 2. Handle Messages
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return {"status": "ignored", "reason": "No chat id"}

    text = message.get("text", "")
    caption = message.get("caption", "")
    photos = message.get("photo", [])

    # Prefer explicit text; fall back to photo caption
    job_text = (text or caption).strip()

    # Handle /start or /help commands
    if job_text in ("/start", "/help"):
        welcome_msg = (
            "👋 *Welcome to Cold Email Drafter Bot!*\n\n"
            "Send me any *Job Description* (as text or screenshot), and I will:\n"
            "1. Match it with your resume\n"
            "2. Draft a personalized, persuasive cold email\n"
            "3. Show you a *Preview* with interactive buttons:\n"
            "   • 📧 *Send Email* directly to the recruiter\n"
            "   • 💾 *Save as Draft* to your Gmail\n"
            "   • 🔄 *Regenerate* for a fresh draft variation\n"
            "   • ❌ *Discard* the draft\n\n"
            "Ready when you are! Send a job post to get started."
        )
        send_message(chat_id, welcome_msg)
        return {"status": "ok"}

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

        # 2. Store in pending drafts for button interactions
        _cleanup_old_drafts()
        draft_id = uuid.uuid4().hex[:8]
        _PENDING_DRAFTS[draft_id] = {
            "subject": draft_response.subject,
            "body": draft_response.body,
            "recruiter_email": draft_response.recruiter_email,
            "job_text": job_text,
            "created_at": time.time(),
        }

        # 3. Present preview with interactive action buttons
        preview_text = _format_preview_text(
            draft_response.recruiter_email,
            draft_response.subject,
            draft_response.body,
        )
        markup = _build_preview_markup(draft_id)
        send_message(chat_id, preview_text, reply_markup=markup)

        return {"status": "ok"}

    except Exception as e:
        logger.error("Error processing request:\n%s", traceback.format_exc())
        error_msg = f"❌ **Error processing request:**\n`{e}`"
        try:
            send_message(chat_id, error_msg)
        except Exception as notify_err:
            logger.warning("Failed to send error notification to user: %s", notify_err)
        return {"status": "error", "reason": str(e)}


@app.get("/")
def health_check():
    """Simple health-check endpoint."""
    return {"status": "healthy", "bot": "Vibe Coding Cold Emailer"}
