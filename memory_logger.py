import logging
logging.basicConfig(level=logging.INFO)

def log_memory_usage():
    from component_logger import log_component
    from firebase import db
    from firebase_admin import firestore
    from datetime import datetime

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

if __name__ == '__main__':
    log_memory_usage()
