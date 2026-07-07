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

def send_message(chat_id: int, text: str) -> dict:
    """Send a text message to *chat_id* via the Telegram Bot API.

    Args:
        chat_id: Target chat identifier.
        text: Message text (supports Telegram Markdown).

    Returns:
        Parsed JSON response from the Telegram API.
    """
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    response = requests.post(_api_url("sendMessage"), json=payload, timeout=10)
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
