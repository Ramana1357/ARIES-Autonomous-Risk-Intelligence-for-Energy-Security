"""
ARIES Intelligence Engine — prompt_manager.py  (Member 1)

Job: read mock_news_feed.json, send each headline/body to Claude, and get
back STRUCTURED JSON matching our risk event schema. This is the core
"AI" piece of the Intelligence Agent.

Run:
    python prompt_manager.py

Output:
    extracted_events.json  — structured risk events, ready for push_to_firebase.py

Requires:
    pip install anthropic python-dotenv
    export ANTHROPIC_API_KEY=sk-ant-...   (or put it in a .env file)
"""

import json
import os
import re
from datetime import datetime, timezone

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()  # reads ANTHROPIC_API_KEY from env automatically

MODEL = "claude-sonnet-4-6"

# The known corridors — keep this in sync with the rest of the team's data.
VALID_CORRIDORS = [
    "Strait of Hormuz",
    "Red Sea / Bab-el-Mandeb",
    "Cape of Good Hope",
    "Pacific / Russia Far East (ESPO)",
    "US Gulf - India direct",
]

EXTRACTION_SYSTEM_PROMPT = f"""You are a geopolitical risk analyst for a crude oil supply chain monitoring system.

You will be given a single news headline and body text. Extract structured risk information
and respond with ONLY a JSON object — no preamble, no markdown fences, no explanation.

The JSON must have exactly these fields:
{{
  "corridor": one of {VALID_CORRIDORS} (pick the single most relevant one; if none clearly apply, pick the closest match),
  "supplier_country": the country most relevant to this event, or null if not applicable,
  "event_type": a short snake_case label, e.g. "military_standoff", "sanctions", "attack", "insurance_repricing", "diplomatic_statement", "rerouting_behavior",
  "severity": a float from 0.0 to 1.0 — how disruptive is this to crude flow if it escalates? (0.0 = negligible, 1.0 = catastrophic full closure),
  "confidence": a float from 0.0 to 1.0 — how certain/verified is this event, based on the source and language used?,
  "summary": a one-sentence plain-language summary of the risk implication (not a copy of the headline)
}}

Be conservative with severity — most single events should score 0.3-0.6 unless they describe an
actual closure, attack causing damage, or confirmed supply halt. Rumors, threats, and statements
score lower than confirmed physical incidents.
"""


def extract_event(news_item: dict) -> dict:
    """Send one news item to Claude, get back a structured risk event dict."""
    user_prompt = f"Headline: {news_item['headline']}\n\nBody: {news_item['body']}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = response.content[0].text.strip()

    # Defensive parsing: strip markdown fences if Claude adds them anyway
    raw_text = re.sub(r"^```(json)?|```$", "", raw_text, flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        print(f"  ⚠ Failed to parse JSON for {news_item['id']}, raw output was:\n{raw_text}")
        return None

    # Attach source metadata
    parsed["id"] = news_item["id"]
    parsed["source"] = news_item["source"]
    parsed["source_timestamp"] = news_item["timestamp"]
    parsed["processed_at"] = datetime.now(timezone.utc).isoformat()

    return parsed


def main():
    with open("mock_news_feed.json") as f:
        news_items = json.load(f)

    print(f"Processing {len(news_items)} news items through Claude...\n")

    extracted_events = []
    for item in news_items:
        print(f"→ {item['id']}: {item['headline'][:70]}...")
        event = extract_event(item)
        if event:
            extracted_events.append(event)
            print(f"  ✓ corridor={event['corridor']}, severity={event['severity']}, confidence={event['confidence']}")

    with open("extracted_events.json", "w") as f:
        json.dump(extracted_events, f, indent=2)

    print(f"\nDone. {len(extracted_events)}/{len(news_items)} events extracted → extracted_events.json")


if __name__ == "__main__":
    main()
