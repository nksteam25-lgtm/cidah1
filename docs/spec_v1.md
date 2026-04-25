# מפרט מערכת ניהול Claude Master
### Advanced AI Multi-User Management System
**גרסה:** 1.0  
**תאריך:** אפריל 2026  
**סיווג:** פנימי — צוות ניהול בלבד

---

## תוכן עניינים

1. [סקירה כללית](#1-סקירה-כללית)
2. [ארכיטקטורת המערכת](#2-ארכיטקטורת-המערכת)
3. [חיבור ל-Claude API — הגדרות Claude Master](#3-חיבור-ל-claude-api--הגדרות-claude-master)
4. [ניהול API Keys — הרשאות לכל חבר צוות](#4-ניהול-api-keys--הרשאות-לכל-חבר-צוות)
5. [ניהול אימיילים ב-Google Workspace](#5-ניהול-אימיילים-ב-google-workspace)
6. [לוגים ומעקב שימוש](#6-לוגים-ומעקב-שימוש)
7. [Agents ואוטומציה](#7-agents-ואוטומציה)
8. [אבטחה ובקרת גישה](#8-אבטחה-ובקרת-גישה)
9. [ניהול שכבות מתקדמות](#9-ניהול-שכבות-מתקדמות)
10. [נהלי תפעול ותחזוקה](#10-נהלי-תפעול-ותחזוקה)

---

## 1. סקירה כללית

### 1.1 מטרת המערכת

**Claude Master** הינה מערכת ניהול מרכזית מבוססת בינה מלאכותית המיועדת לנהל עד **10 משתמשים** דרך ממשק Claude API. המערכת מאפשרת שליטה מלאה של מנהל אחד (Claude Master) על כלל החשבונות, ההרשאות, הפעולות האוטומטיות, וניהול הדואר האלקטרוני הארגוני ב-Google Workspace.

### 1.2 עקרונות מפתח

- **ריכוזיות מלאה** — Claude Master שולט בכל הגדרות המשתמשים מנקודה אחת.
- **הפרדת הרשאות** — לכל חבר צוות יש מפתח API נפרד עם מגבלות מותאמות אישית.
- **ניראות מלאה** — כל פעולה נרשמת ומנוטרת בזמן אמת.
- **אוטומציה חכמה** — Agents פועלים ברקע לביצוע משימות חוזרות ומשימות דואר אלקטרוני.
- **אבטחה בשכבות** — ניהול גישה מבוסס תפקידים (RBAC) עם הצפנה מקצה לקצה.

### 1.3 משתמשי המערכת

| תפקיד | כמות | תיאור |
|--------|------|--------|
| Claude Master Admin | 1 | שליטה מלאה — ניהול כל המשתמשים, הגדרות, ולוגים |
| Team Lead | עד 2 | גישה לדוחות צוות, ניהול Agents ב-scope מוגבל |
| Team Member | עד 7 | גישה בסיסית ל-API עם מכסות שימוש |

---

## 2. ארכיטקטורת המערכת

### 2.1 תרשים שכבות

```
┌─────────────────────────────────────────────────────────┐
│                    CLAUDE MASTER ADMIN                   │
│              (שליטה מלאה + לוח בקרה מרכזי)              │
└────────────────────────┬────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
┌────────▼──────┐ ┌──────▼──────┐ ┌─────▼────────┐
│  API Gateway  │ │   Email     │ │   Agents     │
│  Manager      │ │   Manager   │ │   Scheduler  │
│  (מפתחות API)│ │ (Gmail GWS) │ │  (אוטומציה) │
└────────┬──────┘ └──────┬──────┘ └─────┬────────┘
         │               │               │
┌────────▼───────────────▼───────────────▼────────┐
│              LOGGING & MONITORING LAYER          │
│         (לוגים, מעקב שימוש, התראות)              │
└────────────────────────┬────────────────────────┘
                         │
┌────────────────────────▼────────────────────────┐
│              10 TEAM MEMBERS                     │
│  User_01 | User_02 | ... | User_10               │
│  (כל אחד עם API Key נפרד ומגבלות שימוש)         │
└─────────────────────────────────────────────────┘
```

### 2.2 רכיבי הליבה

**א. Claude API Gateway** — ניהול מרכזי של כל הבקשות אל Anthropic API  
**ב. User Management Service** — הגדרת משתמשים, הרשאות ומכסות  
**ג. Email Orchestration Layer** — חיבור ל-Gmail API עבור Google Workspace  
**ד. Agent Runtime** — סביבת הרצה לבוטים וסוכנים אוטומטיים  
**ה. Audit & Logging Service** — רישום ובקרה של כל פעילות במערכת  

---

## 3. חיבור ל-Claude API — הגדרות Claude Master

### 3.1 דרישות מוקדמות

```
- חשבון Anthropic (Tier 3 ומעלה מומלץ לתמיכה ב-10 משתמשים)
- Python 3.10+ / Node.js 18+
- סביבת שרת: Linux Ubuntu 22.04 LTS (מומלץ) או Docker
- הגישה לכלים: anthropic SDK, google-auth, google-api-python-client
```

### 3.2 התקנת ה-SDK

```bash
# Python
pip install anthropic google-auth google-auth-oauthlib google-api-python-client python-dotenv

# Node.js (חלופה)
npm install @anthropic-ai/sdk googleapis dotenv
```

### 3.3 קובץ הגדרות Claude Master (`.env.master`)

```env
# === CLAUDE MASTER CREDENTIALS ===
MASTER_ANTHROPIC_API_KEY=sk-ant-api03-MASTER_KEY_HERE
MASTER_MODEL=claude-opus-4-6
MASTER_MAX_TOKENS=8192
MASTER_TEMPERATURE=0.3

# === MASTER CONTROL FLAGS ===
MASTER_ENABLE_LOGGING=true
MASTER_ENABLE_AGENT_SCHEDULER=true
MASTER_ENABLE_EMAIL_MANAGEMENT=true
MASTER_AUDIT_LEVEL=full  # full | basic | minimal

# === GOOGLE WORKSPACE ===
GWS_SERVICE_ACCOUNT_FILE=./credentials/gws_service_account.json
GWS_ADMIN_EMAIL=admin@your-domain.com
GWS_DOMAIN=your-domain.com
GWS_DELEGATED_EMAIL=claude-master@your-domain.com

# === DATABASE (לוגים ומעקב) ===
DB_HOST=localhost
DB_PORT=5432
DB_NAME=claude_master_db
DB_USER=claude_admin
DB_PASSWORD=SECURE_PASSWORD_HERE

# === SECURITY ===
JWT_SECRET=VERY_LONG_RANDOM_SECRET_HERE
ENCRYPTION_KEY=AES256_KEY_HERE
SESSION_TIMEOUT_HOURS=8
```

### 3.4 אתחול Claude Master — קוד ליבה

```python
# claude_master.py — קובץ ליבה של המערכת
import anthropic
import os
from dotenv import load_dotenv

load_dotenv('.env.master')

class ClaudeMaster:
    """
    Claude Master — מנהל מרכזי של כל המשתמשים ב-Claude API
    """

    def __init__(self):
        self.master_client = anthropic.Anthropic(
            api_key=os.getenv("MASTER_ANTHROPIC_API_KEY")
        )
        self.model = os.getenv("MASTER_MODEL", "claude-opus-4-6")
        self.user_registry = UserRegistry()
        self.email_manager = GWSEmailManager()
        self.agent_scheduler = AgentScheduler()
        self.audit_logger = AuditLogger()

    def get_user_client(self, user_id: str) -> anthropic.Anthropic:
        """מחזיר client ייעודי למשתמש לפי ה-user_id שלו"""
        user = self.user_registry.get_user(user_id)
        if not user or not user.is_active:
            raise PermissionError(f"User {user_id} is not active or does not exist.")
        
        self.audit_logger.log(
            action="api_access",
            user_id=user_id,
            model=user.allowed_model
        )
        
        return anthropic.Anthropic(api_key=user.api_key)

    def master_query(self, prompt: str, context: dict = None) -> str:
        """שאילתת Master — עם הרשאות מלאות"""
        response = self.master_client.messages.create(
            model=self.model,
            max_tokens=8192,
            system="You are Claude Master, an advanced AI management system...",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
```

### 3.5 System Prompt מומלץ ל-Claude Master

```
You are Claude Master, the central AI management system for a team of 10 users.
Your responsibilities include:
1. Managing user permissions and API access for all team members
2. Overseeing all email communications through Google Workspace
3. Scheduling and running automated agents
4. Monitoring system usage and generating reports
5. Enforcing security policies and access controls

You operate with full administrative privileges. Always log your actions.
Respond in the user's preferred language (Hebrew/English).
Never expose API keys, passwords, or sensitive credentials in responses.
When acting as Master, prefix critical system actions with [MASTER ACTION].
```

---

## 4. ניהול API Keys — הרשאות לכל חבר צוות

### 4.1 מודל ניהול מפתחות

כל אחד מ-10 חברי הצוות מקבל **API Key נפרד** שנוצר ב-Anthropic Console ומנוהל דרך Claude Master. המפתחות מאוחסנים מוצפנים ב-database מרכזי.

### 4.2 הגדרת משתמש — מבנה נתונים

```python
# models/user.py
from dataclasses import dataclass
from enum import Enum

class UserRole(Enum):
    MASTER_ADMIN = "master_admin"
    TEAM_LEAD    = "team_lead"
    TEAM_MEMBER  = "team_member"

class AllowedModel(Enum):
    OPUS   = "claude-opus-4-6"
    SONNET = "claude-sonnet-4-6"
    HAIKU  = "claude-haiku-4-5-20251001"

@dataclass
class TeamUser:
    user_id: str              # מזהה ייחודי, לדוג׳ "user_01"
    name: str                 # שם מלא
    email: str                # אימייל ב-Google Workspace
    role: UserRole            # תפקיד במערכת
    api_key: str              # מפתח API מוצפן (AES-256)
    allowed_model: str        # מודל מותר לשימוש
    monthly_token_limit: int  # מכסה חודשית ב-tokens
    tokens_used_this_month: int
    is_active: bool
    can_use_agents: bool      # האם מורשה להפעיל Agents
    can_access_email: bool    # האם מורשה לקרוא/לכתוב מיילים
    created_at: str
    last_active: str
```

### 4.3 טבלת הגדרות מומלצת לכל תפקיד

| הגדרה | Master Admin | Team Lead | Team Member |
|-------|-------------|-----------|-------------|
| מודל מותר | Opus 4 / Sonnet 4 | Sonnet 4 | Haiku / Sonnet |
| מכסה חודשית (tokens) | ללא הגבלה | 2,000,000 | 500,000 |
| גישה ל-Agents | מלאה | חלקית | ✗ |
| גישה לאימיילים | מלאה | קריאה בלבד | ✗ |
| גישה ללוגים | מלאה | צוות בלבד | עצמי בלבד |
| יצירת משתמשים | ✓ | ✗ | ✗ |
| שינוי API Keys | ✓ | ✗ | ✗ |

### 4.4 הגדרת 10 משתמשים — קוד הפעלה

```python
# setup/initialize_users.py
from claude_master import ClaudeMaster

def initialize_team(master: ClaudeMaster):
    """
    הפעל פעם אחת בלבד — אתחול 10 חברי הצוות
    """
    team_config = [
        {
            "user_id": "user_01",
            "name": "מנהל ראשי",
            "email": "admin@your-domain.com",
            "role": "master_admin",
            "allowed_model": "claude-opus-4-6",
            "monthly_token_limit": 0,  # ללא הגבלה
            "can_use_agents": True,
            "can_access_email": True
        },
        {
            "user_id": "user_02",
            "name": "Team Lead א׳",
            "email": "lead1@your-domain.com",
            "role": "team_lead",
            "allowed_model": "claude-sonnet-4-6",
            "monthly_token_limit": 2_000_000,
            "can_use_agents": True,
            "can_access_email": True
        },
        # user_03 ... user_10 — חברי צוות רגילים
        *[
            {
                "user_id": f"user_{i:02d}",
                "name": f"Team Member {i-2}",
                "email": f"member{i-2}@your-domain.com",
                "role": "team_member",
                "allowed_model": "claude-sonnet-4-6",
                "monthly_token_limit": 500_000,
                "can_use_agents": False,
                "can_access_email": False
            }
            for i in range(3, 11)
        ]
    ]

    for user_data in team_config:
        # יצירת API Key ב-Anthropic Console (ידנית) ורישום במערכת
        master.user_registry.create_user(user_data)
        print(f"✓ User {user_data['user_id']} ({user_data['name']}) initialized.")

# הרצה:
# master = ClaudeMaster()
# initialize_team(master)
```

### 4.5 רוטציה ועדכון API Keys

```python
# ניהול מפתחות — Claude Master בלבד
class APIKeyManager:

    def rotate_user_key(self, master_token: str, user_id: str, new_api_key: str):
        """
        עדכון מפתח API למשתמש.
        דורש: אימות Master Admin.
        """
        if not self.verify_master_token(master_token):
            raise PermissionError("Only Claude Master Admin can rotate API keys.")
        
        encrypted_key = self.encrypt(new_api_key)
        self.db.update_user_key(user_id, encrypted_key)
        self.audit_logger.log(
            action="api_key_rotated",
            user_id=user_id,
            performed_by="master_admin"
        )
        print(f"[MASTER ACTION] API Key for {user_id} rotated successfully.")

    def revoke_user_access(self, master_token: str, user_id: str, reason: str):
        """שלילת גישה מיידית ממשתמש"""
        self.db.deactivate_user(user_id)
        self.audit_logger.log(
            action="access_revoked",
            user_id=user_id,
            reason=reason
        )
```

### 4.6 ניטור מכסות שימוש

```python
# בדיקת מכסה לפני כל קריאה
def check_quota_before_call(user_id: str, estimated_tokens: int) -> bool:
    user = db.get_user(user_id)
    
    if user.monthly_token_limit == 0:
        return True  # Admin — ללא הגבלה
    
    remaining = user.monthly_token_limit - user.tokens_used_this_month
    
    if estimated_tokens > remaining:
        # שליחת התראה ל-Master Admin
        notify_master(
            f"User {user_id} has exceeded monthly quota. "
            f"Used: {user.tokens_used_this_month} / {user.monthly_token_limit}"
        )
        return False
    
    return True
```

---

## 5. ניהול אימיילים ב-Google Workspace

### 5.1 הגדרת Service Account ב-Google Cloud

**שלב 1 — יצירת Service Account:**
1. כנס ל-[Google Cloud Console](https://console.cloud.google.com)
2. צור פרויקט חדש: `claude-master-project`
3. הפעל את ה-APIs הבאים:
   - Gmail API
   - Google Workspace Admin SDK
   - Google Drive API (אופציונלי)
4. צור Service Account: `claude-master-service@PROJECT_ID.iam.gserviceaccount.com`
5. הורד קובץ JSON של המפתח → שמור כ-`./credentials/gws_service_account.json`

**שלב 2 — Domain-Wide Delegation:**
1. ב-[Google Workspace Admin Console](https://admin.google.com)
2. נווט: Security → API Controls → Domain-wide Delegation
3. הוסף Client ID של ה-Service Account
4. הגדר את ה-Scopes הבאים:
```
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/gmail.send
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/admin.directory.user.readonly
https://www.googleapis.com/auth/gmail.labels
```

### 5.2 מחלקת ניהול האימיילים

```python
# email/gws_manager.py
from google.oauth2 import service_account
from googleapiclient.discovery import build
import anthropic
import base64
from email.mime.text import MIMEText

class GWSEmailManager:
    """
    Claude Master — מנהל דואר אלקטרוני מרכזי ל-Google Workspace
    שולט בכל תיבות הדואר של 10 המשתמשים.
    """

    SCOPES = [
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.modify',
        'https://www.googleapis.com/auth/gmail.labels',
    ]

    def __init__(self):
        self.service_account_file = os.getenv("GWS_SERVICE_ACCOUNT_FILE")
        self.admin_email = os.getenv("GWS_ADMIN_EMAIL")
        self.domain = os.getenv("GWS_DOMAIN")
        self.claude = anthropic.Anthropic(api_key=os.getenv("MASTER_ANTHROPIC_API_KEY"))

    def _get_gmail_service(self, delegated_user_email: str):
        """יצירת שירות Gmail עם הרשאות delegated למשתמש ספציפי"""
        credentials = service_account.Credentials.from_service_account_file(
            self.service_account_file,
            scopes=self.SCOPES
        ).with_subject(delegated_user_email)
        
        return build('gmail', 'v1', credentials=credentials)

    def read_inbox(self, user_email: str, max_results: int = 20) -> list:
        """
        קריאת תיבת הדואר הנכנס של משתמש.
        Claude Master בלבד יכול לקרוא מיילים של כל המשתמשים.
        """
        service = self._get_gmail_service(user_email)
        results = service.users().messages().list(
            userId='me',
            labelIds=['INBOX'],
            maxResults=max_results
        ).execute()
        
        messages = []
        for msg in results.get('messages', []):
            detail = service.users().messages().get(
                userId='me', id=msg['id'], format='full'
            ).execute()
            messages.append(self._parse_message(detail))
        
        return messages

    def ai_summarize_inbox(self, user_email: str) -> str:
        """
        Claude מסכם את תיבת הדואר ומדגיש פריטים חשובים.
        """
        messages = self.read_inbox(user_email, max_results=30)
        
        email_text = "\n\n".join([
            f"From: {m['from']}\nSubject: {m['subject']}\nDate: {m['date']}\nSnippet: {m['snippet']}"
            for m in messages
        ])
        
        response = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": f"""סכם את תיבת הדואר הנכנס של {user_email}.
זהה: 1) פריטים דחופים 2) מיילים שדורשים תשובה 3) אשכולות נושאים.
מיילים:
{email_text}"""
            }]
        )
        return response.content[0].text

    def send_email(self, from_email: str, to: str, subject: str, body: str):
        """שליחת מייל בשם משתמש (Master בלבד)"""
        service = self._get_gmail_service(from_email)
        message = MIMEText(body, 'html')
        message['to'] = to
        message['from'] = from_email
        message['subject'] = subject
        
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(
            userId='me', body={'raw': raw}
        ).execute()
        
        self.audit_logger.log(
            action="email_sent",
            from_user=from_email,
            to=to,
            subject=subject
        )

    def auto_classify_and_label(self, user_email: str):
        """
        Agent אוטומטי: מסווג מיילים ומוסיף labels בעזרת AI.
        """
        messages = self.read_inbox(user_email, max_results=50)
        
        for msg in messages:
            classification = self.claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": f"Classify this email into one category: [URGENT, CLIENT, INTERNAL, NEWSLETTER, SPAM]\nSubject: {msg['subject']}\nFrom: {msg['from']}\nSnippet: {msg['snippet']}\nRespond with ONLY the category name."
                }]
            ).content[0].text.strip()
            
            self.apply_label(user_email, msg['id'], classification)

    def apply_label(self, user_email: str, message_id: str, label_name: str):
        """הוספת label למייל"""
        service = self._get_gmail_service(user_email)
        # יצירת label אם לא קיים + הוספה להודעה
        label_id = self._get_or_create_label(service, label_name)
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'addLabelIds': [label_id]}
        ).execute()

    def draft_ai_reply(self, user_email: str, message_id: str) -> str:
        """
        יצירת טיוטת תשובה חכמה לכל מייל.
        """
        service = self._get_gmail_service(user_email)
        message = service.users().messages().get(
            userId='me', id=message_id, format='full'
        ).execute()
        
        parsed = self._parse_message(message)
        
        draft = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": f"""כתוב טיוטת תשובה מקצועית למייל הבא. שמור על טון עניינוי ומכבד.
From: {parsed['from']}
Subject: {parsed['subject']}
Body: {parsed['body'][:2000]}

כתוב את התשובה בשפה שבה נכתב המייל המקורי."""
            }]
        ).content[0].text
        
        return draft
```

### 5.3 חשבונות Gmail ייעודיים ב-Workspace

יש ליצור ב-Google Workspace חשבון ייעודי לפעולות Claude Master:

```
claude-master@your-domain.com        ← חשבון ראשי של הסוכן
claude-notifications@your-domain.com ← שליחת התראות אוטומטיות
claude-reports@your-domain.com       ← שליחת דוחות תקופתיים
```

### 5.4 כללי ניהול אימיילים אוטומטיים

| כלל | פעולה | תדירות |
|-----|--------|--------|
| מיילים לא נפתחו > 48 שעות | התראה ל-Master | כל שעה |
| נושא מכיל "URGENT" | סיווג + הודעת Slack | מיידי |
| מייל לקוח חדש | יצירת טיוטת תשובה | מיידי |
| ניוזלטרים | תיוג אוטומטי + העברה לתיקייה | כל שעה |
| דוח שבועי | סיכום כל תיבות הדואר | כל יום ראשון 08:00 |

---

## 6. לוגים ומעקב שימוש

### 6.1 מבנה מסד הנתונים — טבלת Audit

```sql
-- אתחול מסד הנתונים
CREATE TABLE audit_logs (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ DEFAULT NOW(),
    user_id     VARCHAR(20) NOT NULL,
    action      VARCHAR(100) NOT NULL,
    model       VARCHAR(50),
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    cost_usd    DECIMAL(10, 6) DEFAULT 0,
    endpoint    VARCHAR(200),
    status      VARCHAR(20) DEFAULT 'success',  -- success | error | blocked
    metadata    JSONB,
    ip_address  INET
);

CREATE TABLE usage_monthly (
    user_id         VARCHAR(20),
    year_month      VARCHAR(7),  -- '2026-04'
    total_tokens    BIGINT DEFAULT 0,
    total_cost_usd  DECIMAL(10, 4) DEFAULT 0,
    api_calls       INTEGER DEFAULT 0,
    email_actions   INTEGER DEFAULT 0,
    agent_runs      INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, year_month)
);

CREATE INDEX idx_audit_user_time ON audit_logs(user_id, timestamp DESC);
CREATE INDEX idx_audit_action    ON audit_logs(action, timestamp DESC);
```

### 6.2 שירות הלוגים

```python
# logging/audit_logger.py
import psycopg2
import json
from datetime import datetime

class AuditLogger:

    def log(self, action: str, user_id: str, **kwargs):
        """
        רישום כל פעולה במערכת.
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "action": action,
            "model": kwargs.get("model"),
            "tokens_in": kwargs.get("tokens_in", 0),
            "tokens_out": kwargs.get("tokens_out", 0),
            "cost_usd": self._calculate_cost(
                kwargs.get("model"), 
                kwargs.get("tokens_in", 0), 
                kwargs.get("tokens_out", 0)
            ),
            "metadata": json.dumps(kwargs.get("metadata", {})),
            "status": kwargs.get("status", "success")
        }
        
        self.db.insert("audit_logs", entry)
        self._update_monthly_usage(user_id, entry)
        
        # בדיקת חריגות
        if entry["tokens_in"] + entry["tokens_out"] > 50_000:
            self._alert_master(f"Large API call detected for {user_id}: {entry}")

    def generate_usage_report(self, user_id: str = None, 
                               year_month: str = None) -> dict:
        """
        דוח שימוש — לפי משתמש או לכל המשתמשים.
        """
        query = """
            SELECT user_id, SUM(tokens_in) as total_in, 
                   SUM(tokens_out) as total_out,
                   SUM(cost_usd) as total_cost,
                   COUNT(*) as api_calls
            FROM audit_logs
            WHERE ($1::varchar IS NULL OR user_id = $1)
              AND ($2::varchar IS NULL OR TO_CHAR(timestamp, 'YYYY-MM') = $2)
            GROUP BY user_id
            ORDER BY total_cost DESC
        """
        return self.db.query(query, [user_id, year_month])
```

### 6.3 לוח בקרה — מדדים מרכזיים לניטור

```python
# dashboard/metrics.py
class MasterDashboard:

    def get_live_metrics(self) -> dict:
        return {
            "active_users_today": self.count_active_users_today(),
            "total_tokens_this_month": self.sum_tokens_this_month(),
            "estimated_cost_this_month_usd": self.estimate_monthly_cost(),
            "top_users_by_usage": self.get_top_users(limit=5),
            "recent_errors": self.get_recent_errors(limit=10),
            "quota_alerts": self.get_users_near_quota(threshold=0.8),
            "email_stats": {
                "processed_today": self.count_email_actions_today(),
                "pending_replies": self.count_pending_replies()
            },
            "active_agents": self.list_running_agents()
        }
```

---

## 7. Agents ואוטומציה

### 7.1 סוגי Agents במערכת

| Agent | תפקיד | תדירות הפעלה | הרשאות |
|-------|--------|--------------|--------|
| `email_classifier_agent` | סיווג אוטומטי של מיילים | כל 30 דקות | Gmail Read + Label |
| `inbox_summary_agent` | סיכום יומי של כל תיבות הדואר | 08:00 בוקר | Gmail Read |
| `quota_monitor_agent` | מעקב מכסות שימוש והתראות | כל שעה | DB Read |
| `weekly_report_agent` | דוח שבועי ל-Master Admin | ראשון 09:00 | כל הלוגים |
| `draft_reply_agent` | טיוטות תשובה למיילים ממתינים | כל שעתיים | Gmail Read+Draft |
| `onboarding_agent` | קבלת חברי צוות חדשים | On Demand | User Registry |

### 7.2. מנהל ה-Agents

```python
# agents/scheduler.py
import schedule
import threading
import time

class AgentScheduler:
    """
    מתזמן וממנהל את כל ה-Agents האוטומטיים של Claude Master.
    """

    def __init__(self, master: 'ClaudeMaster'):
        self.master = master
        self.running_agents = {}

    def register_all_agents(self):
        """רישום לוח הזמנים של כל ה-Agents"""

        # סיווג מיילים — כל 30 דקות
        schedule.every(30).minutes.do(
            self._run_for_all_users,
            agent_func=self.master.email_manager.auto_classify_and_label,
            agent_name="email_classifier_agent"
        )

        # סיכום יומי — כל יום ב-08:00
        schedule.every().day.at("08:00").do(
            self.run_inbox_summary_agent
        )

        # מעקב מכסות — כל שעה
        schedule.every().hour.do(
            self.run_quota_monitor_agent
        )

        # דוח שבועי — ראשון 09:00
        schedule.every().sunday.at("09:00").do(
            self.run_weekly_report_agent
        )

    def _run_for_all_users(self, agent_func, agent_name: str):
        """הפעלת Agent עבור כל 10 המשתמשים"""
        users = self.master.user_registry.get_all_users()
        for user in users:
            if user.can_access_email:
                try:
                    agent_func(user.email)
                    self.master.audit_logger.log(
                        action=f"agent_run_{agent_name}",
                        user_id=user.user_id,
                        status="success"
                    )
                except Exception as e:
                    self.master.audit_logger.log(
                        action=f"agent_run_{agent_name}",
                        user_id=user.user_id,
                        status="error",
                        metadata={"error": str(e)}
                    )

    def run_weekly_report_agent(self):
        """
        Agent שבועי: מסכם פעילות, שימוש ב-API, ומיילים חשובים.
        שולח דוח ל-Master Admin.
        """
        report_data = self.master.audit_logger.generate_usage_report(
            year_month=datetime.now().strftime("%Y-%m")
        )
        
        report_text = self.master.master_query(
            f"צור דוח שבועי מפורט למנהל. נתוני שימוש:\n{json.dumps(report_data, ensure_ascii=False)}"
        )
        
        self.master.email_manager.send_email(
            from_email="claude-reports@your-domain.com",
            to="admin@your-domain.com",
            subject=f"דוח שבועי Claude Master — {datetime.now().strftime('%d/%m/%Y')}",
            body=report_text
        )

    def start(self):
        """הפעלת ה-Scheduler ברקע"""
        self.register_all_agents()
        
        def run():
            while True:
                schedule.run_pending()
                time.sleep(60)
        
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        print("[MASTER] Agent Scheduler started.")
```

---

## 8. אבטחה ובקרת גישה

### 8.1 שכבות האבטחה

```
שכבה 1 — הצפנת API Keys (AES-256-GCM בכל מסד הנתונים)
שכבה 2 — JWT Authentication לכל בקשת API פנימית
שכבה 3 — IP Whitelist — רק כתובות ידועות יכולות לגשת ל-Master API
שכבה 4 — Rate Limiting — מניעת שימוש לרעה ב-API
שכבה 5 — Audit Trail מלא — כל פעולה רשומה ולא ניתנת למחיקה
שכבה 6 — Secret Rotation — מפתחות API מתחלפים אוטומטית כל 90 יום
```

### 8.2 מדיניות גישה (RBAC)

```python
# security/rbac.py
PERMISSIONS = {
    "master_admin": [
        "users:create", "users:delete", "users:update",
        "api_keys:read", "api_keys:rotate", "api_keys:revoke",
        "email:read_all", "email:send_as_any",
        "logs:read_all", "logs:export",
        "agents:create", "agents:delete", "agents:run",
        "system:configure", "system:shutdown"
    ],
    "team_lead": [
        "users:read",
        "email:read_own", "email:send_own",
        "logs:read_team",
        "agents:run_approved"
    ],
    "team_member": [
        "email:read_own", "email:send_own",
        "logs:read_own",
        "api:use_within_quota"
    ]
}

def require_permission(permission: str):
    """Decorator לבדיקת הרשאות"""
    def decorator(func):
        def wrapper(user, *args, **kwargs):
            user_permissions = PERMISSIONS.get(user.role.value, [])
            if permission not in user_permissions:
                raise PermissionError(
                    f"User {user.user_id} lacks permission: {permission}"
                )
            return func(user, *args, **kwargs)
        return wrapper
    return decorator
```

### 8.3 מדיניות אבטחה — כללי חובה

1. **אף פעם לא** לאחסן API Keys בקוד או ב-Git — תמיד משתני סביבה או Vault.
2. **רוטציה חובה** של מפתחות כל 90 יום, מיידית במקרה של דלף.
3. **חשבון שנרשם חריג** (>3 ניסיונות כושלים) — חסימה אוטומטית + התראה ל-Master.
4. **כל שינוי הרשאות** מחייב אישור Master Admin + רישום ב-Audit Log.
5. **גיבוי מסד הנתונים** — אוטומטי כל 24 שעות, שמירה ל-30 יום.

---

## 9. ניהול שכבות מתקדמות

### 9.1 Multi-Model Strategy

Claude Master מפנה בקשות למודל המתאים לפי סוג המשימה:

| סוג משימה | מודל מומלץ | עלות יחסית |
|-----------|-----------|-----------|
| ניהול ואסטרטגיה | Claude Opus 4 | גבוהה |
| כתיבה ועיבוד | Claude Sonnet 4 | בינונית |
| סיווג ורוטין | Claude Haiku 4.5 | נמוכה |
| עיבוד מיילים | Claude Haiku 4.5 | נמוכה |
| דוחות שבועיים | Claude Sonnet 4 | בינונית |

### 9.2 Context Management בין משתמשים

```python
# context/conversation_manager.py
class ConversationManager:
    """
    ניהול היסטוריית שיחות עבור כל משתמש בנפרד.
    Master יכול לצפות בכל ההיסטוריות.
    """
    
    def get_user_context(self, user_id: str, 
                          max_messages: int = 20) -> list:
        """שליפת 20 ההודעות האחרונות של המשתמש"""
        return self.db.get_messages(user_id, limit=max_messages)
    
    def add_to_context(self, user_id: str, role: str, content: str):
        """הוספת הודעה להיסטוריה"""
        self.db.insert_message(user_id, role, content)
    
    def clear_user_context(self, user_id: str, 
                            cleared_by: str = "user"):
        """מחיקת היסטוריה — עם רישום ב-Audit"""
        self.db.delete_messages(user_id)
        self.audit_logger.log(
            action="context_cleared",
            user_id=user_id,
            metadata={"cleared_by": cleared_by}
        )
```

### 9.3 Webhook & Integration Layer

```python
# integrations/webhooks.py
# Claude Master יכול לקבל ולשלוח Webhooks למערכות חיצוניות

SUPPORTED_INTEGRATIONS = {
    "slack": {
        "webhook_url": os.getenv("SLACK_WEBHOOK_URL"),
        "events": ["quota_alert", "error_critical", "weekly_report"]
    },
    "google_calendar": {
        "enabled": True,
        "events": ["meeting_summary", "action_items"]
    },
    "notion": {
        "api_key": os.getenv("NOTION_API_KEY"),
        "events": ["weekly_report", "email_summary"]
    }
}
```

---

## 10. נהלי תפעול ותחזוקה

### 10.1 הפעלה ראשונית — Checklist

```
[ ] 1. הגדרת Service Account ב-Google Cloud Console
[ ] 2. הפעלת Domain-Wide Delegation ב-Google Workspace Admin
[ ] 3. יצירת 10 API Keys נפרדים ב-Anthropic Console
[ ] 4. הגדרת קובץ .env.master עם כל הנתונים
[ ] 5. אתחול מסד הנתונים: python setup/init_db.py
[ ] 6. יצירת 10 חשבונות משתמשים: python setup/initialize_users.py
[ ] 7. בדיקת חיבור Gmail: python tests/test_gmail_connection.py
[ ] 8. הפעלת שרת Claude Master: python main.py
[ ] 9. בדיקת Agent Scheduler: python tests/test_agents.py
[ ] 10. שליחת דוח בדיקה ל-Admin: python tests/test_report.py
```

### 10.2 פקודות ניהול שוטף

```bash
# בדיקת סטטוס כל המשתמשים
python manage.py status --all-users

# רוטציה של API Key למשתמש ספציפי
python manage.py rotate-key --user user_03 --new-key sk-ant-...

# שלילת גישה ממשתמש
python manage.py revoke --user user_07 --reason "security_breach"

# הרצת דוח שימוש חודשי
python manage.py report --month 2026-04 --output report.pdf

# עצירה והפעלה מחדש של Agent
python manage.py agent restart --name email_classifier_agent
```

### 10.3 ניהול תקלות נפוצות

| תקלה | סיבה אפשרית | פתרון |
|------|-------------|--------|
| `PermissionError: User not active` | המשתמש חסום או לא קיים | בדוק `user.is_active` ב-DB |
| `Gmail API 403 Forbidden` | Domain Delegation לא מוגדר | אמת הגדרות ב-Google Workspace Admin |
| `Anthropic rate limit` | חריגה ממכסה | הגדל מכסה או צמצם קצב בקשות |
| `JWT Token expired` | פג תוקף session | רענן token, בדוק `SESSION_TIMEOUT_HOURS` |
| `Agent not running` | Thread קרס | `python manage.py agent restart --name AGENT_NAME` |

### 10.4 גיבוי ושחזור

```bash
# גיבוי יומי אוטומטי (הוסף ל-cron)
0 2 * * * pg_dump claude_master_db > /backups/claude_master_$(date +\%Y\%m\%d).sql

# שחזור מגיבוי
psql claude_master_db < /backups/claude_master_20260424.sql
```

---

## נספח א׳ — רשימת תלויות (requirements.txt)

```
anthropic>=0.25.0
google-auth>=2.28.0
google-auth-oauthlib>=1.2.0
google-api-python-client>=2.120.0
psycopg2-binary>=2.9.9
python-dotenv>=1.0.0
schedule>=1.2.0
cryptography>=42.0.0
pyjwt>=2.8.0
fastapi>=0.110.0
uvicorn>=0.27.0
```

## נספח ב׳ — קישורים חשובים

- [Anthropic Console — ניהול API Keys](https://console.anthropic.com)
- [Google Cloud Console](https://console.cloud.google.com)
- [Google Workspace Admin](https://admin.google.com)
- [Claude API Documentation](https://docs.anthropic.com)
- [Gmail API Reference](https://developers.google.com/gmail/api)

---

*מסמך זה סווג כ"פנימי" — אין להפיצו מחוץ לצוות הניהול.*  
*עודכן לאחרונה: אפריל 2026 | גרסה: 1.0*
