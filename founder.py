import os
import fitz  # PyMuPDF
import smtplib
from email.mime.text import MIMEText
from firebase import db
from firebase_admin import firestore
from dotenv import load_dotenv

from gpt_helpers import generate_pitch_summary, generate_friendly_feedback
from memory_logger import save_memory
from sentience_engine import process_email_for_memory

load_dotenv()

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

VC_THESIS = """
We invest in early-stage startups leveraging AI to create defensible workflows within vertical SaaS, infrastructure, or marketplaces. 
Founders must show deep understanding of their space, product velocity, and clarity in go-to-market execution.
"""

def extract_text_from_pdf(pdf_bytes):
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return "\n".join([page.get_text() for page in doc])
    except Exception as e:
        print(f"❌ PDF extraction failed: {e}")
        return ""

def send_email_reply(to_email, subject, reply_text):
    msg = MIMEText(reply_text)
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = EMAIL_USER
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, [to_email], msg.as_string())
        print(f"✅ Email sent to {to_email}")
    except Exception as e:
        print(f"❌ Email send failed: {e}")

def handle_founder_email(email_obj):
    attachments = email_obj.get("attachments", {})
    pdf_text = ""
    meaningful_pitch = False

    if attachments:
        pdf_filename, pdf_bytes = next(iter(attachments.items()))
        pdf_text = extract_text_from_pdf(pdf_bytes)
        if pdf_text.strip():
            meaningful_pitch = True
    else:
        print("📭 No pitch deck attached — continuing with body only.")

    email_body = email_obj["body"].strip()
    sender = email_obj["sender"]
    subject = email_obj["subject"]

    try:
        report = generate_pitch_summary(email_body, pdf_text, VC_THESIS)
        if report.strip() and "⚠️" not in report:
            meaningful_pitch = True
    except Exception as e:
        report = "⚠️ Could not generate response."
        print(f"❌ GPT error: {e}")

    if not meaningful_pitch:
        print(f"⚠️ No meaningful pitch received from {sender}")
        send_email_reply(
            sender,
            subject,
            """Hi there,

Thanks for reaching out!

It looks like we weren’t able to extract a full pitch or deck from your message. Could you kindly resend your pitch, preferably with a PDF deck if you have one?

Warmly,  
The Mano Team"""
        )
        return  # 🚪 Stop here. Don't save junk.

    # Save valid pitch to Firestore
    try:
        db.collection("pitches").add({
            "sender": sender,
            "subject": subject,
            "body": email_body,
            "parsed_summary": report,
            "thread_id": email_obj.get("thread_id"),
            "recipients": email_obj.get("recipients", []),
            "source": "founder",
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        print(f"✅ Pitch saved for {sender}")
    except Exception as e:
        print(f"❌ Firestore save failed: {e}")

    # Send proper thank you email
    send_email_reply(
        sender,
        subject,
        """Hi there,

Thank you for sharing your pitch with us.

Your deck has been received and logged for review. Our investment team reviews submissions on a weekly basis, and we’ll reach out if it aligns with our current thesis or warrants a deeper look.

If you’d like feedback, feel free to reply to this email — we’re happy to share a few thoughts when we can.

Warmly,  
The Mano Team"""
    )

def handle_founder_reply(email_obj):
    sender = email_obj["sender"]

    try:
        docs = db.collection("pitches")\
            .where("sender", "==", sender)\
            .order_by("timestamp", direction=firestore.Query.DESCENDING)\
            .limit(1)\
            .stream()

        doc = next(docs, None)

        if not doc:
            send_email_reply(sender, email_obj["subject"],
                "Hey! We couldn’t locate your original pitch in our system. Mind resending the deck?")
            print("⚠️ No pitch found — sent missing pitch request.")
            return

        data = doc.to_dict()
        original_report = data.get("parsed_summary", "")
        original_body = data.get("body", "")

        if not original_body.strip() or not original_report.strip() or "⚠️" in original_report:
            send_email_reply(sender, email_obj["subject"],
                "Hey! We received your reply but don’t seem to have your full deck or summary on file. Could you please resend it?")
            print("⚠️ Original report missing or broken — asked for resubmission.")
            return

        # 🧠 Build real feedback message
        feedback_prompt = f"""
📩 Original Pitch:
{original_body}

🧠 Internal Summary:
{original_report}

💬 Founder Reply:
{email_obj['body']}
"""

        reply = generate_friendly_feedback(feedback_prompt)
        send_email_reply(sender, email_obj["subject"], reply)
        print(f"✅ Feedback reply sent to {sender}")

    except Exception as e:
        print(f"❌ Failed to send founder feedback: {e}")
