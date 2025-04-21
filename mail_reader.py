import imaplib
import email
from email.header import decode_header
import os
import json
import re
from dotenv import load_dotenv

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
SEEN_LOG = "seen.json"

# 🧠 Seen ID cache helpers
def load_seen_ids():
    if not os.path.exists(SEEN_LOG):
        return set()
    with open(SEEN_LOG, "r") as f:
        return set(json.load(f))

def save_seen_ids(ids):
    with open(SEEN_LOG, "w") as f:
        json.dump(list(ids), f)

# ✉️ Clean sender email from name <email@example.com>
def clean_sender(raw_sender):
    match = re.search(r'<(.+?)>', raw_sender)
    return match.group(1).lower() if match else raw_sender.strip().lower()

# 📥 Decode subject line if it's MIME encoded
def decode_mime_words(header_val):
    parts = decode_header(header_val)
    decoded = ""
    for part, encoding in parts:
        if isinstance(part, bytes):
            decoded += part.decode(encoding or "utf-8", errors="ignore")
        else:
            decoded += part
    return decoded.strip()

# 🔐 Connect to Gmail via IMAP
def connect_to_mailbox():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")
    return mail

# 📩 Fetch all unread emails
def fetch_all_unread_emails():
    mail = connect_to_mailbox()
    status, messages = mail.search(None, "UNSEEN")
    email_ids = messages[0].split()
    emails = []

    for eid in email_ids:
        status, msg_data = mail.fetch(eid, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_mime_words(msg.get("Subject", "No Subject"))
        sender = clean_sender(msg.get("From", ""))
        date = msg.get("Date", "")
        body = ""
        attachments = {}

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    except:
                        continue

                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename and filename.lower().endswith(".pdf"):
                        attachments[filename] = part.get_payload(decode=True)
        else:
            try:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
            except:
                body = ""

        emails.append({
            "id": eid.decode(),
            "subject": subject,
            "sender": sender,
            "date": date.strip(),
            "body": body.strip()[:5000],
            "attachments": attachments
        })

    mail.logout()
    return emails
