import os
from dotenv import load_dotenv
from firebase import db
from firebase_admin import firestore
from datetime import datetime
from gpt_helpers import chat_with_gpt
import smtplib
from email.mime.text import MIMEText

load_dotenv()
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
PARTNER_EMAIL = "gyanbhambhani@gmail.com"

def fetch_pending_reminders():
    return db.collection("reminders").where("status", "==", "pending").stream()

def generate_digest():
    reminders = fetch_pending_reminders()
    entries = []
    for doc in reminders:
        data = doc.to_dict()
        due = data.get("due", "N/A")
        entries.append(f"🔁 {data.get('title', 'Untitled')} — due {due}\n{data.get('body', '')}\n")

    joined = "\n\n".join(entries) if entries else "✅ No outstanding follow-ups."

    prompt = f"""
You are summarizing this week's outstanding reminders for a VC partner.

Here is the raw list:
---
{joined}
---

Format it as a clean Monday morning digest. Prioritize clarity and follow-up focus.
"""
    return chat_with_gpt(prompt)

def send_digest_email(content):
    msg = MIMEText(content)
    msg["Subject"] = "📬 Mano Digest – Weekly VC Reminders"
    msg["From"] = EMAIL_USER
    msg["To"] = PARTNER_EMAIL

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, [PARTNER_EMAIL], msg.as_string())
        print(f"✅ Weekly digest sent to {PARTNER_EMAIL}")
    except Exception as e:
        print(f"❌ Failed to send digest: {e}")

if __name__ == "__main__":
    digest = generate_digest()
    send_digest_email(digest)
