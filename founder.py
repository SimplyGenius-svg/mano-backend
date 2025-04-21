import os
import fitz  # PyMuPDF
from firebase import db
from firebase_admin import firestore
from gpt_helpers import generate_pitch_summary, generate_friendly_feedback
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText

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
    if not attachments:
        print("📭 No pitch deck attached — skipping.")
        return

    pdf_filename, pdf_bytes = next(iter(attachments.items()))
    pdf_text = extract_text_from_pdf(pdf_bytes)
    email_body = email_obj["body"]

    try:
        report = generate_pitch_summary(email_body, pdf_text, VC_THESIS)
    except Exception as e:
        report = "⚠️ Could not generate response."
        print(f"❌ GPT error: {e}")

    # Save to Firestore only if GPT succeeded
    if "⚠️" not in report:
        try:
            founder_id = email_obj["sender"].replace(".", "_").replace("@", "__")
            doc_id = f"{founder_id}_{email_obj['id']}"
            db.collection("pitches").document(doc_id).set({
                "email": email_obj["sender"],
                "subject": email_obj["subject"],
                "last_body": email_body,
                "report": report,
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            print(f"✅ Pitch report saved: {doc_id}")
        except Exception as e:
            print(f"❌ Firestore error: {e}")

    send_email_reply(
        email_obj["sender"],
        email_obj["subject"],
        """Hi there,

Thank you for sharing your pitch with us.

Your deck has been received and logged for review. Our investment team reviews submissions on a weekly basis, and we’ll reach out if it aligns with our current thesis or warrants a deeper look.

If you’d like feedback, feel free to reply to this email — we’re happy to share a few thoughts when we can.

Warmly,  
The Mano Team"""
    )


def handle_founder_reply(email_obj):
    sender = email_obj["sender"]
    founder_id = sender.replace(".", "_").replace("@", "__")

    try:
        # Fetch latest pitch
        docs = db.collection("pitches").where("email", "==", sender).order_by("timestamp", direction=firestore.Query.DESCENDING).limit(1).stream()
        doc = next(docs, None)

        if not doc:
            print("⚠️ No pitch found to reply against.")
            return

        data = doc.to_dict()
        original_report = data.get("report", "")
        original_body = data.get("last_body", "")

        thread = f"""
📩 Original Pitch:
{original_body}

🧠 Internal Summary:
{original_report}

💬 Founder Reply:
{email_obj['body']}
"""

        reply = generate_friendly_feedback(thread)
        send_email_reply(sender, email_obj["subject"], reply)
        print(f"✅ Feedback reply sent to {sender}")

    except Exception as e:
        print(f"❌ Failed to send founder feedback: {e}")
