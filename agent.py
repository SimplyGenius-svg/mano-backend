# agent.py

import os
import json
import time
import smtplib
from dotenv import load_dotenv
from email.mime.text import MIMEText
from mail_reader import fetch_all_unread_emails
from brain import process_incoming_email

load_dotenv()
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

SEEN_LOG = "seen.json"

def load_seen_ids():
    if not os.path.exists(SEEN_LOG):
        return set()
    with open(SEEN_LOG, 'r') as f:
        return set(json.load(f))

def save_seen_ids(ids):
    with open(SEEN_LOG, 'w') as f:
        json.dump(list(ids), f)

def send_email_reply(to_email, subject, reply_text):
    msg = MIMEText(reply_text)
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = EMAIL_USER
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, [to_email], msg.as_string())

    print(f"✅ Reply sent to {to_email}")

def run_agent():
    seen = load_seen_ids()
    print("👂 Mano is listening...")

    while True:
        try:
            emails = fetch_all_unread_emails()

            if not emails:
                print("📭 No unread emails found.")
            else:
                for email in emails:
                    email_id = f"{email['sender']}-{email['subject']}"

                    if email_id in seen:
                        print(f"↪️ Already seen: {email['subject']}")
                        continue

                    print(f"\n📨 Email from {email['sender']}: {email['subject']}")
                    print("🧠 Processing...\n" + "=" * 50)

                    response = process_incoming_email(email)
                    print(response)
                    print("=" * 50)

                    send_email_reply(email["sender"], email["subject"], response)
                    seen.add(email_id)
                    save_seen_ids(seen)

        except Exception as e:
            print(f"🔥 Error: {e}")

        time.sleep(60)

if __name__ == "__main__":
    run_agent()
