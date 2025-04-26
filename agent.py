import os
import time
import json
import email
import imaplib
import logging
import datetime
import traceback
import threading
from dotenv import load_dotenv

from firebase import db
from firebase_admin import firestore
from founder import handle_founder_email, handle_founder_reply, run_scheduled_tasks
from reminder import reminder_checker_loop
from partner import process_partner_email

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("agent")

# Load environment variables
load_dotenv()

# Email credentials
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")

# Known domains for classification
FOUNDER_DOMAINS = [
    "gmail.com", 
    "yahoo.com", 
    "outlook.com", 
    "hotmail.com",
    "berkeley.edu",  # University domains
    "stanford.edu",
    "mit.edu",
    "harvard.edu"
]

# List of specific partner emails - everything else is treated as founders
PARTNER_EMAILS = [
    "gyanbhambhani@gmail.com",
    "mano@mano.network"
]

# Email management functions
def connect_to_email_server():
    """Connect to the email server"""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        return mail
    except Exception as e:
        logger.error(f"Failed to connect to email server: {e}")
        return None

def fetch_new_emails(mail):
    """Fetch new unread emails"""
    try:
        mail.select("inbox")
        status, messages = mail.search(None, "UNSEEN")
        
        if status != "OK" or not messages[0]:
            return []
        
        message_ids = messages[0].split()
        email_data = []
        
        for msg_id in message_ids:
            try:
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                email_message = email.message_from_bytes(raw_email)
                
                # Extract basic info
                sender = email.utils.parseaddr(email_message["From"])[1]
                subject = email_message["Subject"]
                thread_id = email_message.get("Message-ID", "")
                
                # Extract recipients
                to_field = email_message.get("To", "")
                cc_field = email_message.get("Cc", "")
                recipients = []
                
                if to_field:
                    recipients.extend([email.utils.parseaddr(addr)[1] for addr in to_field.split(",")])
                if cc_field:
                    recipients.extend([email.utils.parseaddr(addr)[1] for addr in cc_field.split(",")])
                
                # Process body and attachments
                body = ""
                attachments = {}
                
                if email_message.is_multipart():
                    for part in email_message.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        
                        # Extract body text
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            payload = part.get_payload(decode=True)
                            if payload:
                                try:
                                    body = payload.decode()
                                except UnicodeDecodeError:
                                    # Try with different encodings if needed
                                    try:
                                        body = payload.decode('latin-1')
                                    except:
                                        body = str(payload)
                        
                        # Extract attachments (especially PDFs)
                        if "attachment" in content_disposition:
                            filename = part.get_filename()
                            if filename and filename.lower().endswith('.pdf'):
                                attachments[filename] = part.get_payload(decode=True)
                else:
                    payload = email_message.get_payload(decode=True)
                    if payload:
                        try:
                            body = payload.decode()
                        except UnicodeDecodeError:
                            try:
                                body = payload.decode('latin-1')
                            except:
                                body = str(payload)
                        except AttributeError:
                            body = str(payload)
                
                email_obj = {
                    "message_id": msg_id,
                    "thread_id": thread_id,
                    "sender": sender,
                    "recipients": recipients,
                    "subject": subject,
                    "body": body,
                    "attachments": attachments,
                    "timestamp": datetime.datetime.now().isoformat()
                }
                
                email_data.append(email_obj)
                
            except Exception as e:
                logger.error(f"Error processing email {msg_id}: {e}")
                logger.error(traceback.format_exc())
        
        return email_data
        
    except Exception as e:
        logger.error(f"Failed to fetch emails: {e}")
        logger.error(traceback.format_exc())
        return []

def is_founder_email(email_obj):
    """Determine if this email is from a founder"""
    sender = email_obj["sender"].lower()
    
    # First, make sure it's not from a partner domain
    domain = sender.split("@")[-1]
    if domain in PARTNER_EMAILS:
        return False
    
    # Check if this is a common consumer domain used by founders
    if domain in FOUNDER_DOMAINS:
        return True
    
    # Check if we have a record of this founder
    try:
        founder_docs = db.collection("founders").where("email", "==", sender).limit(1).get()
        if len(founder_docs) > 0:
            print(f"📬 Detected founder with previous pitch...")
            return True
    except Exception as e:
        logger.error(f"Failed to check founder database: {e}")
    
    # Check email content for founder indicators
    body = email_obj["body"].lower()
    subject = email_obj["subject"].lower()
    
    founder_indicators = [
        "startup", "founder", "pitch", "deck", "fundraising", "raising", 
        "seed", "pre-seed", "series a", "investment", "venture"
    ]
    
    if any(indicator in subject for indicator in founder_indicators):
        return True
    
    if any(indicator in body for indicator in founder_indicators):
        return True
    
    return False

def is_partner_email(email_obj):
    """Determine if this email is from a specific partner email address"""
    sender = email_obj["sender"].lower()
    
    # Check if it's one of our explicitly listed partner emails
    if sender in PARTNER_EMAILS:
        print(f"🤝 Detected email from known partner: {sender}")
        return True
    
    return False

def is_reply_email(email_obj, collection_name="founder_communications"):
    """Determine if this is a reply to our previous communication"""
    subject = email_obj["subject"]
    
    if subject and subject.lower().startswith("re:"):
        return True
    
    # Check if we have prior communication with this sender
    sender = email_obj["sender"]
    
    try:
        # Check if we have sent any emails to this person
        comm_docs = db.collection(collection_name)\
            .where("sender", "==", sender)\
            .limit(1)\
            .get()
        
        if len(comm_docs) > 0:
            return True
    except Exception as e:
        logger.error(f"Failed to check communication history: {e}")
    
    return False

def process_email(email_obj):
    """Process a single email based on its type"""
    try:
        sender = email_obj["sender"]
        subject = email_obj["subject"]
        
        # Determine email type - check partner first to avoid misclassification
        if is_partner_email(email_obj):
            logger.info(f"Processing partner email from {sender}: {subject}")
            print(f"🤝 Processing email from partner: {sender}")
            
            # Process through partner pipeline
            result = process_partner_email(email_obj)
            
            # Safely convert result to string for logging if needed
            if isinstance(result, dict):
                try:
                    result_str = json.dumps(result)
                except:
                    result_str = str(result)
            else:
                result_str = str(result)
                
            return result
            
        elif is_founder_email(email_obj):
            logger.info(f"Processing founder email from {sender}: {subject}")
            
            # Check if this is a reply to previous communication
            if is_reply_email(email_obj):
                # Handle as a reply
                print(f"📝 Processing founder reply: {sender}")
                result = handle_founder_reply(email_obj)
                return result
            else:
                # Handle as a new pitch or inquiry
                print(f"📊 Processing new founder pitch/inquiry: {sender}")
                result = handle_founder_email(email_obj)
                return result
        else:
            # Log other emails for manual review
            logger.info(f"Unclassified email from {sender}: {subject}")
            print(f"📩 Unclassified email from: {sender}")
            
            # Store in the database for reference
            try:
                other_mail_data = {
                    "sender": sender,
                    "subject": subject,
                    "body": email_obj["body"],
                    "recipients": email_obj.get("recipients", []),
                    "thread_id": email_obj.get("thread_id", ""),
                    "type": "other",
                    "processed": False,
                    "timestamp": firestore.SERVER_TIMESTAMP
                }
                
                db.collection("other_emails").add(other_mail_data)
            except Exception as e:
                logger.error(f"Failed to store unclassified email: {e}")
            
            return {
                "status": "unclassified",
                "message": "Email not identified as founder or partner"
            }
    except Exception as e:
        error_message = f"Error while processing email from {email_obj['sender']}: {str(e)}"
        traceback_str = traceback.format_exc()
        logger.error(f"{error_message}\n{traceback_str}")
        
        # Store the error for debugging
        try:
            error_data = {
                "sender": email_obj["sender"],
                "subject": email_obj["subject"],
                "error": str(e),
                "traceback": traceback_str,
                "timestamp": firestore.SERVER_TIMESTAMP
            }
            
            db.collection("processing_errors").add(error_data)
        except Exception as inner_e:
            logger.error(f"Failed to log error: {inner_e}")
        
        # Return sanitized error information
        return {
            "status": "error",
            "message": error_message
        }

def record_health_check():
    """Record a health check in the database"""
    try:
        health_data = {
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": "healthy",
            "version": "1.0.2",  # Increment this when you make significant changes
            "last_check": datetime.datetime.now().isoformat()
        }
        
        db.collection("system_health").document("agent").set(health_data)
        
    except Exception as e:
        logger.error(f"Failed to record health check: {e}")

def run_agent():
    """Main function to run the email processing agent"""
    print("Mano is live and listening...")
    
    # Start the reminder service in a background thread
    reminder_thread = threading.Thread(target=reminder_checker_loop)
    reminder_thread.daemon = True
    reminder_thread.start()
    
    print("🔔 Background reminder service started")
    
    # Main processing loop
    while True:
        try:
            # Health check
            record_health_check()
            
            # Process scheduled tasks
            run_scheduled_tasks()
            
            # Connect to email server
            mail = connect_to_email_server()
            if not mail:
                logger.warning("Failed to connect to email server, will retry in 10 seconds")
                time.sleep(10)
                continue
            
            # Fetch new emails
            new_emails = fetch_new_emails(mail)
            
            if not new_emails:
                print("👭 No new emails found.")
            
            # Process each email
            for email_obj in new_emails:
                print(f"📨 New email from {email_obj['sender']}: {email_obj['subject']}")
                
                # Process the email safely
                try:
                    result = process_email(email_obj)
                    
                    # Log result (safely convert to string if dict)
                    if isinstance(result, dict):
                        try:
                            result_str = json.dumps(result)
                        except Exception:
                            result_str = str(result)
                    else:
                        result_str = str(result)
                    
                    if result and isinstance(result, dict) and result.get("status") == "error":
                        print(f"❌ {result.get('message', 'Unknown error')}")
                    
                except Exception as e:
                    error_trace = traceback.format_exc()
                    logger.error(f"Unhandled exception in email processing: {str(e)}\n{error_trace}")
                    print(f"❌ Unhandled error while processing email: {str(e)}")
            
            # Clean up
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass
            
            # Sleep before next check
            time.sleep(10)
            
        except KeyboardInterrupt:
            print("\nShutting down Mano...")
            break
            
        except Exception as e:
            error_trace = traceback.format_exc()
            logger.error(f"Unhandled exception in main loop: {str(e)}\n{error_trace}")
            print(f"⚠️ Unhandled error in main loop: {str(e)}")
            time.sleep(30)  # Longer delay after errors

if __name__ == "__main__":
    run_agent()