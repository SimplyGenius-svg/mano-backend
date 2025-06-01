# run_backend.py

import threading
import time

from agent import run_agent
from mail_reader import fetch_all_unread_emails
from weekly_digest import VCDigestGenerator

def start_agent():
    print("🧠 Starting agent...")
    run_agent()

def start_mail_reader():
    print("📩 Starting mail reader...")
    while True:
        fetch_all_unread_emails()
        time.sleep(60)  # Poll every 60 seconds

def start_weekly_digest():
    print("📰 Starting weekly digest...")
    digest_generator = VCDigestGenerator()
    digest_generator.process_all_partner_digests()

def main():
    print("🚀 Initializing Mano Backend...")

    # Step 1: Initialize core services
    # Vector client and Firebase initialize automatically on import

    # Step 2: Launch threads
    agent_thread = threading.Thread(target=start_agent, daemon=True)
    mail_thread = threading.Thread(target=start_mail_reader, daemon=True)
    digest_thread = threading.Thread(target=start_weekly_digest, daemon=True)

    agent_thread.start()
    mail_thread.start()
    digest_thread.start()

    # Step 3: Keep main thread alive
    print("✅ Mano backend is running. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Mano backend...")

if __name__ == "__main__":
    main()
