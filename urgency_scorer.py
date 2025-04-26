import re

def score_urgency(email_body, tone="neutral"):
    """
    Score urgency of an email based on language and tone.
    Returns an integer between 0 and 10.
    0 = no urgency (backlog)
    10 = extreme urgency (critical immediate)
    """
    body = email_body.lower()

    urgency = 0  # Default to no urgency

    # Step 1: Keyword detection
    if any(word in body for word in ["immediately", "asap", "urgent", "critical", "eod", "right away", "now"]):
        urgency = 9
    elif any(word in body for word in ["today", "by tonight", "in a few hours", "end of day", "this afternoon"]):
        urgency = 7
    elif any(word in body for word in ["tomorrow", "next day", "soon"]):
        urgency = 5
    elif any(word in body for word in ["this week", "early next week", "upcoming"]):
        urgency = 3
    elif any(word in body for word in ["next month", "whenever", "no rush"]):
        urgency = 1

    # Step 2: Tone adjustment
    if tone.lower() in ["frustrated", "concerned", "angry", "anxious"]:
        urgency = min(urgency + 1, 10)

    return urgency
