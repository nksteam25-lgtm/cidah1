"""
Claude Master — יצירת Labels + Filters ב-Gmail
מריצים פעם אחת בלבד
"""
import pickle
from pathlib import Path
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

CREDENTIALS_FILE = Path("credentials/gmail_credentials.json")
TOKEN_FILE        = Path("credentials/gmail_token.pickle")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.modify",
]

# ── שידוך משתמשים ─────────────────────────────────────────────────────────────
USERS = [
    {"name": "Guy Neeman",            "role": "super_admin",    "alias": None},
    {"name": "Lilach Keynan",         "role": "manager_ops",    "alias": "guyn+ops@cidah.ai"},
    {"name": "Barak Orbach",          "role": "manager_full",   "alias": "guyn+legal1@cidah.ai"},
    {"name": "Roy Boker",             "role": "manager_full",   "alias": "guyn+legal2@cidah.ai"},
    {"name": "Adi Yehezkiel-Yaffe",   "role": "team_lawyer",    "alias": "guyn+legal3@cidah.ai"},
    {"name": "Dana Hasson",           "role": "team_lawyer",    "alias": "guyn+legal4@cidah.ai"},
    {"name": "Hila Cohen",            "role": "team_lawyer",    "alias": "guyn+legal5@cidah.ai"},
    {"name": "Philippe Lipschutz",    "role": "team_lawyer",    "alias": "guyn+legal6@cidah.ai"},
    {"name": "Tamar Maoz Knaz",       "role": "team_lawyer",    "alias": "guyn+legal7@cidah.ai"},
    {"name": "Mona Mantel",           "role": "team_paralegal", "alias": "guyn+para1@cidah.ai"},
    {"name": "Yafit Mor",             "role": "team_paralegal", "alias": "guyn+para2@cidah.ai"},
    {"name": "Agent Comms",           "role": "agent_system",   "alias": "guyn+agent@cidah.ai"},
]

# ── צבעים לפי תפקיד ──────────────────────────────────────────────────────────
ROLE_COLORS = {
    "super_admin":    {"backgroundColor": "#000000", "textColor": "#ffffff"},
    "manager_ops":    {"backgroundColor": "#1c4587", "textColor": "#ffffff"},
    "manager_full":   {"backgroundColor": "#1a764d", "textColor": "#ffffff"},
    "team_lawyer":    {"backgroundColor": "#41236d", "textColor": "#ffffff"},
    "team_paralegal": {"backgroundColor": "#7a4706", "textColor": "#ffffff"},
    "agent_system":   {"backgroundColor": "#ff6d00", "textColor": "#000000"},
}


def get_credentials():
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return creds


def get_existing_labels(gmail) -> dict:
    result = gmail.users().labels().list(userId="me").execute()
    return {l["name"]: l["id"] for l in result.get("labels", [])}


def create_label(gmail, name: str, role: str) -> str:
    color = ROLE_COLORS.get(role, {})
    body = {
        "name": f"neeman/{name}",
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }
    if color:
        body["color"] = color
    result = gmail.users().labels().create(userId="me", body=body).execute()
    return result["id"]


def create_filter(gmail, alias: str, label_id: str) -> None:
    try:
        gmail.users().settings().filters().create(
            userId="me",
            body={
                "criteria": {"to": alias},
                "action": {
                    "addLabelIds": [label_id],
                    "removeLabelIds": [],
                },
            }
        ).execute()
    except Exception as e:
        if "already exists" in str(e):
            print(f"  → Filter קיים כבר: {alias}")
        else:
            raise


def main():
    print("Claude Master — מגדיר Labels + Filters\n")
    creds  = get_credentials()
    gmail  = build("gmail", "v1", credentials=creds)

    existing = get_existing_labels(gmail)

    for user in USERS:
        if not user["alias"]:
            print(f"⏭  {user['name']} (master — ללא filter)")
            continue

        label_key = f"neeman/{user['name']}"

        # Label
        if label_key in existing:
            label_id = existing[label_key]
            print(f"✓ Label קיים: {label_key}")
        else:
            label_id = create_label(gmail, user["name"], user["role"])
            print(f"✓ Label נוצר: {label_key}")

        # Filter
        create_filter(gmail, user["alias"], label_id)
        print(f"  → Filter: {user['alias']} → {label_key}\n")

    print("✅ הכל מוגדר — 10 labels + 10 filters פעילים")


if __name__ == "__main__":
    main()
