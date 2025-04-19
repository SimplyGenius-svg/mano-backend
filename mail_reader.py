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

        subject, encoding = decode_header(msg["Subject"])[0]
        subject = subject.decode(encoding or "utf-8") if isinstance(subject, bytes) else subject
        sender = msg.get("From")
        date = msg.get("Date")

        body = ""
        attachments = {}

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))

                # Parse text/plain part
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    except:
                        pass

                # Parse attachments (PDFs)
                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    if filename and filename.lower().endswith(".pdf"):
                        attachments[filename] = part.get_payload(decode=True)
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

        emails.append({
            "id": eid.decode(),
            "subject": subject,
            "sender": sender,
            "date": date,
            "body": body[:3000],
            "attachments": attachments
        })

    return emails
