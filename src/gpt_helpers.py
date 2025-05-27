import os
import time
import concurrent.futures
import logging
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

# Load environment variables
load_dotenv()

# Setup OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gpt_helpers")

def chat_with_gpt(user_prompt, system_prompt=None, temperature=0.4, model="gpt-4o", max_retries=3, timeout_seconds=30):
    """Unified, safe GPT call with retries, timeout, system prompts, and logging."""

    def call_openai():
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=1500
            )
            return response.choices[0].message.content.strip()
        except OpenAIError as e:
            logger.error(f"OpenAI call error: {e}")
            raise e

    attempt = 0
    while attempt < max_retries:
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(call_openai)
                return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            logger.warning(f"Timeout after {timeout_seconds} seconds (attempt {attempt+1})")
        except OpenAIError as e:
            wait_time = 5 * (attempt + 1)
            logger.warning(f"OpenAI error. Waiting {wait_time} seconds before retry... Error: {e}")
            time.sleep(wait_time)
        except Exception as e:
            logger.warning(f"GPT call failed (attempt {attempt+1}): {e}")
        attempt += 1
        time.sleep(2 * attempt)  # Backoff

    logger.error("Max retries exceeded. Returning fallback.")
    return "⚠️ Could not generate response due to system error."

# --- Helper functions ---

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
You are Mano, an intelligent VC chief of staff. A founder has followed up asking for feedback on their pitch.

Below is the full thread:

{email_thread}

Write a professional, warm, and direct feedback email that includes:
- One strength we liked
- One suggestion for improvement
- A short closing encouraging them to update us later

Rules:
- DO NOT include a subject line inside the email body
- DO NOT include placeholders like [Your Name] or [Your Company]
- Always end the email with: "Warmly, Mano"
- No promises of investment

Keep it crisp, encouraging, and respectful.
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

Keep it crisp, structured, and decision-oriented.
"""
    return chat_with_gpt(prompt, temperature=0.3)

def classify_founder_email_intent(body_text):
    prompt = f"""
Classify the following founder email body into one of two categories: "pitch" or "feedback".

---
Email Body:
{body_text}
---

Rules:
- If the founder is asking for feedback, review, comments, thoughts, classify as "feedback".
- If the founder is introducing their company, pitching, fundraising, or describing their company or product, classify as "pitch".
- Only reply with "pitch" or "feedback" — nothing else.
"""
    try:
        classification = chat_with_gpt(prompt, temperature=0.2).strip().lower()
        if classification in ["pitch", "feedback"]:
            return classification
        else:
            return "pitch"  # Safe fallback
    except Exception as e:
        logger.error(f"❌ GPT classification error: {e}")
        return "pitch"  # Fallback
