import logging
from component_logger import log_component
from firebase import db
from firebase_admin import firestore
from datetime import datetime

logging.basicConfig(level=logging.INFO)

@log_component("memory_logger")
def save_memory(sender_email, subject, body, tags, memory_type):
    memory_data = {
        "sender": sender_email,
        "subject": subject,
        "body": body,
        "tags": tags,
        "type": memory_type,
        "timestamp": datetime.utcnow()
    }
    db.collection('partner_memory').add(memory_data)
    logging.info(f"🧠 Memory saved: {memory_data}")

def log_memory_usage():
    pass

if __name__ == '__main__':
    log_memory_usage()
