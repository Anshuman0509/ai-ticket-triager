# AI Customer Support Ticket Triager

An automation pipeline that classifies incoming customer support tickets by
**category, priority, and sentiment**, drafts a suggested first reply, and
routes urgent tickets to Slack while logging everything to a spreadsheet —
with no human touching the ticket until triage is done.

## Architecture

```
Customer Ticket (form / email)
        │
        ▼
  n8n Webhook  ──►  FastAPI /triage (Claude API + rule-based fallback)
        │
        ▼
  n8n Switch (route by priority)
        │
   ┌────┴─────┐
   ▼          ▼
 Slack     Google Sheets
(Urgent/    (all tickets
 High)       logged)
```

- **n8n** handles orchestration: receiving the ticket via webhook, calling
  the classification API, and branching the workflow based on the result.
- **FastAPI microservice** (`app/main.py`) does the actual classification.
  If `ANTHROPIC_API_KEY` is set it calls Claude for category/priority/
  sentiment/suggested-reply; otherwise it uses a deterministic keyword-based
  classifier so the pipeline still runs in an offline/demo environment.
- **Fail-safe design**: if the LLM call fails for any reason, the service
  automatically falls back to the rule-based classifier instead of
  returning a 500, so the automation never breaks mid-pipeline.

## Run it locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...   # optional — omit to use the rule-based fallback
uvicorn app.main:app --reload --port 8000
```

Test it:

```bash
curl -X POST http://localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d '{"subject": "Cannot log in", "body": "I keep getting a 500 error, this is urgent"}'
```

## n8n workflow

`n8n_workflow.json` can be imported directly into n8n (Workflows → Import
from File). It contains:

1. **Webhook** — receives new tickets (e.g. from a support form or email
   parser)
2. **HTTP Request** — calls the FastAPI `/triage` endpoint
3. **Switch** — routes Urgent/High priority tickets to Slack, everything
   else to a Google Sheets log

## Tech stack

Python, FastAPI, Claude API, n8n, Slack API, Google Sheets API, Pydantic

## Possible extensions

- Swap the rule-based fallback for a local open-source model
- Add a helpdesk integration (Zendesk/Freshdesk) instead of Sheets
- Add a feedback loop where agent edits to the suggested reply are logged
  for future fine-tuning
