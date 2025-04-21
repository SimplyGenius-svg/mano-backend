import openai
import os
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def chat_with_gpt(prompt, temperature=0.4, model="gpt-4o"):
    """
    Unified interface for calling OpenAI ChatCompletion with new SDK syntax (v1.x+)
    """
    try:
        response = openai.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ GPT error: {e}")
        return "⚠️ Could not generate response."


def generate_pitch_summary(email_body, pdf_text, vc_thesis):
    prompt = f"""
You are a venture associate preparing a report for your general partner.

You've just received a cold pitch with the following:

📩 Email Body:
{email_body}

📄 Pitch Deck Text:
{pdf_text}

🎯 Our investment thesis:
{vc_thesis}

Write a thoughtful, structured internal report that includes:
1. Company Name (if available)
2. One-liner Summary
3. Problem Statement
4. Proposed Solution
5. Market Opportunity
6. Business Model
7. Traction or Milestones
8. Team
9. Thesis Fit Score (0–10)
10. Why or why not this fits our thesis
11. Recommendation (Pass / Review / High Priority)

Make it clear, professional, and easy for a general partner to read in under 2 minutes.
"""
    return chat_with_gpt(prompt)


def generate_friendly_feedback(email_thread):
    prompt = f"""
A founder has followed up asking for feedback on their pitch.

Below is the thread:

{email_thread}

Please write a brief, friendly, and helpful summary with:
- One area they seem strong in
- One suggestion or point of improvement
- A kind, encouraging tone
- No investment promise

Be professional and human.
"""
    return chat_with_gpt(prompt, temperature=0.5)


def generate_partner_digest(top_pitch_summaries):
    prompt = f"""
You are preparing a weekly dealflow digest for a VC partner.

Here are the top pitches and their summaries:

{top_pitch_summaries}

Write a partner-friendly, 1-page digest summarizing:
- 3–5 top pitches
- Key highlights and thesis fit
- Your recommendation on which to review

Keep it crisp and decision-oriented.
"""
    return chat_with_gpt(prompt, temperature=0.3)
