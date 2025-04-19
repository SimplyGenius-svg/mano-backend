# mail_reader.py

import imaplib
import email
from email.header import decode_header
import os
from dotenv import load_dotenv

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

def fetch_all_unread_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    status, messages = mail.search(None, "UNSEEN")
    email_ids = messages[0].split()

    emails = []
    for eid in email_ids:
        status, msg_data = mail.fetch(eid, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        subject = decode_header(msg["Subject"])[0][0]
        sender = msg.get("From")
        date = msg.get("Date")

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

        emails.append({
            "id": eid.decode(),
            "subject": subject if isinstance(subject, str) else subject.decode(),
            "sender": sender,
            "date": date,
            "body": body[:3000]
        })

    return emails
