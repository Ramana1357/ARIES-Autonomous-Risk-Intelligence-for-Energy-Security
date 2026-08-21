"""
ARIES Simulation Backend — main.py  (Member 2)

Job: close the loop between Member 1 and Member 3.
    1. Read the LIVE corridor risk scores Member 1 already pushed to Firebase
    2. For each corridor, calculate impact (reserves_calculator.py)
    3. For any corridor above a risk threshold, rank reroute options (reroute_algorithm.py)
    4. Write the results back to Firebase so the frontend can display them

Run:
    python main.py

Requires:
    pip install -r requirements.txt
    serviceAccountKey.json in this folder — COPY THE SAME ONE Member 1 used
    (same Firebase project, same database — this is what makes the whole
    pipeline connect end-to-end)

Firestore structure this reads:
    /corridor_risk/{corridor_name}   — written by Member 1

Firestore structure this writes:
    /scenario_impact/{corridor_name}     — output of reserves_calculator.py
    /recommendations/{corridor_name}     — output of reroute_algorithm.py
                                             (THIS is what the frontend's
                                             recommendation panel should read)
"""

import json
import sys

import firebase_admin
from firebase_admin import credentials, firestore

from reserves_calculator import calculate_impact
from reroute_algorithm import rank_reroute_options

SERVICE_ACCOUNT_FILE = "serviceAccountKey.json"

# Only run the full simulation for corridors at or above this risk level.
# Calm corridors don't need a reroute plan.
RISK_THRESHOLD_FOR_ACTION = 0.5


def init_firebase():
    with open(SERVICE_ACCOUNT_FILE) as f:
        key_data = json.load(f)
    project_id = key_data.get("project_id", "UNKNOWN")
    print(f"Using service account for project: {project_id}")

    cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {"projectId": project_id})

    return firestore.client()


def safe_doc_id(name: str) -> str:
    """Same fix Member 1 uses — Firestore doc IDs can't contain '/'."""
    return name.replace("/", "-")


def read_corridor_risk(db) -> list:
    """Reads the live risk scores Member 1's push_to_firebase.py wrote."""
    docs = db.collection("corridor_risk").stream()
    corridors = [doc.to_dict() for doc in docs]
    if not corridors:
        print("✗ No corridor_risk data found in Firebase.")
        print("  Make sure Member 1 has run push_to_firebase.py first —")
        print("  this script reads what they already pushed.")
        sys.exit(1)
    return corridors


def run_pipeline():
    db = init_firebase()

    print("\nReading live corridor risk scores from Firebase...")
    corridors = read_corridor_risk(db)

    for c in corridors:
        corridor_name = c["corridor"]
        risk_score = c["risk_score"]
        print(f"  {corridor_name}: risk={risk_score}")

    print(f"\nRunning impact + reroute analysis for corridors >= {RISK_THRESHOLD_FOR_ACTION} risk...\n")

    impact_batch = db.batch()
    rec_batch = db.batch()
    actioned_count = 0

    for c in corridors:
        corridor_name = c["corridor"]
        risk_score = c["risk_score"]

        if risk_score < RISK_THRESHOLD_FOR_ACTION:
            print(f"  {corridor_name}: risk {risk_score} below threshold, skipping simulation.")
            continue

        # 1. Calculate impact
        impact = calculate_impact(corridor_name, risk_score, duration_days=14)
        print(f"  ✓ {corridor_name}: shortfall={impact['shortfall_bpd']:,.0f} bpd, "
              f"reserve stress in {impact['days_to_reserve_stress']} days")

        doc_id = safe_doc_id(corridor_name)
        impact_batch.set(db.collection("scenario_impact").document(doc_id), impact)

        # 2. Rank reroute options for this shortfall
        recs = rank_reroute_options(
            shortfall_bpd=impact["shortfall_bpd"],
            corridor_affected=corridor_name,
            urgency_days=min(7, impact["days_to_reserve_stress"]),
        )
        rec_batch.set(db.collection("recommendations").document(doc_id), recs)

        # Print the actual recommendation, not just a confirmation —
        # this is the part a procurement officer (or a judge) actually
        # wants to see.
        print(f"\n  📋 RECOMMENDATION for {corridor_name}:")
        print(f"     {recs['executive_summary']}\n")
        print(f"     Top ranked alternatives:")
        for opt in recs["options"][:5]:
            print(
                f"       {opt['rank_score']:.2f}  {opt['supplier_country']:<28} "
                f"via {opt['route']:<45} "
                f"{opt['volume_bpd_available']:>9,} bpd, "
                f"{opt['lead_time_days']:>2.0f}d lead, "
                f"${opt['freight_cost_usd_per_bbl']:.2f}/bbl, "
                f"{opt['grade_compatibility']} grade"
            )
        print()

        actioned_count += 1

    impact_batch.commit()
    rec_batch.commit()

    print(f"\n✓ Wrote impact + recommendations for {actioned_count} corridor(s) to Firebase.")
    print("  Frontend should read /scenario_impact and /recommendations for these.")

    # Final readable summary — the "so what" of the whole run, useful for demo
    if actioned_count > 0:
        print("\n" + "=" * 70)
        print("SUMMARY — WHAT TO DO RIGHT NOW")
        print("=" * 70)
        for c in corridors:
            corridor_name = c["corridor"]
            if c["risk_score"] < RISK_THRESHOLD_FOR_ACTION:
                continue
            doc = db.collection("recommendations").document(safe_doc_id(corridor_name)).get()
            if doc.exists:
                data = doc.to_dict()
                top = data["options"][0] if data["options"] else None
                print(f"\n⚠  {corridor_name} (risk {c['risk_score']})")
                if top:
                    print(f"   → Reroute to {top['supplier_country']} via {top['route']}")
                    print(f"     ({top['volume_bpd_available']:,} bpd available, {top['lead_time_days']:.0f}-day lead time)")
        print("\n" + "=" * 70)


if __name__ == "__main__":
    run_pipeline()