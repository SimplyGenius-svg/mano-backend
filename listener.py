import imaplib
import email
from email.header import decode_header
import os
from dotenv import load_dotenv

# Load .env for credentials
load_dotenv()
EMAIL = os.getenv("EMAIL_USER")
PASSWORD = os.getenv("EMAIL_PASS")

def clean_subject(subject):
    if isinstance(subject, bytes):
        subject = subject.decode()
    return subject.strip()

def connect():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(EMAIL, PASSWORD)
    mail.select("inbox")
    return mail

def fetch_latest_pitch_decks():
    mail = connect()
    status, messages = mail.search(None, '(UNSEEN)')
    email_ids = messages[0].split()
    
    for eid in email_ids:
        res, msg = mail.fetch(eid, "(RFC822)")
        for response in msg:
            if isinstance(response, tuple):
                msg_data = email.message_from_bytes(response[1])
                subject = clean_subject(decode_header(msg_data["Subject"])[0][0])
                from_email = msg_data["From"]
                print(f"📥 New Email from {from_email} | Subject: {subject}")
                
                for part in msg_data.walk():
                    if part.get_content_maintype() == 'multipart':
                        continue
                    if part.get("Content-Disposition") is None:
                        continue
                    filename = part.get_filename()
                    if filename and filename.endswith(".pdf"):
                        filepath = os.path.join("incoming", filename)
                        with open(filepath, "wb") as f:
                            f.write(part.get_payload(decode=True))
                        print(f"✅ Saved: {filepath}")
                        return from_email, filepath, subject
    return None, None, None

if __name__ == "__main__":
    os.makedirs("incoming", exist_ok=True)
    sender, pdf_path, subject = fetch_latest_pitch_decks()
    if pdf_path:
        print(f"📎 Ready to process: {pdf_path}")
    else:
        print("📭 No new pitch decks found.")
