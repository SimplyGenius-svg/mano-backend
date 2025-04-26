import os
import time
import smtplib
from dotenv import load_dotenv
from email.mime.text import MIMEText

from mail_reader import fetch_all_unread_emails, load_seen_ids, save_seen_ids
from founder import handle_founder_email, handle_founder_reply
from partner import handle_partner_email
from partner import create_reminder, start_background_services
from firebase import db
from firebase_admin import firestore
from gpt_helpers import classify_founder_email_intent  # New function for smarter classification

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

# 🧪 Partner whitelist
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
        print(f"❌ Failed to send reply to {to_email}: {e}")

# 🔁 Main loop
def run_agent():
    seen = load_seen_ids()
    print("Mano is live and listening...")
    
    # Start the background reminder service
    start_background_services()
    print("🔔 Background reminder service started")

    while True:
        try:
            emails = fetch_all_unread_emails()

            if not emails:
                print("👭 No new emails found.")
            else:
                for email_obj in emails:
                    email_id = f"{email_obj['id']}_{email_obj['sender']}"

                    if email_id in seen:
                        print(f"↪️ Already seen: {email_obj['subject']}")
                        continue

                    print(f"\n📨 New email from {email_obj['sender']}: {email_obj['subject']}")

                    sender = email_obj['sender'].lower()
                    body = email_obj.get("body", "").lower()

                    try:
                        if sender in PARTNER_EMAILS:
                            print("🔁 Routing to partner logic...")
                            # The handle_partner_email function now handles reminder creation internally
                            # if it detects a reminder request in the email
                            handle_partner_email(email_obj)
                        else:
                            # Check if founder has a previous pitch
                            docs = db.collection("pitches")\
                                .where("sender", "==", sender)\
                                .order_by("timestamp", direction=firestore.Query.DESCENDING)\
                                .limit(1)\
                                .stream()

                            doc = next(docs, None)

                            if doc:
                                intent = classify_founder_email_intent(body)
                                if intent == "feedback":
                                    print("💬 Detected founder asking for feedback...")
                                    handle_founder_reply(email_obj)
                                else:
                                    print("📬 Detected new founder pitch or update...")
                                    reply = handle_founder_email(email_obj)
                                    if reply:
                                        send_email_reply(email_obj["sender"], email_obj["subject"], reply)
                            else:
                                print("📬 No previous pitch found — treating as new pitch...")
                                reply = handle_founder_email(email_obj)
                                if reply:
                                    send_email_reply(email_obj["sender"], email_obj["subject"], reply)

                        seen.add(email_id)
                        save_seen_ids(seen)

                    except Exception as e:
                        print(f"❌ Error while processing email from {email_obj['sender']}: {e}")

            # No need to check reminders here - background service handles this

        except Exception as loop_err:
            print(f"🔥 Agent loop error: {loop_err}")

        time.sleep(10)

# 🚀 Entry point
if __name__ == "__main__":
    run_agent()
