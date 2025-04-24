import os
import re
import smtplib
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
from firebase import db
from firebase_admin import firestore
from gpt_helpers import chat_with_gpt
from email.mime.text import MIMEText
import dateparser

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

PARTNER_VOICE = """
You are responding to a VC partner who is sharp, inquisitive, and concise.
Keep your tone helpful, professional, and clear — always be one step ahead.
Use short, structured responses. Never guess. Always summarize with action steps.
"""

# 🧠 Classify partner intent with GPT
def classify_partner_intent(email_body):
    prompt = f"""
Classify the following VC partner message using relevant tags. Use short, lowercase tags separated by commas.
Possible tags: ask, note, reminder, follow_up, IC_prep, infra, founder, backlog

Message:
---
{email_body}
---
Tags:
"""
    try:
        raw = chat_with_gpt(prompt)
        return [tag.strip() for tag in raw.lower().split(",") if tag.strip()]
    except Exception as e:
        print(f"❌ GPT tag error: {e}")
        return []

# 📅 Extract natural language time like “in 1 minute”
def extract_reminder_time(text):
    match = re.search(r"remind me (.+?)(\.|$|\n)", text, re.IGNORECASE)
    if match:
        raw_phrase = match.group(1).strip()
        print(f"📌 Found raw reminder phrase: {raw_phrase}")

        # ✅ Split on known lead-in phrases like "to", "that", etc.
        trimmed = re.split(r"\b(to|that|for|about)\b", raw_phrase, maxsplit=1)[0].strip()
        print(f"🔍 Trimmed for parsing: {trimmed}")

        parsed = dateparser.parse(trimmed, settings={"PREFER_DATES_FROM": "future"})
        if parsed:
            delta = (parsed - datetime.now()).total_seconds()
            print(f"⏱️ Parsed reminder time: {parsed} (in {int(delta)}s)")
            if 30 <= delta <= 604800:
                return parsed
            else:
                print("⚠️ Parsed time outside expected range.")
        else:
            print("❌ dateparser couldn't parse trimmed phrase.")
    else:
        print("⚠️ No 'remind me' phrase matched.")
    return None



# 🧠 Store message to Firestore
def store_partner_message(email_obj, tags):
    try:
        doc_id = f"{email_obj['sender'].replace('.', '_').replace('@', '__')}_{email_obj['id']}"
        db.collection("partner_memory").document(doc_id).set({
            "email": email_obj["sender"],
            "subject": email_obj.get("subject", ""),
            "body": email_obj.get("body", ""),
            "timestamp": firestore.SERVER_TIMESTAMP,
            "tags": tags,
            "type": "ask" if "ask" in tags or "reminder" in tags else "note"
        })
    except Exception as e:
        print(f"❌ Firestore write failed: {e}")

# 🔔 Create and schedule reminder
def create_reminder_if_needed(email_obj, tags):
    print("🔍 Running reminder check...")
    due_time = extract_reminder_time(email_obj["body"])
    if due_time:
        print(f"📝 Creating reminder due at: {due_time}")
        try:
            doc_ref = db.collection("reminders").add({
                "title": email_obj["subject"] or "Follow-up requested",
                "body": email_obj["body"],
                "sender": email_obj["sender"],
                "due": due_time.isoformat(),
                "status": "pending",
                "created_at": firestore.SERVER_TIMESTAMP
            })
            print(f"✅ Reminder added to Firestore: ID = {doc_ref[1].id}")
            schedule_in_memory_reminder(doc_ref[1].id, due_time, email_obj)
        except Exception as e:
            print(f"❌ Firestore reminder insert failed: {e}")
    else:
        print("⚠️ Skipping reminder creation: No valid time parsed.")


# 🔁 Set follow-up in memory with threading.Timer
def schedule_in_memory_reminder(reminder_id, due_time, email_obj):
    delay = (due_time - datetime.now()).total_seconds()
    if delay > 0:
        print(f"🧠 Scheduling in-memory follow-up in {int(delay)} seconds")
        threading.Timer(delay, send_follow_up_email, args=(reminder_id, email_obj)).start()

# 📨 Fire off reminder
def send_follow_up_email(reminder_id, email_obj):
    subject = f"🔔 Follow-up Reminder: {email_obj['subject']}"
    body = f"This is your reminder to revisit:\n\n{email_obj['body']}\n\n– Mano"
    send_email_reply(email_obj["sender"], subject, body)
    try:
        db.collection("reminders").document(reminder_id).update({
            "status": "done",
            "completed_at": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        print(f"❌ Failed to update reminder status: {e}")

# ✉️ Send reply email
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

# 🔁 Called by agent.py
def handle_partner_email(email_obj):
    body = email_obj["body"]
    sender = email_obj["sender"]
    subject = email_obj["subject"]

    print(f"📥 Partner message from {sender}")
    tags = classify_partner_intent(body)
    store_partner_message(email_obj, tags)
    create_reminder_if_needed(email_obj, tags)

    thread_context = get_recent_thread(sender)

    # Compose GPT reply
    prompt = f"""
You are an intelligent VC chief of staff named Mano.

Latest partner message:
---
{body}
---

Recent context:
---
{thread_context}
---

Respond in a clear, concise, and helpful tone. Match partner style.
{PARTNER_VOICE}
"""
    return chat_with_gpt(prompt)

# 🧵 Fetch last 10 messages from this partner
def get_recent_thread(sender):
    try:
        thread_docs = (
            db.collection("partner_memory")
            .where("email", "==", sender)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(10)
            .stream()
        )
        return "\n\n---\n\n".join([
            f"{doc.to_dict().get('subject', '')}\n{doc.to_dict().get('body', '')}"
            for doc in thread_docs
        ])
    except Exception as e:
        print(f"❌ Thread fetch failed: {e}")
        return ""

# ⏰ Check due reminders on each loop
def check_due_reminders():
    now = datetime.utcnow().isoformat()
    reminders = db.collection("reminders").where("status", "==", "pending").stream()

    for r in reminders:
        data = r.to_dict()
        due = data.get("due", "")
        if due and due <= now:
            print(f"🔔 Triggering scheduled reminder: {data.get('title')}")
            send_follow_up_email(r.id, data)

# --------------------------------------
# Enhancement 1: Sentiment & Tone Tracking
# --------------------------------------
def analyze_sentiment(text: str) -> str:
    prompt = f"""
Analyze the sentiment and tone of the following message. Reply with one word: positive, neutral, or negative.
Message:
---
{text}
---
Response:
"""
    raw = chat_with_gpt(prompt)
    return raw.strip().lower()

# --------------------------------------
# Enhancement 2: Action-Item Extraction & Task Automation
# --------------------------------------
def extract_action_items(text: str) -> list[str]:
    prompt = f"""
Extract any actionable tasks from this message as a bullet list. Only list tasks.
Message:
---
{text}
---
Tasks:
"""
    raw = chat_with_gpt(prompt)
    return [line.strip('- ').strip() for line in raw.splitlines() if line.startswith('-')]

# --------------------------------------
# Enhancement 3: Priority Scoring & Urgency Flags
# --------------------------------------
def compute_priority_score(tags: list[str], sentiment: str, text: str) -> float:
    score = 0
    # Base weight on tags
    if "ask" in tags: score += 2
    if "reminder" in tags: score += 1.5
    if "infra" in tags: score += 1
    # Sentiment weight
    if sentiment == 'negative': score += 1
    # Keyword urgency
    if re.search(r"\b(asap|urgent|priority)\b", text, re.IGNORECASE):
        score += 2
    return score

# --------------------------------------
# Enhancement 4: Calendar & Meeting-Slot Integration
# --------------------------------------
def propose_meeting_slots(text: str) -> list[str]:
    """
Stub: parse proposed dates and return available slots based on your calendar API.
"""
    prompt = f"""
Identify any meeting requests in this message and propose three possible time slots based on a typical US PST workday (9am-5pm). Return as bullet list.
Message:
---
{text}
---
Slots:
"""
    raw = chat_with_gpt(prompt)
    return [line.strip('- ').strip() for line in raw.splitlines() if line.startswith('-')]

# --------------------------------------
# Enhancement 5: Weekly Partner Digest
# --------------------------------------
def compile_weekly_digest() -> str:
    """
Fetch all partner_memory entries from the last 7 days and summarize key points.
"""
    one_week_ago = datetime.utcnow() - timedelta(days=7)
    docs = db.collection("partner_memory")\
        .where("timestamp", ">=", one_week_ago)\
        .stream()
    entries = []
    for doc in docs:
        data = doc.to_dict()
        entries.append(f"- [{data['sender']}] {data['subject']}: {data['tags']}")
    summary = "\n".join(entries)
    return f"Weekly Partner Digest (last 7 days):\n{summary}"

# --------------------------------------
# Enhancement 6: Thread Summarization
# --------------------------------------
def summarize_thread(sender: str) -> str:
    context = get_recent_thread(sender)
    prompt = f"""
Summarize the following email thread in one concise paragraph. Focus on decisions made and open questions.
Thread:
---
{context}
---
Summary:
"""
    return chat_with_gpt(prompt)

# --------------------------------------
# Enhancement 7: Attachment & Link Intelligence
# --------------------------------------
def parse_attachment_intelligence(attachments: list[bytes]) -> str:
    """
Stub: Extract text from attachments and summarize key points.
"""
    # In production, parse PDFs or slides, then summarize.
    texts = ["<parsed content>" for _ in attachments]
    combined = "\n".join(texts)
    prompt = f"""
Summarize the key points from the following extracted content:
---
{combined}
---
Summary:
"""
    return chat_with_gpt(prompt)

# --------------------------------------
# Enhancement 8: Partner Profile & Preference Memory
# --------------------------------------
def update_partner_profile(sender: str, preferences: dict):
    db.collection("partner_profiles").document(sender).set(preferences, merge=True)

# --------------------------------------
# Enhancement 9: Unanswered-Question Detection
# --------------------------------------
def detect_unanswered_questions(request_text: str, reply_text: str) -> list[str]:
    prompt = f"""
Identify which questions in the original message were not answered in the reply.
Original Message:
---
{request_text}
---
Reply Message:
---
{reply_text}
---
List any unanswered questions as bullet points. If none, reply 'None'.
"""
    raw = chat_with_gpt(prompt)
    return [line.strip('- ').strip() for line in raw.splitlines() if line.startswith('-')]

# --------------------------------------
# Enhancement 10: Performance Metrics Dashboard
# --------------------------------------
def record_metrics(sender: str, response_time_s: float, priority: float):
    db.collection("partner_metrics").add({
        "sender": sender,
        "response_time_s": response_time_s,
        "priority_score": priority,
        "timestamp": firestore.SERVER_TIMESTAMP
    })

# --------------------------------------
# Core Handler
# --------------------------------------
def handle_partner_email(email_obj):
    start = datetime.utcnow()
    sender = email_obj["sender"]
    body = email_obj["body"]
    subject = email_obj.get("subject", "")

    # Classify and store
    tags = classify_partner_intent(body)
    store_partner_message(email_obj, tags)

    # Enhance context
    sentiment = analyze_sentiment(body)
    action_items = extract_action_items(body)
    priority = compute_priority_score(tags, sentiment, body)
    slots = propose_meeting_slots(body)
    attachment_summary = parse_attachment_intelligence(email_obj.get("attachments", []))
    thread_summary = summarize_thread(sender)

    # Update partner profile if needed
    update_partner_profile(sender, {"last_sentiment": sentiment})

    # Create reminder if asked
    create_reminder_if_needed(email_obj, tags)

    # Compose reply

    action_items_str = "- " + "\n- ".join(action_items) if action_items else "None"
    slots_str = "- " + "\n- ".join(slots) if slots else "No availability provided"

    prompt = f"""
You are an intelligent VC chief of staff named Mano.

Latest partner message:
---
{body}
---
Thread summary:
{thread_summary}

Attachment summary (if any):
{attachment_summary}

Action items extracted:
{action_items_str}

Available slots:
{slots_str}

Respond in a clear, concise, and helpful tone. Match partner style.
{PARTNER_VOICE}
"""
    reply = chat_with_gpt(prompt)

    # Check for missed questions
    missed = detect_unanswered_questions(body, reply)
    if missed and missed != ['None']:
        follow_up = "\n".join(f"• {q}" for q in missed)
        reply += f"\n\nP.S. I realized I missed the following questions:\n{follow_up}"

    # Send reply
    send_email_reply(sender, subject, reply)

    # Record metrics
    elapsed = (datetime.utcnow() - start).total_seconds()
    record_metrics(sender, elapsed, priority)

    return reply

# ⏰ Periodic tasks (can be scheduled externally)
def send_weekly_partner_digest():
    digest = compile_weekly_digest()
    send_email_reply(EMAIL_USER, "Weekly Partner Digest", digest)

