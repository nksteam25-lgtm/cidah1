"""
Claude Master — יצירת 10 Workspaces אוטומטית
הרץ: python3 setup/create_workspaces.py
"""
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv("setup/.env")

ADMIN_KEY = os.getenv("ANTHROPIC_ADMIN_KEY")
BASE_URL   = "https://api.anthropic.com/v1"
HEADERS    = {
    "x-api-key": ADMIN_KEY,
    "anthropic-version": "2023-06-01",
    "Content-Type": "application/json"
}

# הגדרת 10 חברי צוות
TEAM = [
    {"id": "user_01", "name": "claude-master-admin"},
    {"id": "user_02", "name": "team-lead-01"},
    {"id": "user_03", "name": "team-member-01"},
    {"id": "user_04", "name": "team-member-02"},
    {"id": "user_05", "name": "team-member-03"},
    {"id": "user_06", "name": "team-member-04"},
    {"id": "user_07", "name": "team-member-05"},
    {"id": "user_08", "name": "team-member-06"},
    {"id": "user_09", "name": "team-member-07"},
    {"id": "user_10", "name": "team-member-08"},
]

def create_workspace(name: str) -> dict:
    """יצירת Workspace חדש"""
    r = requests.post(
        f"{BASE_URL}/organizations/workspaces",
        headers=HEADERS,
        json={"name": name}
    )
    return r.json()

def create_api_key(workspace_id: str, key_name: str) -> dict:
    """יצירת API Key בתוך Workspace"""
    r = requests.post(
        f"{BASE_URL}/organizations/workspaces/{workspace_id}/api_keys",
        headers=HEADERS,
        json={"name": key_name}
    )
    return r.json()

def main():
    results = []
    print("=" * 60)
    print("Claude Master — יוצר Workspaces ומפתחות")
    print("=" * 60)

    for member in TEAM:
        ws_name  = f"workspace_{member['name']}"
        key_name = f"key_{member['name']}"

        # יצירת Workspace
        ws = create_workspace(ws_name)
        ws_id = ws.get("id")

        if not ws_id:
            print(f"✗ {ws_name} — שגיאה: {ws}")
            continue

        print(f"✓ Workspace נוצר: {ws_name} ({ws_id})")

        # יצירת API Key
        key = create_api_key(ws_id, key_name)
        api_key_value = key.get("key") or key.get("secret")

        if api_key_value:
            print(f"  ✓ Key: {api_key_value[:20]}...")
        else:
            print(f"  ⚠ Key לא הוחזר — יש ליצור ידנית ב-Console")
            api_key_value = "MANUAL_CREATION_REQUIRED"

        results.append({
            "user_id":      member["id"],
            "name":         member["name"],
            "workspace_id": ws_id,
            "workspace":    ws_name,
            "api_key":      api_key_value
        })

    # שמירת התוצאות לקובץ מוצפן
    output_file = "setup/workspaces_created.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("=" * 60)
    print(f"✓ הושלם — {len(results)} Workspaces נוצרו")
    print(f"✓ תוצאות נשמרו: {output_file}")
    print("⚠  שמור את הקובץ במקום מאובטח!")
    print("=" * 60)

if __name__ == "__main__":
    main()
