"""One-time script to generate a Gmail OAuth refresh token.

Usage:
    python generate_token.py

Requires `credentials.json` (downloaded from Google Cloud Console) to be
present in the same directory as this script.
"""

from pathlib import Path
import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"


def main() -> None:
    if not CREDENTIALS_FILE.exists():
        print(f"[ERROR] '{CREDENTIALS_FILE}' not found.")
        return

    print("Starting authentication flow...")
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    # Create a private local file, refusing to overwrite an existing token.
    target = CREDENTIALS_FILE.with_name("token.json")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(creds.to_json())
    print("Authentication succeeded. Credentials saved to ignored token.json (owner-only permissions).")
    print("Transfer the refresh_token securely into your environment settings; do not paste it in chat.")


if __name__ == "__main__":
    main()
