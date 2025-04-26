from urgency_scorer import score_urgency

def process_email_for_memory(email_data):
    """Takes parsed email dict, returns structured memory item."""
    
    body = email_data.get("body", "")
    tone = email_data.get("tone", "neutral")  # Assume tone detection happens earlier

    urgency = score_urgency(body, tone)

    # Rough intent tagging
    intent_tags = []
    if any(word in body for word in ["schedule", "meeting", "calendar", "invite"]):
        intent_tags.append("scheduling")
    if any(word in body for word in ["deck", "pitch", "fundraise", "invest"]):
        intent_tags.append("dealflow")
    if any(word in body for word in ["reminder", "follow up", "ping"]):
        intent_tags.append("follow_up")
    if not intent_tags:
        intent_tags.append("note")

    # Generate simple action plan
    action_steps = ""
    if "scheduling" in intent_tags:
        action_steps = "Suggest meeting times."
    elif "dealflow" in intent_tags:
        action_steps = "Review pitch deck and summarize key points."
    elif "follow_up" in intent_tags:
        action_steps = "Send a follow-up email."

    memory_data = {
        "thread_id": email_data.get("thread_id"),
        "sender": email_data.get("sender"),
        "recipients": email_data.get("recipients"),
        "subject": email_data.get("subject"),
        "body": body,
        "urgency_score": urgency,
        "intent_tags": intent_tags,
        "action_steps": action_steps,
        "completed": False,
        "source": email_data.get("source", "partner"),  # default to partner
        "tone": tone,
        "parsed_summary": email_data.get("parsed_summary", "")
    }

    return memory_data
