"""
ARIES Intelligence Engine — push_to_firebase.py  (Member 1)

Job: take extracted_events.json (output of prompt_manager.py), push raw
events to Firestore, and compute/write an aggregated per-corridor risk
score that the frontend listens to in real time.

Run:
    python push_to_firebase.py

Requires:
    pip install firebase-admin
    serviceAccountKey.json in this folder (from Firebase Console →
    Project Settings → Service Accounts → Generate new private key)

Firestore structure this creates:
    /risk_events/{event_id}        — raw extracted events (audit trail)
    /corridor_risk/{corridor_name} — live aggregated score per corridor
                                       (THIS is what MapComponent.jsx /
                                       firebase_listener.js should subscribe to)

CHANGES vs previous version:
    - Explicitly connects to the "(default)" database by name, to avoid
      ambiguity if your Firebase project ever has more than one database.
    - Prints the project_id it's connecting to BEFORE trying to write,
      so a mismatch is obvious immediately instead of buried in a traceback.
    - Retries the connection a few times with a short delay, since a
      freshly-created Firestore database can take a minute or two to
      become fully available even after the Console shows it as ready.
    - Clearer, plain-English error messages instead of raw Google
      exception dumps.
"""

import json
import sys
import time
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore
from google.api_core.exceptions import NotFound, PermissionDenied

SERVICE_ACCOUNT_FILE = "serviceAccountKey.json"
DATABASE_ID = "(default)"  # matches what you see in the Firebase Console

# Baseline risk per corridor — same numbers Member 2 uses in reserves_calculator.py
# Keep these in sync across the team.
BASELINE_RISK = {
    "Strait of Hormuz": 0.35,
    "Red Sea / Bab-el-Mandeb": 0.30,
    "Cape of Good Hope": 0.05,
    "Pacific / Russia Far East (ESPO)": 0.10,
    "US Gulf - India direct": 0.05,
}


def init_firebase():
    with open(SERVICE_ACCOUNT_FILE) as f:
        key_data = json.load(f)
    project_id = key_data.get("project_id", "UNKNOWN")
    print(f"Using service account for project: {project_id}")

    cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)

    # Avoid "app already exists" error if this script is re-run in the
    # same interactive session.
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {"projectId": project_id})

    try:
        db = firestore.client(database_id=DATABASE_ID)
    except TypeError:
        # Older firebase-admin versions don't accept database_id — fall
        # back to the plain client, which uses "(default)" automatically.
        db = firestore.client()

    return db, project_id


def wait_for_database(db, max_attempts=5, delay_seconds=15):
    """
    A freshly created Firestore database can take a minute or two to
    become fully reachable even though the Console shows it as ready.
    This does a trivial read to confirm the database actually responds
    before we try writing real data.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            list(db.collections())  # cheap call, just checks connectivity
            print("✓ Firestore is reachable.")
            return True
        except NotFound:
            print(
                f"  Database not ready yet (attempt {attempt}/{max_attempts}). "
                f"Waiting {delay_seconds}s..."
            )
            time.sleep(delay_seconds)
        except PermissionDenied as e:
            print("\n✗ Permission denied talking to Firestore.")
            print("  This usually means the Cloud Firestore API is still disabled,")
            print("  or this service account doesn't have access to this project.")
            print(f"  Details: {e}")
            sys.exit(1)

    print("\n✗ Firestore still not reachable after several attempts.")
    print("  Double check in Firebase Console → Firestore Database that a")
    print("  database named (default) exists and shows data/collections tabs")
    print("  without errors.")
    sys.exit(1)


def push_raw_events(db, events):
    """Store each extracted event individually — audit trail + lets the
    frontend show a 'recent events' feed if you want one."""
    batch = db.batch()
    for event in events:
        doc_ref = db.collection("risk_events").document(event["id"])
        batch.set(doc_ref, event)
    batch.commit()
    print(f"✓ Pushed {len(events)} raw events to /risk_events")


def compute_corridor_scores(events):
    """
    Aggregate events per corridor into a single rolling risk score.
    Simple approach: baseline pulled up toward the highest (severity*confidence)
    event for that corridor. Tune this — it's intentionally simple for a prototype.
    """
    scores = {}
    for corridor, baseline in BASELINE_RISK.items():
        relevant = [e for e in events if e["corridor"] == corridor]
        if relevant:
            max_weighted = max(e["severity"] * e["confidence"] for e in relevant)
            risk_score = min(1.0, baseline + max_weighted * (1 - baseline))
            trend = "rising" if risk_score > baseline else "stable"
        else:
            risk_score = baseline
            trend = "stable"

        scores[corridor] = {
            "corridor": corridor,
            "risk_score": round(risk_score, 3),
            "trend": trend,
            "driving_event_ids": [e["id"] for e in relevant],
            "event_count": len(relevant),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return scores


def safe_doc_id(name: str) -> str:
    """
    Firestore document IDs can't contain '/' (it reads as a path separator).
    Some corridor names do, e.g. "Red Sea / Bab-el-Mandeb" — replace it with
    a dash so Firestore treats it as a single flat document name.
    """
    return name.replace("/", "-")


def push_corridor_scores(db, scores):
    """This is the live doc the React frontend should listen to with onSnapshot."""
    batch = db.batch()
    for corridor, data in scores.items():
        doc_ref = db.collection("corridor_risk").document(safe_doc_id(corridor))
        batch.set(doc_ref, data)  # data.corridor still holds the real, unmodified name
    batch.commit()
    print(f"✓ Pushed {len(scores)} corridor risk scores to /corridor_risk")


def main():
    db, project_id = init_firebase()

    print(f"Connecting to Firestore database '{DATABASE_ID}' in project '{project_id}'...")
    wait_for_database(db)

    with open("extracted_events.json") as f:
        events = json.load(f)

    push_raw_events(db, events)

    scores = compute_corridor_scores(events)
    push_corridor_scores(db, scores)

    print("\nCorridor risk summary:")
    for corridor, data in scores.items():
        print(f"  {corridor}: {data['risk_score']} ({data['trend']}, {data['event_count']} events)")

    print(f"\nDone. Check Firebase Console → Firestore Database → Data tab for project '{project_id}'.")


if __name__ == "__main__":
    main()
