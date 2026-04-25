#!/bin/bash
cd "$(dirname "$0")"

echo "🔧 יוצר סביבה מבודדת..."

# יצירת venv עם python3.12
rm -rf venv
python3.12 -m venv venv

# הפעלת venv
source venv/bin/activate

echo "🔧 מתקין ספריות..."
pip install --quiet --upgrade \
    google-auth \
    google-auth-oauthlib \
    google-auth-httplib2 \
    google-api-python-client \
    python-dotenv

echo ""
echo "✅ ספריות מותקנות"
echo "🚀 מחבר Gmail..."
echo ""

python email/gmail_manager.py
