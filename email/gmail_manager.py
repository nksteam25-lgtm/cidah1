"""
Claude Master — Gmail Manager
חיבור ל-guyn@cidah.ai דרך Gmail API + Google Drive API
Anthropic SDK נייטיב | Google API נייטיב
"""
import os
import json
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ── הגדרות ───────────────────────────────────────────────────────────────────
CREDENTIALS_FILE = Path("credentials/gmail_credentials.json")
TOKEN_FILE        = Path("credentials/gmail_token.pickle")
SAVE_FOLDER       = Path("neeman_native_docs")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.file",
]

LABEL_NAME = "neeman_native_docs"


# ── אימות OAuth ──────────────────────────────────────────────────────────────
def get_credentials() -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return creds


# ── בניית שירותים ─────────────────────────────────────────────────────────────
def get_services():
    creds   = get_credentials()
    gmail   = build("gmail", "v1", credentials=creds)
    drive   = build("drive", "v3", credentials=creds)
    return gmail, drive


# ── יצירת Label ב-Gmail ───────────────────────────────────────────────────────
def create_label(gmail, name: str) -> str:
    """יוצר label ב-Gmail אם לא קיים, מחזיר את ה-ID"""
    labels = gmail.users().labels().list(userId="me").execute()
    for label in labels.get("labels", []):
        if label["name"] == name:
            print(f"✓ Label קיים: {name} ({label['id']})")
            return label["id"]

    result = gmail.users().labels().create(
        userId="me",
        body={
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
    ).execute()
    print(f"✓ Label נוצר: {name} ({result['id']})")
    return result["id"]


# ── קריאת מיילים עם Label ────────────────────────────────────────────────────
def list_labeled_messages(gmail, label_id: str, max_results: int = 10) -> list:
    result = gmail.users().messages().list(
        userId="me",
        labelIds=[label_id],
        maxResults=max_results
    ).execute()
    return result.get("messages", [])


# ── שמירת קובץ ל-Drive ────────────────────────────────────────────────────────
def save_to_drive(drive, filename: str, content: str, mimetype: str = "text/plain") -> str:
    """שומר קובץ ב-Drive ומחזיר file ID"""
    from googleapiclient.http import MediaInMemoryUpload
    media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mimetype)
    file_metadata = {"name": filename}
    result = drive.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()
    print(f"✓ נשמר ב-Drive: {filename} ({result['id']})")
    return result["id"]


# ── שמירה מקומית ל-neeman_native_docs ────────────────────────────────────────
def save_locally(filename: str, content: str) -> None:
    SAVE_FOLDER.mkdir(exist_ok=True)
    path = SAVE_FOLDER / filename
    path.write_text(content, encoding="utf-8")
    print(f"✓ נשמר מקומית: {path}")


# ── ראשי ──────────────────────────────────────────────────────────────────────
def main():
    print("Claude Master — Gmail Manager")
    print("מתחבר ל-guyn@cidah.ai...\n")

    gmail, drive = get_services()

    # יצירת label
    label_id = create_label(gmail, LABEL_NAME)

    # הדפסת מיילים עם הlabel
    messages = list_labeled_messages(gmail, label_id)
    print(f"\nמיילים ב-{LABEL_NAME}: {len(messages)}")

    print("\n✓ חיבור Gmail + Drive פעיל")
    return gmail, drive, label_id


if __name__ == "__main__":
    main()
