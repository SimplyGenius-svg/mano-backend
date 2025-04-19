# mano.py

import os
from dotenv import load_dotenv
from mail_reader import fetch_latest_email  # 🔄 Now using IMAP, not Gmail API
from brain import process_incoming_email    # 🧠 Full decision logic

# 🔐 Load environment variables
load_dotenv()

if __name__ == "__main__":
    email = fetch_latest_email()

    print(f"\n📨 Email from: {email['sender']}")
    print(f"📌 Subject: {email['subject']}")
    print("\n🧠 Mano’s Take:\n" + "=" * 50)

    response = process_incoming_email(email)
    print(response)
    print("=" * 50)
