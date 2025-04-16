# mano_backend_v0.py
from flask import Flask, request, jsonify
import fitz  # PyMuPDF
import openai
import os
import tempfile

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

VC_THESIS = "We back pre-seed AI infra companies with traction in vertical SaaS, based in the US."

@app.route("/upload", methods=["POST"])
def handle_upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if not file.filename.endswith(".pdf"):
        return jsonify({"error": "Only PDF files supported"}), 400

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        file.save(tmp_file.name)
        pdf_text = extract_text_from_pdf(tmp_file.name)

    summary, match_score, email = generate_ai_response(pdf_text, VC_THESIS)

    return jsonify({
        "summary": summary,
        "match_score": match_score,
        "email_response": email
    })

def extract_text_from_pdf(filepath):
    text = ""
    doc = fitz.open(filepath)
    for page in doc:
        text += page.get_text()
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
    3. Write an email response in the following tone: 'Hey, loved the pitch. Would love to schedule a call.'
    """

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    content = response.choices[0].message['content']
    lines = content.split("\n")
    summary = lines[1].strip()
    match = lines[3].strip()
    email = "\n".join(lines[5:]).strip()

    return summary, match, email

if __name__ == "__main__":
    app.run(debug=True, port=5000)
