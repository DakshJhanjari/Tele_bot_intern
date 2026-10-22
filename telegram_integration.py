import logging
import os

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token — read once at import time so misconfiguration fails fast at startup
# ---------------------------------------------------------------------------

_BOT_TOKEN: str = ""


def _get_token() -> str:
    """Return the bot token, reading from env on first call."""
    global _BOT_TOKEN
    if not _BOT_TOKEN:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set.")
        _BOT_TOKEN = token
    return _BOT_TOKEN


def _api_url(method: str) -> str:
    """Return the full Telegram Bot API URL for *method*."""
    return f"https://api.telegram.org/bot{_get_token()}/{method}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_message(
    chat_id: int,
    text: str,
    parse_mode: str | None = "Markdown",
    reply_markup: dict | None = None,
) -> dict:
    """Send a text message to *chat_id* via the Telegram Bot API.

    Args:
        chat_id: Target chat identifier.
        text: Message text.
        parse_mode: Parsing mode ('Markdown', 'HTML', or None).
        reply_markup: Optional inline keyboard or reply markup dictionary.

    Returns:
        Parsed JSON response from the Telegram API.
    """
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    response = requests.post(_api_url("sendMessage"), json=payload, timeout=10)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        # If Markdown parsing fails due to unescaped characters in AI draft, retry as plain text
        if parse_mode and response.status_code == 400 and "can't parse entities" in response.text:
            logger.warning("Telegram parse error, retrying without parse_mode: %s", response.text)
            payload.pop("parse_mode", None)
            retry_res = requests.post(_api_url("sendMessage"), json=payload, timeout=10)
            retry_res.raise_for_status()
            return retry_res.json()
        raise exc

    return response.json()


def edit_message_text(
    chat_id: int,
    message_id: int,
    text: str,
    parse_mode: str | None = "Markdown",
    reply_markup: dict | None = None,
) -> dict:
    """Edit an existing message text in *chat_id*.

    Args:
        chat_id: Target chat identifier.
        message_id: Identifier of the message to edit.
        text: New message text.
        parse_mode: Parsing mode ('Markdown', 'HTML', or None).
        reply_markup: Optional new inline keyboard, or empty dict/None to remove.

    Returns:
        Parsed JSON response from the Telegram API.
    """
    payload: dict = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    response = requests.post(_api_url("editMessageText"), json=payload, timeout=10)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        if parse_mode and response.status_code == 400 and "can't parse entities" in response.text:
            logger.warning("Telegram edit parse error, retrying without parse_mode: %s", response.text)
            payload.pop("parse_mode", None)
            retry_res = requests.post(_api_url("editMessageText"), json=payload, timeout=10)
            retry_res.raise_for_status()
            return retry_res.json()
        raise exc

    return response.json()


def answer_callback_query(
    callback_query_id: str,
    text: str | None = None,
    show_alert: bool = False,
) -> dict:
    """Acknowledge a callback query from an inline keyboard button.

    Args:
        callback_query_id: Unique identifier for the query to be answered.
        text: Text of the notification displayed to the user.
        show_alert: If true, an alert will be shown by the client instead of a notification.

    Returns:
        Parsed JSON response from the Telegram API.
    """
    payload: dict = {
        "callback_query_id": callback_query_id,
        "show_alert": show_alert,
    }
    if text:
        payload["text"] = text

    response = requests.post(_api_url("answerCallbackQuery"), json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def download_file(file_id: str) -> bytes:
    """Download a file from Telegram given its *file_id*.

    Args:
        file_id: Telegram file identifier (from an incoming ``photo`` or
            ``document`` message).

    Returns:
        Raw file bytes.
    """
    # Step 1 — resolve file_id → file_path
    res = requests.get(_api_url("getFile"), params={"file_id": file_id}, timeout=10)
    res.raise_for_status()
    file_path = res.json()["result"]["file_path"]

    # Step 2 — download the actual bytes
    download_url = f"https://api.telegram.org/file/bot{_get_token()}/{file_path}"
    file_res = requests.get(download_url, timeout=30)
    file_res.raise_for_status()

    return file_res.content
