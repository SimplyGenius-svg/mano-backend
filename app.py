from flask import Flask, request, jsonify
from dotenv import load_dotenv
from pathlib import Path
import openai
import fitz  # PyMuPDF
import os
import tempfile
import traceback
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from vector_db import PitchVectorDB
from google.cloud import firestore

# Load environment variables
env_path = Path(__file__).resolve().parent / ".env"
print(f"🔍 Loading .env from {env_path}")
load_dotenv(dotenv_path=env_path)

openai.api_key = os.getenv("OPENAI_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

print("✅ OpenAI Key Loaded:", "✔️" if openai.api_key else "❌ MISSING")
print("✉️ Email Config Loaded:", "✔️" if EMAIL_USER and EMAIL_PASS else "❌ MISSING")

# Firestore client
firestore_client = firestore.Client()
print("🔥 Firestore Initialized")

# Initialize app
app = Flask(__name__)
VC_THESIS = "We back pre-seed AI infra companies with traction in vertical SaaS, based in the US."
vector_db = PitchVectorDB()

@app.route("/upload", methods=["POST"])
def handle_upload():
    try:
        print("🚀 /upload HIT")
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files['file']
        from_email = request.form.get('from_email', 'gyanb@berkeley.edu')
        subject = request.form.get('subject', 'New Pitch Submission')

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            file.save(tmp_file.name)
            pdf_text = extract_text_from_pdf(tmp_file.name)

        if not pdf_text.strip():
            fallback = "We received your pitch but couldn’t extract readable text. Please resend."
            send_email(from_email, "📁 Mano: Unable to Read Deck", fallback)
            return jsonify({"error": "No text extracted"}), 422

        summary, match_score, email = generate_ai_response(pdf_text, VC_THESIS)
        print("🧠 GPT parsed successfully")

        industry = extract_industry(pdf_text)
        company = extract_company_name(subject, pdf_text)

        if any(tag in summary for tag in ["[No", "[None"]) or any(tag in match_score for tag in ["[No", "[None"]):
            fallback_email = f"Dear Founder,\n\nWe received your pitch but ran into an issue processing it. Please feel free to resend.\n\nBest,\nMano Team"
            send_email(from_email, f"🔧 Mano: Processing Issue", fallback_email)
            return jsonify({"error": "AI summary or score failed"}), 500

        doc_ref = firestore_client.collection("pitches").document()
        doc_ref.set({
            "email": from_email,
            "subject": subject,
            "summary": summary,
            "match_score": match_score,
            "industry": industry,
            "company": company,
            "timestamp": firestore.SERVER_TIMESTAMP
        })

        send_email(from_email, f"🚒 Mano's Summary: {subject}", f"Summary:\n{summary}\n\nMatch Score:\n{match_score}\n\nEmail Draft:\n{email}")

        return jsonify({
            "summary": summary,
            "match_score": match_score,
            "email_response": email,
            "firestore_id": doc_ref.id
        })

    except Exception as e:
        print("🔥 ERROR:", str(e))
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

def extract_text_from_pdf(filepath):
    doc = fitz.open(filepath)
    text = "".join(page.get_text() for page in doc[:min(3, len(doc))])
    doc.close()
    return text[:8000]

def generate_ai_response(text, thesis):
    prompt = f"""
You are Mano, an AI Chief of Staff for a VC.

Analyze this pitch:
---
{text}
---

Compare it to:
"{thesis}"

Please return:

1. A 3-sentence TL;DR of the company labeled 'Summary'
2. A labeled 'Match Score' from 1–5, with reasoning underneath
3. A labeled 'Email Draft' — a professional VC-style response

Format:
Summary:
<...>

Match Score:
<score and reasoning>

Email Draft:
<email>
"""

    print("🤖 Asking GPT...")
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    content = response.choices[0].message['content']
    print("🧠 RAW GPT OUTPUT:\n", content)

    # Safer parser using keywords
    summary_match = re.search(r"Summary:\s*(.*?)(?=\nMatch Score:)", content, re.DOTALL)
    score_match = re.search(r"Match Score:\s*(.*?)(?=\nEmail Draft:)", content, re.DOTALL)
    email_match = re.search(r"Email Draft:\s*(.*)", content, re.DOTALL)

    summary = summary_match.group(1).strip() if summary_match else "[No summary found]"
    match_score = score_match.group(1).strip() if score_match else "[No match score found]"
    email = email_match.group(1).strip() if email_match else "[No email draft found]"

    return summary, match_score, email


def extract_industry(text):
    prompt = f"""
Given this deck, classify the industry:
{text[:2000]}
Options: AI/ML, SaaS, FinTech, Healthcare, E-commerce, EdTech, Hardware, Consumer, Enterprise, Other
"""
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message['content'].strip()

def extract_company_name(subject, text):
    match = re.search(r"(?:company|startup|venture)[\s:]+([\w\s]+)", text[:500], re.IGNORECASE)
    if match:
        return match.group(1).strip()
    words = subject.split()
    return " ".join(words[:2]) if len(words) >= 2 else "Unknown Company"

def send_email(to, subject, body):
    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_USER
    msg["To"] = to
    msg["Subject"] = subject
    text_part = MIMEText(body, "plain")
    html_body = body.replace('\n\n', '</p><p>').replace('\n', '<br>')
    html_part = MIMEText(f"<html><body><p>{html_body}</p></body></html>", "html")
    msg.attach(text_part)
    msg.attach(html_part)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(msg["From"], [msg["To"]], msg.as_string())
    print(f"✉️ Sent email to {to}")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
