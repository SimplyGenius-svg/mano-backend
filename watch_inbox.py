import imaplib
import email
from email.header import decode_header
import os
import time
import tempfile
import requests
from dotenv import load_dotenv
from pathlib import Path
from vector_db import PitchVectorDB

# Load environment
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
UPLOAD_ENDPOINT = "http://127.0.0.1:5000/upload"  # Replace with hosted URL later

# Initialize vector database
vector_db = PitchVectorDB()

def clean_subject(s):
    try:
        subject, encoding = decode_header(s)[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding if encoding else "utf-8")
        return subject
    except:
        return s


def handle_attachments(msg, from_email, subject):
    for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        if part.get("Content-Disposition") is None:
            continue
        filename = part.get_filename()
        if filename and filename.endswith(".pdf"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(part.get_payload(decode=True))
                tmp_file.flush()
                print(f"📎 Found PDF: {filename} — Uploading to Mano...")
                with open(tmp_file.name, "rb") as f:
                    response = requests.post(
                        UPLOAD_ENDPOINT,
                        files={"file": f},
                        data={"from_email": from_email, "subject": subject}
                    )
                    if response.status_code == 200:
                        print("📬 Response from Mano:", response.json())
                        # Vector DB storage is handled in the app.py endpoint
                    else:
                        print(f"❌ Error from API: {response.status_code}")
                        print(response.text)


def check_inbox():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("inbox")

    status, messages = mail.search(None, '(UNSEEN)')
    mail_ids = messages[0].split()

    for mail_id in mail_ids:
        res, msg_data = mail.fetch(mail_id, "(RFC822)")
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                subject = clean_subject(msg["Subject"])
                from_email = msg["From"].split('<')[-1].strip('>') if '<' in msg["From"] else msg["From"]
                print(f"📥 New email from: {from_email} | Subject: {subject}")
                handle_attachments(msg, from_email, subject)

    mail.logout()


if __name__ == "__main__":
    print("📡 Listening to inbox for new PDFs...")
    while True:
        check_inbox()
        time.sleep(60)  # check every 60 seconds