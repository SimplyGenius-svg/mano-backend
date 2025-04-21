import os
import json
import time
import smtplib
from dotenv import load_dotenv
from email.mime.text import MIMEText

from mail_reader import fetch_all_unread_emails, load_seen_ids, save_seen_ids
from founder import handle_founder_email
from partner import handle_partner_email, check_due_reminders  # ✅ Make sure both are defined in partner.py

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

# 🧠 Partner whitelist
PARTNER_EMAILS = {
    "gyanbhambhani@gmail.com",
    "yourpartner2@vcfirm.com"
}

# ✉️ Send reply via SMTP
def send_email_reply(to_email, subject, reply_text):
    msg = MIMEText(reply_text)
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = EMAIL_USER
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, [to_email], msg.as_string())
        print(f"✅ Reply sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send reply: {e}")

# 🔁 Main loop
def run_agent():
    seen = load_seen_ids()
    print("👂 Mano is live and listening...")

    while True:
        try:
            emails = fetch_all_unread_emails()

            if not emails:
                print("📭 No new emails found.")
            else:
                for email_obj in emails:
                    email_id = f"{email_obj['id']}_{email_obj['sender']}".lower()

                    if email_id in seen:
                        print(f"↪️ Already seen: {email_obj['subject']}")
                        continue

                    print(f"\n📨 New email from {email_obj['sender']}: {email_obj['subject']}")

                    try:
                        sender = email_obj['sender'].lower()
                        if sender in PARTNER_EMAILS:
                            print("🔁 Routing to partner logic...")
                            reply = handle_partner_email(email_obj)
                        else:
                            print("📤 Routing to founder logic...")
                            reply = handle_founder_email(email_obj)

                        if reply:
                            send_email_reply(email_obj["sender"], email_obj["subject"], reply)

                        seen.add(email_id)
                        save_seen_ids(seen)

                    except Exception as e:
                        print(f"❌ Error while processing email from {email_obj['sender']}: {e}")

            # 🔔 Run partner reminder logic
            try:
                check_due_reminders()
            except Exception as err:
                print(f"⚠️ Reminder check failed: {err}")

        except Exception as loop_err:
            print(f"🔥 Agent loop error: {loop_err}")

        time.sleep(10)

# 🚀 Entry point
if __name__ == "__main__":
    run_agent()
