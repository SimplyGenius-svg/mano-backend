import os
import re
import smtplib
import threading
import time
from datetime import datetime
import dateparser
from dotenv import load_dotenv
from firebase import db
from firebase_admin import firestore
from gpt_helpers import chat_with_gpt
from memory_logger import save_memory
from sentience_engine import process_email_for_memory
from email.mime.text import MIMEText

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

PARTNER_VOICE = """
You are responding to a VC partner who is sharp, inquisitive, and concise.
Keep your tone helpful, professional, and clear — always be one step ahead.
Use short, structured responses. Never guess. Always summarize with action steps.
"""

# --- Email Sending ---
def send_email_reply(to_email, subject, reply_text):
    msg = MIMEText(reply_text)
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, [to_email], msg.as_string())
        print(f"✅ Reply sent to {to_email}")
    except Exception as e:
        print(f"❌ Email failed: {e}")

# --- Intent Classification ---
def classify_partner_intent(body):
    prompt = f"""
Classify the following VC partner message using relevant tags. Use short, lowercase tags separated by commas.
Possible tags: ask, note, reminder, follow_up, IC_prep, infra, founder, backlog

Message:
---
{body}
---
Tags:
"""
    try:
        raw = chat_with_gpt(prompt)
        return [tag.strip() for tag in raw.lower().split(",") if tag.strip()]
    except Exception as e:
        print(f"❌ GPT tag error: {e}")
        return []

# --- Reminder Handling ---
def extract_reminder_time(text):
    """Extract a time specification from a reminder request in text."""
    match = re.search(r"remind me (.+?)(\.|$|\n)", text, re.IGNORECASE)
    if match:
        raw_phrase = match.group(1).strip()
        print(f"📌 Found raw reminder phrase: {raw_phrase}")
        
        # Split on known lead-in phrases like "to", "that", etc.
        trimmed = re.sub(r"^(to|that|for|about)\s+", "", raw_phrase, flags=re.IGNORECASE).strip()
        print(f"🔍 Trimmed for parsing: {trimmed}")
        
        # Parse the time phrase
        parsed = None
        try:
            # Try to extract the "time" part using regex
            time_match = re.search(r"\b(in|at|on|by|before|after|next)\b.*", trimmed, re.IGNORECASE)
            if time_match:
                time_text = time_match.group(0).strip()
                print(f"⏱️ Extracted time text: {time_text}")
            else:
                time_text = trimmed  # fallback if no match

            # Now parse ONLY the time text
            parsed = dateparser.parse(time_text, settings={"PREFER_DATES_FROM": "future", "STRICT_PARSING": True})

        except Exception as e:
            print(f"❌ Error parsing time: {e}")
            
        if parsed:
            delta = (parsed - datetime.now()).total_seconds()
            print(f"⏱️ Parsed reminder time: {parsed} (in {int(delta)}s)")
            # Only accept reminders between 30 seconds and 7 days in the future
            if 30 <= delta <= 604800:
                return parsed
            else:
                print("⚠️ Parsed time outside expected range (30s to 7 days).")
        else:
            print("❌ dateparser couldn't parse trimmed phrase.")
    else:
        print("⚠️ No 'remind me' phrase matched.")
    return None

def create_reminder(email_obj):
    """Create a reminder in Firestore from an email object."""
    due_time = extract_reminder_time(email_obj["body"])
    if not due_time:
        print("⚠️ No valid reminder time found in message.")
        return None
        
    try:
        # Create the reminder document in Firestore
        reminder_data = {
            "title": email_obj.get("subject", "Follow-up requested"),
            "body": email_obj["body"],
            "sender": email_obj["sender"],
            "due": due_time.isoformat(),
            "status": "pending",
            "created_at": firestore.SERVER_TIMESTAMP
        }
        
        # Add document to Firestore and get the document reference
        doc_ref = db.collection("reminders").add(reminder_data)
        reminder_id = doc_ref[1].id
        
        print(f"✅ Reminder created in Firestore with ID: {reminder_id}")
        
        # Schedule the in-memory reminder for execution
        # schedule_reminder(reminder_id, due_time, email_obj)
        
        return reminder_id
    except Exception as e:
        print(f"❌ Failed to create reminder: {e}")
        return None

def schedule_reminder(reminder_id, due_time, email_obj):
    """Schedule an in-memory reminder using threading.Timer."""
    delay = (due_time - datetime.now()).total_seconds()
    
    if delay <= 0:
        print("⚠️ Reminder due time is in the past, executing immediately")
        send_reminder(reminder_id, email_obj)
    else:
        print(f"🧠 Scheduling in-memory reminder in {int(delay)} seconds")
        # Create and start a timer thread to execute the reminder
        timer = threading.Timer(delay, send_reminder, args=[reminder_id, email_obj])
        timer.daemon = True  # Allow the timer to be terminated when the program exits
        timer.start()

def send_reminder(reminder_id, email_obj):
    print(f"🔔 Executing reminder with ID: {reminder_id}")
    
    try:
        reminder_doc = db.collection("reminders").document(reminder_id).get()
        if not reminder_doc.exists:
            print(f"⚠️ Reminder {reminder_id} no longer exists")
            return

        reminder_data = reminder_doc.to_dict()

        if reminder_data.get("status") != "pending":
            print(f"⚠️ Reminder {reminder_id} is already marked as {reminder_data.get('status')}")
            return
        
        # 🔥 Immediately mark as done BEFORE sending email
        db.collection("reminders").document(reminder_id).update({
            "status": "done",
            "completed_at": firestore.SERVER_TIMESTAMP
        })
        
        subject = f"🔔 Follow-up Reminder: {reminder_data.get('title', 'No Subject')}"
        body = f"This is your reminder to revisit:\n\n{reminder_data.get('body', email_obj.get('body', 'No content'))}\n\n– Mano"
        recipient = reminder_data.get("sender", email_obj.get("sender"))

        send_email_reply(recipient, subject, body)
        
        print(f"✅ Reminder {reminder_id} completed and marked as done")
    except Exception as e:
        print(f"❌ Failed to process reminder {reminder_id}: {e}")

# --- Thread Fetching ---
def get_recent_thread(sender):
    try:
        docs = db.collection("partner_memory")\
            .where("sender", "==", sender)\
            .order_by("timestamp", direction=firestore.Query.DESCENDING)\
            .limit(10)\
            .stream()
        return "\n\n---\n\n".join([
            f"{doc.to_dict().get('subject', '')}\n{doc.to_dict().get('body', '')}"
            for doc in docs
        ])
    except Exception as e:
        print(f"❌ Thread fetch failed: {e}")
        return ""

# --- Sentiment Analysis ---
def analyze_sentiment(text):
    prompt = f"""
Analyze the sentiment of the following message. Reply with one word: positive, neutral, or negative.
---
{text}
---
"""
    try:
        raw = chat_with_gpt(prompt)
        return raw.strip().lower()
    except Exception as e:
        print(f"❌ Sentiment analysis failed: {e}")
        return "neutral"

# --- Action Item Extraction ---
def extract_action_items(text):
    prompt = f"""
List action items from this message as bullet points.
---
{text}
---
Tasks:
"""
    try:
        raw = chat_with_gpt(prompt)
        return [line.strip('- ').strip() for line in raw.splitlines() if line.startswith('-')]
    except Exception as e:
        print(f"❌ Action extraction failed: {e}")
        return []

# --- Priority Score ---
def compute_priority(tags, sentiment, body):
    score = 0
    if "ask" in tags: score += 2
    if "reminder" in tags: score += 1.5
    if sentiment == "negative": score += 1
    if re.search(r"\b(asap|urgent|priority)\b", body, re.IGNORECASE):
        score += 2
    return score

# --- Handle Partner Email ---
def handle_partner_email(email_obj):
    start = datetime.utcnow()
    sender = email_obj["sender"]
    subject = email_obj.get("subject", "")
    body = email_obj["body"]
    
    print(f"📥 Handling new partner email from {sender}")
    
    # Process the email content
    tags = classify_partner_intent(body)
    sentiment = analyze_sentiment(body)
    action_items = extract_action_items(body)
    priority_score = compute_priority(tags, sentiment, body)
    thread_context = get_recent_thread(sender)
    
    # Save to partner memory
    try:
        memory_type = "reminder" if "reminder" in tags else "note"
        save_memory(
            sender_email=sender,
            subject=subject,
            body=body,
            tags=tags,
            memory_type=memory_type
        )
    except Exception as e:
        print(f"❌ Memory save failed: {e}")
    
    # Check if this is a reminder request
    if "reminder" in tags:
        reminder_id = create_reminder(email_obj)
        if reminder_id:
            print(f"📅 Reminder created and scheduled: {reminder_id}")
    
    # Generate a reply if this is a question or follow-up
    if "ask" in tags or "follow_up" in tags:
        action_items_str = "- " + "\n- ".join(action_items) if action_items else "None"
        
        prompt = f"""
You are Mano, the intelligent VC chief of staff.

Latest partner message:
---
{body}
---

Thread context:
---
{thread_context}
---

Action items extracted:
{action_items_str}

Respond clearly, formally, and always suggest next steps.
{PARTNER_VOICE}
"""
        reply = chat_with_gpt(prompt)
        send_email_reply(sender, subject, reply)
    
    # Record metrics about this interaction
    elapsed = (datetime.utcnow() - start).total_seconds()
    record_partner_metrics(sender, elapsed, priority_score)
    
    return "Email processed successfully"

# --- Metrics ---
def record_partner_metrics(sender, response_time, priority):
    try:
        db.collection("partner_metrics").add({
            "sender": sender,
            "response_time_sec": response_time,
            "priority_score": priority,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        print(f"📈 Partner metrics recorded.")
    except Exception as e:
        print(f"❌ Metrics recording failed: {e}")

# --- Reminder Checking (Background Service) ---
def reminder_checker_loop():
    """
    Main loop for checking and processing due reminders.
    This should be run in a separate thread.
    """
    print("🔄 Starting reminder checker loop")
    
    while True:
        try:
            # Get current time
            now = datetime.utcnow()
            print(f"🕒 Checking for due reminders at {now.isoformat()}")
            
            # Query Firestore for pending reminders
            reminders = db.collection("reminders")\
                .where("status", "==", "pending")\
                .stream()
            
            # Process each reminder
            for reminder in reminders:
                reminder_id = reminder.id
                data = reminder.to_dict()
                
                # Check if the reminder has a due time
                due_str = data.get("due")
                if not due_str:
                    print(f"⚠️ Reminder {reminder_id} has no due date")
                    continue
                
                # Parse the due time
                try:
                    due_time = datetime.fromisoformat(due_str)
                except ValueError:
                    print(f"⚠️ Invalid due time format for reminder {reminder_id}: {due_str}")
                    continue
                
                # Check if the reminder is due
                if due_time <= now:
                    print(f"🔔 Processing due reminder {reminder_id}: {data.get('title')}")
                    
                    # Prepare the email object for sending
                    email_obj = {
                        "sender": data.get("sender"),
                        "subject": data.get("title", "Follow-up"),
                        "body": data.get("body", "No content")
                    }
                    
                    # Send the reminder
                    send_reminder(reminder_id, email_obj)
            
        except Exception as e:
            print(f"❌ Error in reminder checker loop: {e}")
        
        # Sleep for a short interval before checking again
        time.sleep(60)  # Check every minute

# --- Initialize Background Services ---
def start_background_services():
    """Start the background services for reminder checking."""
    reminder_thread = threading.Thread(target=reminder_checker_loop)
    reminder_thread.daemon = True
    reminder_thread.start()
    print("✅ Background reminder service started")

