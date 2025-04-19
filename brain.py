from openai import OpenAI
import os
from dotenv import load_dotenv
import fitz
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
from datetime import datetime, timedelta

load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY)

if not firebase_admin._apps:
    cred = credentials.Certificate("mano-firebase-key.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

def extract_text_from_pdf(pdf_bytes):
    doc = fitz.open("pdf", pdf_bytes)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def generate_weekly_pitch_digest():
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    snapshot = db.collection("pitches").where("timestamp", ">=", one_week_ago).stream()
    summaries = []
    for doc in snapshot:
        data = doc.to_dict()
        summaries.append(
            f"**{data.get('subject', 'No Subject')}**\nFrom: {data.get('sender')}\n{data.get('gpt_summary', '').strip()}\n---"
        )
    if not summaries:
        return "No pitches were submitted in the last 7 days."
    return "Here’s your weekly pitch digest:\n\n" + "\n\n".join(summaries)

def classify_email_type(email):
    prompt = f"""
You are an AI assistant categorizing inbound VC emails.

Subject: {email['subject']}
From: {email['sender']}
Date: {email['date']}
Body:
{email['body']}

Classify this email into ONE of the following:
- pitch
- update
- thread
- partner_message
- non_actionable

Respond with ONLY the category.
"""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content.strip().lower()

def analyze_pitch_email(email):
    prompt = f"""
You're Mano — a sharp AI chief of staff reviewing a cold pitch.

Subject: {email['subject']}
From: {email['sender']}
Date: {email['date']}
Body:
{email['body']}

Please:
1. TL;DR in 2–3 sentences
2. Score it 1–5 vs thesis: "Pre-seed AI infra companies in the US with traction, ideally vertical SaaS"
3. List green flags
4. List red flags
5. Decide: reply, pass, ask a question, or flag

Keep it casual but informed.
"""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return response.choices[0].message.content.strip()

def generate_feedback_email(email):
    prompt = f"""
You're Mano, a thoughtful AI chief of staff. A founder asked for feedback.

Subject: {email['subject']}
From: {email['sender']}
Body:
{email['body']}

Give:
- a warm tone
- 1–2 reasons it may not be a fit
- 1 practical suggestion

Be short, kind, and constructive.
"""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.55
    )
    return response.choices[0].message.content.strip()

def summarize_update_email(email):
    prompt = f"""
You're Mano — a VC chief of staff reviewing a founder update.

Subject: {email['subject']}
From: {email['sender']}
Body:
{email['body']}

Summarize the update in 2 sentences.
Label as: strong execution, early promise, or no real movement.
Suggest: follow up, ignore, or ask for a call.
"""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return response.choices[0].message.content.strip()

def summarize_thread(email):
    prompt = f"""
You're Mano — an AI in an ongoing email thread.

Subject: {email['subject']}
From: {email['sender']}
Body:
{email['body']}

Summarize the conversation so far.
Recommend: reply, wait, or drop it.
"""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4
    )
    return response.choices[0].message.content.strip()

def tag_and_store_partner_memory(email, response):
    sender = email['sender'].lower()
    subject = email.get("subject", "")
    body = email.get("body", "")
    email_type = "ask" if "?" in subject or "?" in body else "note"
    tags = []
    keyword_tag_map = {
        "thesis": "thesis",
        "digest": "digest",
        "summary": "summary",
        "pipeline": "pipeline",
        "dealflow": "dealflow",
        "referral": "networking",
        "intro": "networking",
        "insight": "reflection"
    }
    for keyword, tag in keyword_tag_map.items():
        if keyword in subject.lower() or keyword in body.lower():
            tags.append(tag)

    try:
        db.collection("partner_memory").add({
            "sender": sender,
            "subject": subject,
            "body": body,
            "response": response,
            "type": email_type,
            "tags": tags,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        print("✅ Logged partner message to Firestore.")
    except Exception as e:
        print(f"❌ Failed to log partner message: {e}")

def reply_to_partner(message_body, partner_name="Gyan"):
    prompt = f"""
You're Mano, chief of staff to VC {partner_name}. Respond casually and supportively to this:

\"{message_body}\"

Be smart, personal, and helpful. High emotional intelligence. Not robotic.
"""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.65
    )
    return response.choices[0].message.content.strip()

def process_incoming_email(email, return_summary=False):
    sender_email = email['sender'].lower()
    subject = email.get("subject", "").lower()
    body = email.get("body", "").lower()

    # === 🔒 Partner Handling (Gyan) — NO SKIPS EVER ===
    if sender_email == "gyanbhambhani@gmail.com":
        # ✅ FULLY HARDWIRED DIGEST TRIGGER
        if (
            "digest" in subject or "summary" in subject or
            "deal" in subject or "recap" in subject or
            "pipeline" in subject or "pitches" in subject or
            "digest" in body or "summary" in body or
            "deal" in body or "recap" in body or
            "pipeline" in body or "pitches" in body
        ):
            digest = generate_weekly_pitch_digest()
            tag_and_store_partner_memory(email, digest)
            return digest, [digest]

        # ✅ Catch-all: log and respond to literally anything else
        response = reply_to_partner(email['body'], partner_name="Gyan")
        tag_and_store_partner_memory(email, response)
        return response, [email['body']] if return_summary else response

    # === Founder Handling ===
    parsed_deck_text = ""
    if email.get("attachments"):
        for filename, file_content in email['attachments'].items():
            if filename.endswith(".pdf"):
                try:
                    parsed_deck_text = extract_text_from_pdf(file_content)
                    email['body'] += f"\n\n[Extracted Pitch Deck Text]\n{parsed_deck_text}"
                except Exception as e:
                    email['body'] += f"\n\n[Deck could not be parsed: {e}]"

    if "feedback" in body or "thoughts?" in body or "do you have any notes" in body:
        feedback = generate_feedback_email(email)
        return feedback, [] if return_summary else feedback

    email_type = classify_email_type(email)

    if email_type == "pitch":
        gpt_response = analyze_pitch_email(email)
        pitch_id = str(uuid.uuid4())
        db.collection("pitches").document(pitch_id).set({
            "sender": email['sender'],
            "subject": email['subject'],
            "body": email['body'],
            "parsed_deck": parsed_deck_text,
            "gpt_summary": gpt_response,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        return (
            f"Hi {email['sender'].split('@')[0]},\n\n"
            "Thanks for sending over your pitch deck — it's been shared with our investment team.\n\n"
            "We review all inbound pitches each week. If your startup aligns with our current focus,\n"
            "you'll hear from us by the end of the week.\n\n"
            "Appreciate you reaching out — keep building.\n\n"
            "Best,\nMano",
            []
        )

    elif email_type == "update":
        return summarize_update_email(email), [] if return_summary else summarize_update_email(email)

    elif email_type == "thread":
        return summarize_thread(email), [] if return_summary else summarize_thread(email)

    # === Default fallback for founders only ===
    return "👋 Skipped. This email doesn’t look actionable.", [] if return_summary else "👋 Skipped. This email doesn’t look actionable."
