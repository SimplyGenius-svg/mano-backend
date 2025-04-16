from flask import Flask, request, jsonify
from dotenv import load_dotenv
from pathlib import Path
import openai
import fitz  # PyMuPDF
import os
import tempfile
import traceback

# Load environment from .env file
env_path = Path(__file__).resolve().parent / ".env"
print(f"🔍 Loading .env from {env_path}")
load_dotenv(dotenv_path=env_path)

openai.api_key = os.getenv("OPENAI_API_KEY")
print("✅ OpenAI Key Loaded:", "✔️" if openai.api_key else "❌ MISSING")

app = Flask(__name__)

VC_THESIS = "We back pre-seed AI infra companies with traction in vertical SaaS, based in the US."


@app.route("/upload", methods=["POST"])
def handle_upload():
    try:
        print("🚀 /upload HIT")

        if 'file' not in request.files:
            print("❌ No file in request")
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files['file']
        print(f"📄 File received: {file.filename}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            file.save(tmp_file.name)
            print(f"✅ File saved: {tmp_file.name}")
            pdf_text = extract_text_from_pdf(tmp_file.name)
            print("📖 Extracted PDF Text Preview:", pdf_text[:200])

        summary, match_score, email = generate_ai_response(pdf_text, VC_THESIS)
        print("🧠 GPT Response OK")

        return jsonify({
            "summary": summary,
            "match_score": match_score,
            "email_response": email
        })

    except Exception as e:
        print("🔥 ERROR:", str(e))
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


def extract_text_from_pdf(filepath):
    print(f"🔍 Parsing PDF: {filepath}")
    text = ""
    doc = fitz.open(filepath)
    for page_num in range(min(3, len(doc))):  # Only first 3 pages
        text += doc[page_num].get_text()
    doc.close()
    return text[:8000]


import re

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
3. Write an email response in the following tone: 'Hey, loved the pitch. Would love to schedule a call.'
"""

    print("🧠 Calling OpenAI GPT-4o...")
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    content = response.choices[0].message['content']
    print("🧠 RAW GPT OUTPUT:\n", content)

    # Regex to pull sections between headers
    summary_match = re.search(r"1\..*?\n(.*?)\n2\.", content, re.DOTALL)
    match_score_match = re.search(r"2\..*?\n(.*?)\n3\.", content, re.DOTALL)
    email_match = re.search(r"3\..*?\n(.*)", content, re.DOTALL)

    summary = summary_match.group(1).strip() if summary_match else ""
    match_score = match_score_match.group(1).strip() if match_score_match else ""
    email = email_match.group(1).strip() if email_match else ""

    # Cleanup markdown code block markers
    email = re.sub(r"^```.*?\n", "", email)  # remove opening ```
    email = re.sub(r"\n```$", "", email)     # remove closing ```

    return content, "", ""




if __name__ == "__main__":
    app.run(debug=True, port=5000)
