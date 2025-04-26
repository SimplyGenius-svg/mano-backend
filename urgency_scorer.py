import re

def score_urgency(email_body, tone="neutral"):
    body = email_body.lower()

    if any(word in body for word in ["immediately", "asap", "urgent", "critical", "eod"]):
        return 3  # Immediate Critical
    if any(word in body for word in ["tomorrow", "today", "soon", "next day", "end of day"]):
        return 2  # Urgent
    if any(word in body for word in ["this week", "upcoming", "sometime soon"]):
        return 1  # Soon
    return 0  # Backlog

    # Bonus: slight tone adjustment
    if tone in ["frustrated", "concerned"]:
        return min(urgency + 1, 3)

    return urgency
