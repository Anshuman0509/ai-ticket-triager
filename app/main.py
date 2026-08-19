"""
AI Customer Support Ticket Triager
-----------------------------------
FastAPI microservice that classifies incoming support tickets by
category, priority, and sentiment, and drafts a suggested first reply.

Designed to sit behind an n8n workflow:
  Webhook (new ticket) -> HTTP Request (this /triage endpoint)
      -> Switch (route by priority) -> Slack / Google Sheets / Helpdesk

If ANTHROPIC_API_KEY is set, classification is done with Claude.
Otherwise it falls back to a deterministic keyword-based classifier
so the service still runs end-to-end in a demo/offline environment.
"""

import os
import json
import re
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="AI Ticket Triager", version="1.0.0")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-6"

@app.get("/")
def read_root():
    return {"message": "AI Ticket Triager is running!"}


class Ticket(BaseModel):
    subject: str
    body: str
    customer_email: Optional[str] = None


class TriageResult(BaseModel):
    category: str
    priority: str
    sentiment: str
    suggested_reply: str
    routed_to: str


CATEGORY_KEYWORDS = {
    "Billing": ["invoice", "refund", "charge", "payment", "subscription", "price"],
    "Technical": ["bug", "error", "crash", "not working", "broken", "login", "api", "integration"],
    "Account": ["password", "account", "access", "login", "email change", "delete my account"],
}

URGENT_KEYWORDS = ["urgent", "asap", "immediately", "down", "outage", "critical", "can't access"]
NEGATIVE_KEYWORDS = ["angry", "frustrated", "terrible", "worst", "unacceptable", "disappointed", "furious"]


def rule_based_classify(subject: str, body: str) -> TriageResult:
    text = f"{subject} {body}".lower()

    category = "General"
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords):
            category = cat
            break

    priority = "Urgent" if any(k in text for k in URGENT_KEYWORDS) else "Medium"
    sentiment = "Negative" if any(k in text for k in NEGATIVE_KEYWORDS) else "Neutral"

    if priority == "Urgent" or sentiment == "Negative":
        routed_to = "slack-urgent-alerts"
    else:
        routed_to = "sheet-ticket-log"

    suggested_reply = (
        f"Hi, thanks for reaching out about \"{subject}\". "
        f"We've logged this as a {category} issue and our team is on it. "
        f"We'll follow up shortly with next steps."
    )

    return TriageResult(
        category=category,
        priority=priority,
        sentiment=sentiment,
        suggested_reply=suggested_reply,
        routed_to=routed_to,
    )


def llm_classify(subject: str, body: str) -> TriageResult:
    import httpx

    prompt = f"""Classify this support ticket. Respond ONLY with JSON, no other text.

Subject: {subject}
Body: {body}

Return JSON with exactly these fields:
{{
  "category": one of ["Billing", "Technical", "Account", "General"],
  "priority": one of ["Low", "Medium", "High", "Urgent"],
  "sentiment": one of ["Positive", "Neutral", "Negative"],
  "suggested_reply": a short, empathetic 2-3 sentence first reply to the customer
}}"""

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    response.raise_for_status()
    text = response.json()["content"][0]["text"]
    text = re.sub(r"```json|```", "", text).strip()
    data = json.loads(text)

    routed_to = "slack-urgent-alerts" if data["priority"] in ("High", "Urgent") else "sheet-ticket-log"

    return TriageResult(
        category=data["category"],
        priority=data["priority"],
        sentiment=data["sentiment"],
        suggested_reply=data["suggested_reply"],
        routed_to=routed_to,
    )


@app.get("/health")
def health():
    return {"status": "ok", "llm_enabled": bool(ANTHROPIC_API_KEY)}


@app.post("/triage", response_model=TriageResult)
def triage(ticket: Ticket):
    if ANTHROPIC_API_KEY:
        try:
            return llm_classify(ticket.subject, ticket.body)
        except Exception:
            # Fail safe: fall back to rule-based classifier rather than 500
            return rule_based_classify(ticket.subject, ticket.body)
    return rule_based_classify(ticket.subject, ticket.body)
