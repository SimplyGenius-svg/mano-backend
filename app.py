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

# Load environment variables from .env file
env_path = Path(__file__).resolve().parent / ".env"
print(f"🔍 Loading .env from {env_path}")
load_dotenv(dotenv_path=env_path)

openai.api_key = os.getenv("OPENAI_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
print("✅ OpenAI Key Loaded:", "✔️" if openai.api_key else "❌ MISSING")
print("✉️ Email Config Loaded:", "✔️" if EMAIL_USER and EMAIL_PASS else "❌ MISSING")

app = Flask(__name__)

VC_THESIS = "We back pre-seed AI infra companies with traction in vertical SaaS, based in the US."

# Initialize the vector database
vector_db = PitchVectorDB()

@app.route("/upload", methods=["POST"])
def handle_upload():
    try:
        print("🚀 /upload HIT")

        if 'file' not in request.files:
            print("❌ No file in request")
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files['file']
        from_email = request.form.get('from_email', 'gyanb@berkeley.edu')
        subject = request.form.get('subject', 'New Pitch Submission')

        print(f"📄 File received: {file.filename} from {from_email}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            file.save(tmp_file.name)
            print(f"✅ File saved: {tmp_file.name}")
            pdf_text = extract_text_from_pdf(tmp_file.name)
            print("📖 Extracted PDF Text Preview:", pdf_text[:200])

        summary, match_score, email = generate_ai_response(pdf_text, VC_THESIS)
        print("🧠 GPT Response OK")
        
        # Analyze industry using OpenAI
        industry = extract_industry(pdf_text)
        
        # Store in vector database
        metadata = {
            "founder_email": from_email,
            "subject": subject,
            "summary": summary,
            "match_score": match_score.split()[0] if match_score else "0", 
            "industry": industry,
            "company_name": extract_company_name(subject, pdf_text)
        }
        pitch_id = vector_db.add_pitch(pdf_text, metadata)
        print(f"📊 Added to vector DB with ID: {pitch_id}")

        # Send email back to sender
        send_email(from_email, f"🧰 Mano's Summary: {subject}", f"Summary:\n{summary}\n\nMatch Score:\n{match_score}\n\nEmail Draft:\n{email}")

        return jsonify({
            "summary": summary,
            "match_score": match_score,
            "email_response": email,
            "pitch_id": pitch_id
        })

    except Exception as e:
        print("🔥 ERROR:", str(e))
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

def extract_text_from_pdf(filepath):
    print(f"🔍 Parsing PDF: {filepath}")
    text = ""
    doc = fitz.open(filepath)
    for page_num in range(min(3, len(doc))):
        text += doc[page_num].get_text()
    doc.close()
    return text[:8000]

def generate_ai_response(text, thesis):
    prompt = f"""
You are Mano, an AI Chief of Staff for a VC.

Analyze the following pitch deck text:
---
{text}
---

Compare it to the VC's thesis:
"{thesis}"

1. Provide a 3-sentence TL;DR of the company.
2. Give it a 1-5 match score with the thesis and explain why.
3. Write a professional email response from a VC to a founder with the following:
   - Professional greeting
   - Brief mention of having reviewed their pitch
   - Your thoughts on their company (1-2 sentences)
   - Clear next steps (if interested) or polite pass (if not a match)
   - Professional closing with VC firm name
   - Keep the tone warm but professional

Format the email properly with appropriate spacing between paragraphs.
"""

    print("🧠 Calling OpenAI GPT-4o...")
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    content = response.choices[0].message['content']
    print("🧠 RAW GPT OUTPUT:\n", content)

    # More forgiving pattern to capture TLDR and Match Score
    summary_match = re.search(r"1[\.\):\-]*\s*(.*?)(?=\n2[\.\):\-])", content, re.DOTALL)
    match_score_match = re.search(r"2[\.\):\-]*\s*(.*?)(?=\n3[\.\):\-])", content, re.DOTALL)
    email_match = re.search(r"3[\.\):\-]*\s*(.*)", content, re.DOTALL)

    summary = summary_match.group(1).strip() if summary_match else "[No summary found]"
    match_score = match_score_match.group(1).strip() if match_score_match else "[No match score found]"
    email = email_match.group(1).strip() if email_match else "[No email draft found]"

    # Clean out markdown ``` if GPT puts the email in a code block
    email = re.sub(r"^```.*?\n", "", email)
    email = re.sub(r"\n```$", "", email)

    return summary, match_score, email

def extract_industry(text):
    """Extract industry from pitch deck using OpenAI"""
    prompt = f"""
    Based on the following pitch deck text, identify the primary industry category 
    of this startup. Respond with ONLY ONE of these categories:
    - AI/ML
    - SaaS
    - FinTech
    - Healthcare
    - E-commerce
    - EdTech
    - Hardware
    - Consumer
    - Enterprise
    - Other (specify if possible)
    
    Text: {text[:2000]}
    """
    
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    industry = response.choices[0].message['content'].strip()
    return industry

def extract_company_name(subject, text):
    """Extract company name from subject line or text"""
    # Try to find it in the first 500 chars
    match = re.search(r"(?:company|startup|venture)[\s:]+([\w\s]+)", text[:500], re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    # Otherwise extract from subject if possible
    words = subject.split()
    if len(words) >= 2:
        return words[0] + " " + words[1]
    
    return "Unknown Company"

def send_email(to_address, subject, body):
    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_USER
    msg["To"] = to_address
    msg["Subject"] = subject

    # Create plain text version
    text_part = MIMEText(body, "plain")
    
    # Create HTML version (convert plain text to HTML with paragraphs)
    html_body = body.replace('\n\n', '</p><p>').replace('\n', '<br>')
    html_body = f"<html><body><p>{html_body}</p></body></html>"
    html_part = MIMEText(html_body, "html")
    
    # Attach both parts - email clients will display the best one they support
    msg.attach(text_part)
    msg.attach(html_part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(msg["From"], [msg["To"]], msg.as_string())
    print(f"✉️ Sent email to {to_address}")

# Add new routes for searching

@app.route("/search", methods=["GET"])
def search_pitches():
    query = request.args.get("query", "")
    industry = request.args.get("industry", None)
    min_score = request.args.get("min_score", None)
    n_results = int(request.args.get("n_results", 5))
    
    if not query:
        return jsonify({"error": "Query parameter is required"}), 400
        
    results = vector_db.search_similar_pitches(
        query_text=query, 
        n_results=n_results,
        industry=industry,
        min_score=min_score
    )
    
    return jsonify({"results": results})

@app.route("/pitches", methods=["GET"])
def get_pitches():
    industry = request.args.get("industry", None)
    min_score = request.args.get("min_score", None)
    limit = int(request.args.get("limit", 100))
    
    results = vector_db.get_all_pitches(
        industry=industry,
        min_score=min_score,
        limit=limit
    )
    
    return jsonify({"pitches": results})

if __name__ == "__main__":
    app.run(debug=True, port=5000)