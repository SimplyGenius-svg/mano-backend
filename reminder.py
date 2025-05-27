import json
import os
import re
import threading
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Union
import dateparser
from firebase_admin import firestore, initialize_app, credentials
from openai import OpenAI
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

from src.util.firebase import db

# Load environment variables
load_dotenv()
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("reminder_system")

# Initialize Firebase
try:
    # Check if already initialized
    firebase_app = initialize_app(
        credentials.Certificate(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
    )
    logger.info("Firebase initialized successfully")
except ValueError as e:
    if "already exists" in str(e):
        logger.info("Firebase already initialized")
    else:
        logger.error(f"Firebase initialization error: {e}")
        raise

# Initialize Firestore
logger.info("Firestore client initialized")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)
logger.info("OpenAI client initialized")

def extract_reminder_time(text: str) -> Optional[datetime]:
    """
    Extract a time specification from a reminder request in text.
    Uses multiple patterns to find time references.
    
    Args:
        text: The text to search for time references
        
    Returns:
        datetime object if a valid future time is found, None otherwise
    """
    # Try multiple regex patterns to catch different reminder phrasings
    patterns = [
        r"remind me (?:to .+? )?(?:at|on|in|by) (.+?)(?:\.|$|\n)",
        r"remind me (?:to .+? )?(.+?)(?:\.|$|\n)",
        r"reminder.+?for (.+?)(?:\.|$|\n)", 
        r"reminder.+?at (.+?)(?:\.|$|\n)",
        r"follow.?up.+?on (.+?)(?:\.|$|\n)",
        r"(?:schedule|set).+?(?:for|at) (.+?)(?:\.|$|\n)"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw_phrase = match.group(1).strip()
            logger.info(f"Found raw reminder phrase: {raw_phrase}")
            
            try:
                # Try to parse the time with relaxed settings
                parsed = dateparser.parse(
                    raw_phrase, 
                    settings={
                        "PREFER_DATES_FROM": "future", 
                        "STRICT_PARSING": False,
                        "RELATIVE_BASE": datetime.now()
                    }
                )
                
                if parsed:
                    delta = (parsed - datetime.now()).total_seconds()
                    logger.info(f"Parsed reminder time: {parsed} (in {int(delta)}s)")
                    
                    # Accept any time in the future, but warn if it's very soon or far away
                    if delta > 0:
                        if delta < 60:
                            logger.warning(f"Reminder time is very soon: {delta} seconds")
                        elif delta > 31536000:  # More than a year
                            logger.warning(f"Reminder time is very far: {delta/86400:.1f} days")
                        return parsed
                    else:
                        logger.warning(f"Parsed time is in the past: {parsed}")
            except Exception as e:
                logger.error(f"Error parsing time '{raw_phrase}': {e}")
                continue  # Try the next pattern
    
    # Try a more generic approach if specific patterns failed
    try:
        # Look for any time-related words and try to parse them
        time_indicators = ["today", "tomorrow", "next", "later", "evening", "morning", 
                           "afternoon", "night", "week", "month", "hour", "minute", "am", "pm"]
        
        words = text.lower().split()
        for i, word in enumerate(words):
            if any(indicator in word for indicator in time_indicators):
                # Try to parse a phrase starting from this word
                start_idx = max(0, i-2)  # Include a couple words before
                end_idx = min(len(words), i+5)  # And several after
                phrase = " ".join(words[start_idx:end_idx])
                
                parsed = dateparser.parse(
                    phrase, 
                    settings={
                        "PREFER_DATES_FROM": "future", 
                        "STRICT_PARSING": False,
                        "RELATIVE_BASE": datetime.now()
                    }
                )
                
                if parsed:
                    delta = (parsed - datetime.now()).total_seconds()
                    if delta > 0:
                        logger.info(f"Found time using generic approach: {parsed} (in {int(delta)}s)")
                        return parsed
    except Exception as e:
        logger.error(f"Error in generic time parsing: {e}")
    
    # If we reach here, no valid time was found
    logger.warning("No valid reminder time found in text.")
    return None

def create_reminder(email_obj: Dict, tags: Optional[List[str]] = None) -> Optional[str]:
    """
    Create a new reminder based on an email.
    
    Args:
        email_obj: Dict containing email information (sender, subject, body)
        tags: Optional list of tags to categorize the reminder
        
    Returns:
        str: ID of the created reminder, or None if creation failed
    """
    logger.info("🔍 Running reminder check...")
    
    if not email_obj or "body" not in email_obj:
        logger.error("Invalid email object provided")
        return None
        
    due_time = extract_reminder_time(email_obj["body"])
    if not due_time:
        logger.warning("⚠️ Skipping reminder creation: No valid time parsed.")
        return None
        
    logger.info(f"📝 Creating reminder due at: {due_time}")
    
    try:
        # Prepare reminder data
        reminder_data = {
            "title": email_obj.get("subject", "Follow-up requested"),
            "body": email_obj["body"],
            "sender": email_obj["sender"],
            "due": due_time.isoformat(),
            "status": "pending",
            "created_at": firestore.SERVER_TIMESTAMP,
            "thread_id": email_obj.get("thread_id")
        }
        
        # Add tags if provided
        if tags:
            reminder_data["tags"] = tags
            
        # Add to Firestore
        doc_ref = db.collection("reminders").document()
        doc_ref.set(reminder_data)
        reminder_id = doc_ref.id
        
        logger.info(f"✅ Reminder added to Firestore: ID = {reminder_id}")
        
        # Schedule the reminder
        schedule_reminder(reminder_id, due_time, email_obj)
        
        return reminder_id
    except Exception as e:
        logger.error(f"❌ Firestore reminder insert failed: {e}")
        return None

def schedule_reminder(reminder_id: str, due_time: datetime, email_obj: Dict) -> None:
    """
    Schedule an in-memory reminder using threading.Timer.
    
    Args:
        reminder_id: The ID of the reminder to schedule
        due_time: When the reminder should trigger
        email_obj: Email information for sending the reminder
    """
    delay = (due_time - datetime.now()).total_seconds()
    
    if delay <= 0:
        logger.warning(f"Reminder {reminder_id} due time is in the past, executing immediately")
        send_reminder(reminder_id, email_obj)
    else:
        logger.info(f"Scheduling in-memory reminder {reminder_id} in {int(delay)} seconds")
        # Create and start a timer thread to execute the reminder
        timer = threading.Timer(delay, send_reminder, args=[reminder_id, email_obj])
        timer.daemon = True  # Allow the timer to be terminated when the program exits
        timer.start()

def send_reminder(reminder_id: str, email_obj: Dict) -> None:
    """
    Send a follow-up email for a reminder and mark it as completed.
    
    Args:
        reminder_id: The ID of the reminder to send
        email_obj: Email information for sending the reminder
    """
    logger.info(f"Executing reminder with ID: {reminder_id}")
    
    # Fetch the latest reminder data from Firestore
    try:
        # Use a transaction to prevent race conditions and duplicate sends
        transaction = db.transaction()
        
        @firestore.transactional
        def update_reminder_in_transaction(transaction, reminder_id):
            reminder_ref = db.collection("reminders").document(reminder_id)
            reminder_doc = reminder_ref.get(transaction=transaction)
            
            if not reminder_doc.exists:
                logger.warning(f"Reminder {reminder_id} no longer exists")
                return False
                
            reminder_data = reminder_doc.to_dict()
            
            # Check if reminder is already completed or in progress
            if reminder_data.get("status") != "pending":
                logger.warning(f"Reminder {reminder_id} is already marked as {reminder_data.get('status')}")
                return False
            
            # Mark the reminder as "in_progress" to prevent duplicate sends
            transaction.update(reminder_ref, {
                "status": "in_progress",
                "processing_started_at": firestore.SERVER_TIMESTAMP
            })
            
            return reminder_data
        
        # Execute the transaction to mark the reminder as in progress
        reminder_data = update_reminder_in_transaction(transaction, reminder_id)
        
        # If the transaction returned False, exit early (reminder was already processed)
        if reminder_data is False:
            return
            
        # Prepare and send the reminder email
        subject = f"🔔 Reminder: {reminder_data.get('title', 'Follow-up')}"
        
        # Get the original email subject
        original_subject = reminder_data.get("title", "your previous message")
        
        # Create a nicer email body
        body = f"""
You asked me to remind you about: "{reminder_data.get('title', 'your reminder')}".

This is from your email with subject: "{original_subject}"

Original message:
---
{reminder_data.get('body', email_obj.get('body', 'No content'))}
---

Let me know if you need any follow-up actions.

– Mano
"""
        
        # Send as HTML email for better formatting
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_USER
        recipient = reminder_data.get("sender", email_obj.get("sender"))
        msg["To"] = recipient
        
        # Plain text version
        plain_text = body
        msg.attach(MIMEText(plain_text, "plain"))
        
        # HTML version
        html_body = f"""
        <html>
          <head>
            <style>
              body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
              .reminder-title {{ font-weight: bold; color: #0066cc; }}
              .original-message {{ margin-top: 15px; padding: 10px; background-color: #f9f9f9; border-left: 4px solid #ddd; }}
              .signature {{ margin-top: 20px; color: #666; }}
            </style>
          </head>
          <body>
            <p>You asked me to remind you about: <span class="reminder-title">"{reminder_data.get('title', 'your reminder')}"</span>.</p>
            <p>This is from your email with subject: "{original_subject}"</p>
            <div class="original-message">
              <p><strong>Original message:</strong></p>
              <p>{reminder_data.get('body', email_obj.get('body', 'No content'))}</p>
            </div>
            <p>Let me know if you need any follow-up actions.</p>
            <p class="signature">– Mano</p>
          </body>
        </html>
        """
        msg.attach(MIMEText(html_body, "html"))
        
        # Send the email
        try:
            import smtplib
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(EMAIL_USER, EMAIL_PASS)
                server.sendmail(EMAIL_USER, [recipient], msg.as_string())
            logger.info(f"Reminder email sent to {recipient}")
        except Exception as e:
            logger.error(f"Failed to send reminder email: {e}")
            # Update reminder status to reflect the error
            db.collection("reminders").document(reminder_id).update({
                "status": "error",
                "error": f"Email sending failed: {str(e)}",
                "error_at": firestore.SERVER_TIMESTAMP
            })
            return
        
        # Update the reminder status to "done" in Firestore
        db.collection("reminders").document(reminder_id).update({
            "status": "done",
            "completed_at": firestore.SERVER_TIMESTAMP
        })
        
        # Add a record to the reminder history
        db.collection("reminder_history").add({
            "reminder_id": reminder_id,
            "title": reminder_data.get("title", "Follow-up"),
            "sender": recipient,
            "status": "completed",
            "original_due": reminder_data.get("due"),
            "completed_at": firestore.SERVER_TIMESTAMP
        })
        
        logger.info(f"Reminder {reminder_id} completed and marked as done")
    except Exception as e:
        logger.error(f"Failed to process reminder {reminder_id}: {e}")
        
        # If there was an error during processing, try to revert the status back to pending
        try:
            db.collection("reminders").document(reminder_id).update({
                "status": "pending",
                "error": str(e),
                "last_error_at": firestore.SERVER_TIMESTAMP
            })
        except Exception as ex:
            logger.error(f"Failed to update reminder status after error: {ex}")

def reminder_checker_loop() -> None:
    """
    Main loop for checking and processing due reminders.
    This should be run in a separate thread.
    """
    logger.info("Starting reminder checker loop")
    
    while True:
        try:
            # Get current time
            now = datetime.now()
            
            # Query Firestore for pending reminders that are due
            reminders = db.collection("reminders")\
                .where("status", "==", "pending")\
                .stream()
            
            # Count how many reminders we'll process
            processed_count = 0
            
            # Process each reminder
            for reminder in reminders:
                reminder_id = reminder.id
                data = reminder.to_dict()
                
                # Check if the reminder has a due time
                due_str = data.get("due")
                if not due_str:
                    logger.warning(f"Reminder {reminder_id} has no due date")
                    continue
                
                # Parse the due time
                try:
                    due_time = datetime.fromisoformat(due_str)
                except ValueError:
                    logger.warning(f"Invalid due time format for reminder {reminder_id}: {due_str}")
                    continue
                
                # Check if the reminder is due
                if due_time <= now:
                    logger.info(f"Processing due reminder {reminder_id}: {data.get('title')}")
                    processed_count += 1
                    
                    # Prepare the email object for sending
                    email_obj = {
                        "sender": data.get("sender"),
                        "subject": data.get("subject", "Follow-up"),
                        "body": data.get("body", "No content"),
                        "thread_id": data.get("thread_id")
                    }
                    
                    # Send the reminder
                    send_reminder(reminder_id, email_obj)
            
            if processed_count > 0:
                logger.info(f"Processed {processed_count} due reminders")
                
        except Exception as e:
            logger.error(f"Error in reminder checker loop: {e}")
        
        # Sleep for a short interval before checking again
        time.sleep(60)  # Check every minute

def list_active_reminders(email: Optional[str] = None) -> List[Dict]:
    """
    List all active reminders, optionally filtered by sender email.
    
    Args:
        email: Optional email to filter by
        
    Returns:
        List of reminder dictionaries
    """
    try:
        query = db.collection("reminders").where("status", "==", "pending")
        
        if email:
            query = query.where("sender", "==", email)
            
        reminders = query.stream()
        
        result = []
        for reminder in reminders:
            data = reminder.to_dict()
            due_time = None
            if data.get("due"):
                try:
                    due_time = datetime.fromisoformat(data["due"])
                    time_until = (due_time - datetime.now()).total_seconds()
                    # Format as human-readable time
                    if time_until < 0:
                        time_str = "Overdue"
                    elif time_until < 60:
                        time_str = "Less than a minute"
                    elif time_until < 3600:
                        time_str = f"{int(time_until/60)} minutes"
                    elif time_until < 86400:
                        time_str = f"{int(time_until/3600)} hours"
                    else:
                        time_str = f"{int(time_until/86400)} days"
                except ValueError:
                    time_str = "Unknown"
            else:
                time_str = "No due date"
                
            result.append({
                "id": reminder.id,
                "title": data.get("title", "Untitled"),
                "due": data.get("due"),
                "time_until": time_str,
                "sender": data.get("sender"),
                "created_at": data.get("created_at")
            })
            
        return result
    except Exception as e:
        logger.error(f"Failed to list active reminders: {e}")
        return []

def cancel_reminder(reminder_id: str) -> bool:
    """
    Cancel a pending reminder.
    
    Args:
        reminder_id: The ID of the reminder to cancel
        
    Returns:
        bool: True if cancelled successfully, False otherwise
    """
    try:
        reminder_ref = db.collection("reminders").document(reminder_id)
        reminder = reminder_ref.get()
        
        if not reminder.exists:
            logger.warning(f"Reminder {reminder_id} not found")
            return False
            
        reminder_data = reminder.to_dict()
        
        if reminder_data.get("status") != "pending":
            logger.warning(f"Cannot cancel reminder {reminder_id}, status is {reminder_data.get('status')}")
            return False
            
        # Update reminder status
        reminder_ref.update({
            "status": "cancelled",
            "cancelled_at": firestore.SERVER_TIMESTAMP
        })
        
        # Add to history
        db.collection("reminder_history").add({
            "reminder_id": reminder_id,
            "title": reminder_data.get("title", "Untitled"),
            "sender": reminder_data.get("sender"),
            "status": "cancelled",
            "original_due": reminder_data.get("due"),
            "cancelled_at": firestore.SERVER_TIMESTAMP
        })
        
        logger.info(f"Reminder {reminder_id} cancelled")
        return True
    except Exception as e:
        logger.error(f"Failed to cancel reminder {reminder_id}: {e}")
        return False

def reschedule_reminder(reminder_id: str, new_due_time: Union[str, datetime]) -> bool:
    """
    Reschedule a pending reminder to a new time.
    
    Args:
        reminder_id: The ID of the reminder to reschedule
        new_due_time: New due time (datetime object or ISO format string)
        
    Returns:
        bool: True if rescheduled successfully, False otherwise
    """
    try:
        # Convert string to datetime if needed
        if isinstance(new_due_time, str):
            try:
                new_due_time = datetime.fromisoformat(new_due_time)
            except ValueError:
                logger.error(f"Invalid due time format: {new_due_time}")
                return False
        
        reminder_ref = db.collection("reminders").document(reminder_id)
        reminder = reminder_ref.get()
        
        if not reminder.exists:
            logger.warning(f"Reminder {reminder_id} not found")
            return False
            
        reminder_data = reminder.to_dict()
        
        if reminder_data.get("status") != "pending":
            logger.warning(f"Cannot reschedule reminder {reminder_id}, status is {reminder_data.get('status')}")
            return False
            
        # Update reminder due time
        reminder_ref.update({
            "due": new_due_time.isoformat(),
            "rescheduled_at": firestore.SERVER_TIMESTAMP,
            "original_due": reminder_data.get("due")  # Track original due time
        })
        
        # Add to history
        db.collection("reminder_history").add({
            "reminder_id": reminder_id,
            "title": reminder_data.get("title", "Untitled"),
            "sender": reminder_data.get("sender"),
            "status": "rescheduled",
            "original_due": reminder_data.get("due"),
            "new_due": new_due_time.isoformat(),
            "rescheduled_at": firestore.SERVER_TIMESTAMP
        })
        
        logger.info(f"Reminder {reminder_id} rescheduled to {new_due_time.isoformat()}")
        
        # Re-schedule in memory if needed
        email_obj = {
            "sender": reminder_data.get("sender"),
            "subject": reminder_data.get("title", "Follow-up"),
            "body": reminder_data.get("body", "No content"),
            "thread_id": reminder_data.get("thread_id")
        }
        schedule_reminder(reminder_id, new_due_time, email_obj)
        
        return True
    except Exception as e:
        logger.error(f"Failed to reschedule reminder {reminder_id}: {e}")
        return False

def get_reminder_statistics() -> Dict:
    """
    Get statistics about reminder usage.
    
    Returns:
        Dict containing reminder statistics
    """
    try:
        # Get all reminder history
        history = db.collection("reminder_history").stream()
        
        # Initialize counters
        total_reminders = 0
        completed = 0
        cancelled = 0
        rescheduled = 0
        by_user = {}
        
        for item in history:
            data = item.to_dict()
            total_reminders += 1
            
            status = data.get("status")
            if status == "completed":
                completed += 1
            elif status == "cancelled":
                cancelled += 1
            elif status == "rescheduled":
                rescheduled += 1
                
            # Track by user
            sender = data.get("sender")
            if sender:
                if sender not in by_user:
                    by_user[sender] = {"total": 0, "completed": 0}
                by_user[sender]["total"] += 1
                if status == "completed":
                    by_user[sender]["completed"] += 1
        
        # Calculate completion rates
        overall_completion_rate = (completed / total_reminders * 100) if total_reminders > 0 else 0
        
        for user, stats in by_user.items():
            stats["completion_rate"] = (stats["completed"] / stats["total"] * 100) if stats["total"] > 0 else 0
        
        return {
            "total_reminders": total_reminders,
            "completed": completed,
            "cancelled": cancelled,
            "rescheduled": rescheduled,
            "overall_completion_rate": overall_completion_rate,
            "by_user": by_user
        }
    except Exception as e:
        logger.error(f"Failed to get reminder statistics: {e}")
        return {
            "error": str(e)
        }

def start_background_services() -> None:
    """Start the background services for reminder checking."""
    # Check if needed environment variables are set
    if not EMAIL_USER or not EMAIL_PASS:
        logger.error("Email credentials missing. Reminder service can't send notifications.")
    
    reminder_thread = threading.Thread(target=reminder_checker_loop)
    reminder_thread.daemon = True
    reminder_thread.start()
    logger.info("Background reminder service started")
    
    # Log startup status to database
    try:
        db.collection("system_status").document("reminder_service").set({
            "status": "running",
            "started_at": firestore.SERVER_TIMESTAMP,
            "hostname": os.getenv("HOSTNAME", "unknown"),
            "version": "2.0.0"  # Add version tracking
        })
    except Exception as e:
        logger.error(f"Failed to record reminder service status: {e}")

# Entry point for standalone testing
if __name__ == "__main__":
    # Test reminder creation
    test_email = {
        "sender": "test@example.com",
        "subject": "Test Reminder",
        "body": "Please remind me to follow up with John about the project tomorrow at 2pm.",
        "thread_id": "test-thread-123"
    }
    
    logger.info("Starting reminder system test...")
    
    # Create a test reminder
    reminder_id = create_reminder(test_email)
    
    if reminder_id:
        logger.info(f"Test reminder created with ID: {reminder_id}")
        
        # Start the reminder service
        start_background_services()
        
        # Keep the script running to allow the background service to process reminders
        try:
            logger.info("Press Ctrl+C to exit...")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Exiting...")
    else:
        logger.error("Failed to create test reminder!")