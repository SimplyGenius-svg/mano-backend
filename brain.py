from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY)


def classify_email_type(email):
    """Classifies the type of email so Mano knows how to respond."""
    prompt = f"""
You are an AI assistant categorizing inbound VC emails.
Here is one such email:

Subject: {email['subject']}
From: {email['sender']}
Date: {email['date']}
Body:
{email['body']}

Classify this email into ONE of the following types:
- pitch (cold pitch or intro from a founder)
- update (existing founder sending updates or follow-ups)
- thread (continued conversation or multi-reply thread)
- partner_message (an internal note from the VC partner to Mano)
- non_actionable (promo, spam, general newsletter, etc.)

Respond with ONLY the category name, nothing else.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )

    category = response.choices[0].message.content.strip().lower()
    return category


def analyze_pitch_email(email):
    """
    Called when a founder sends a cold pitch or intro. 
    Mano gives an insightful, judgmental breakdown — like a chief of staff.
    """
    prompt = f"""
You're Mano — a smart, sharp, and sometimes brutally honest AI inbox assistant for a VC.
You’re reviewing an email that could be a cold pitch, intro, or warm referral.

Subject: {email['subject']}
From: {email['sender']}
Date: {email['date']}
Body:
{email['body']}

Do the following:
1. Give a 2-3 sentence TL;DR of the pitch. Be clear, not generic.
2. Score it 1–5 for match with the VC thesis: "Pre-seed AI infrastructure companies in the US with traction, ideally in vertical SaaS."
3. Mention any green flags (e.g., ex-FAANG team, early revenue, credible referrer).
4. Mention any red flags (e.g., vague traction, broad market, unclear product).
5. Decide: reply, pass, ask a question, or flag for later — and explain your thinking.

Tone: professional but informal. You're speaking to a VC you work with every day. Keep it honest, helpful, and decisive.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    return response.choices[0].message.content.strip()


def summarize_update_email(email):
    """Handles follow-up messages from founders you've already seen before."""
    prompt = f"""
You're Mano — an AI chief of staff helping your VC parse a founder update.

Here’s the email:
Subject: {email['subject']}
From: {email['sender']}
Date: {email['date']}
Body:
{email['body']}

Give a short but sharp 2–3 sentence summary of the update.
Then say whether this founder is showing:
- strong execution
- early promise
- no real movement
Suggest if we should: follow up, ignore, or ask for a call.

Tone: clear, insightful, and casual — you're speaking to the VC directly.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )

    return response.choices[0].message.content.strip()


def summarize_thread(email):
    """Used for follow-ups or ongoing threads where context is useful."""
    prompt = f"""
You're Mano — an AI who sits in email threads for a VC.
Here’s the latest message in an ongoing thread:

Subject: {email['subject']}
From: {email['sender']}
Date: {email['date']}
Body:
{email['body']}

Summarize what's happened in the thread so far.
Then make a recommendation: should we reply, wait, or drop it?

Be brief, useful, and chill.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4
    )

    return response.choices[0].message.content.strip()


def reply_to_partner(message_body, partner_name="Gyan"):
    """
    Called when the partner emails Mano directly. 
    Mano responds with emotional intelligence, clarity, and personality.
    """
    prompt = f"""
You are Mano, a loyal and emotionally intelligent AI chief of staff for a VC named {partner_name}.
They just emailed you the following message:

\"{message_body}\"

Your job:
- Respond directly, in their voice — like you're texting back someone you know really well.
- Be casual but thoughtful.
- If they sound stressed, support them. If they sound excited, lean in.
- Suggest things they might do next.
- If they ask a question, answer it directly.
- If they're being vague, try to clarify what they really need.
- NEVER sound like a boring AI. Sound like a sharp, funny, helpful person who gets the game.

Format it like you're writing a friendly but high-IQ email or iMessage.

Now write your reply.
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.65
    )

    return response.choices[0].message.content.strip()


def process_incoming_email(email):
    """
    The master function.
    Mano classifies the email and responds accordingly.
    """
    if email['sender'].lower() == "gyanbhambhani@gmail.com":
        return reply_to_partner(email['body'], partner_name="Gyan")

    email_type = classify_email_type(email)
    
    if email_type == "pitch":
        return analyze_pitch_email(email)
    
    elif email_type == "update":
        return summarize_update_email(email)

    elif email_type == "thread":
        return summarize_thread(email)

    elif email_type == "partner_message":
        return reply_to_partner(email['body'], partner_name="Gyan")

    else:
        return "👋 Skipped. This email doesn’t look actionable."
