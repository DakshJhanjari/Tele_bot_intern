import base64
import logging
import os
from email.message import EmailMessage

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level credential / service cache
# ---------------------------------------------------------------------------

_credentials: Credentials | None = None


def _get_credentials() -> Credentials:
    """Build (and cache) OAuth credentials from environment variables."""
    global _credentials
    if _credentials is None:
        client_id = os.environ.get("GMAIL_CLIENT_ID")
        client_secret = os.environ.get("GMAIL_CLIENT_SECRET")
        refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN")

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError("Missing Gmail OAuth environment variables.")

        _credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
        )
    return _credentials


def get_gmail_service():
    """Return a Gmail API service using cached OAuth credentials."""
    return build("gmail", "v1", credentials=_get_credentials())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_draft(subject: str, body: str, to_email: str = "") -> dict:
    """Create a draft email in the authenticated user's Gmail account.

    Args:
        subject: Email subject line.
        body: Plain-text email body.
        to_email: Optional recipient address. Omitted from headers if blank.

    Returns:
        The Gmail API draft resource dict (contains the draft ``id``).
    """
    service = get_gmail_service()

    message = EmailMessage()
    message.set_content(body)
    message["Subject"] = subject
    if to_email:
        message["To"] = to_email

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_body = {"message": {"raw": encoded_message}}

    draft = service.users().drafts().create(userId="me", body=create_body).execute()
    logger.info("Draft created successfully (id=%s).", draft["id"])
    return draft
