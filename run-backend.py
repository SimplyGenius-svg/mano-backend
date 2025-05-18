# run_backend.py

import threading
import time

from agent import main as run_agent
from mail_reader import read_mail
from weekly_digest import main as run_digest
from firebase import initialize_firebase
from vector_client import connect

def start_agent():
    print("🧠 Starting agent...")
    run_agent()

def start_mail_reader():
    print("📩 Starting mail reader...")
    while True:
        read_mail()
        time.sleep(60)  # Poll every 60 seconds

def start_weekly_digest():
    print("📰 Starting weekly digest...")
    run_digest()

def main():
    print("🚀 Initializing Mano Backend...")

    # Step 1: Initialize core services
    initialize_firebase()
    connect()

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
