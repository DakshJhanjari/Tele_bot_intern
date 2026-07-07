"""One-time script to generate a Gmail OAuth refresh token.

Usage:
    python generate_token.py

Requires `credentials.json` (downloaded from Google Cloud Console) to be
present in the same directory as this script.
"""

from pathlib import Path

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

    print("\n[SUCCESS] Authentication Successful!\n")
    print("=" * 50)
    print("YOUR REFRESH TOKEN IS:")
    print(creds.refresh_token)
    print("=" * 50)


if __name__ == "__main__":
    main()
