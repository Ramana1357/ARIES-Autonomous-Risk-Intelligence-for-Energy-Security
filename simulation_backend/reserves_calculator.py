"""
ARIES Simulation Backend — reserves_calculator.py  (Member 2)

Job: turn a corridor's risk score (from Member 1's Firebase data) into
concrete numbers: how many barrels/day are at risk, what price impact
to expect, and how many days until India's strategic reserves are
stressed if the disruption continues.

This is plain math — no LLM needed here. The judgment calls (elasticity
assumption, risk-to-capacity-loss mapping) are simplifications clearly
marked below; that's normal and fine to say out loud in a hackathon demo.

Run standalone for testing:
    python reserves_calculator.py
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Simplified price elasticity assumption for the prototype:
# every 1% of India's total crude imports lost pushes price up by this
# many USD/bbl. NOT a real econometric model — say so in the demo.
PRICE_IMPACT_USD_PER_PCT_SHORTFALL = 1.4


def load_json(filename):
    with open(DATA_DIR / filename) as f:
        return json.load(f)


def risk_score_to_capacity_loss_pct(risk_score: float) -> float:
    """
    Converts a 0-1 risk score (from Member 1's Firebase data) into an
    assumed % of corridor capacity lost. This is the simplification that
    connects "how dangerous is it" to "how much oil actually stops flowing."

    Simple prototype mapping: risk_score below 0.5 -> minimal capacity loss,
    scales up sharply above 0.7 to represent a corridor nearing closure.
    """
    if risk_score < 0.5:
        return risk_score * 20          # 0.0-0.5 -> 0-10% loss
    elif risk_score < 0.7:
        return 10 + (risk_score - 0.5) * 100   # 0.5-0.7 -> 10-30% loss
    else:
        return 30 + (risk_score - 0.7) * 233   # 0.7-1.0 -> 30-100% loss


def calculate_impact(corridor: str, risk_score: float, duration_days: int = 14) -> dict:
    """
    Core calculation. Given a corridor and its current risk score, returns
    the full impact: shortfall, price delta, days to reserve stress, and
    which refineries are exposed.
    """
    corridors = load_json("corridors.json")
    refineries = load_json("refineries.json")
    reserves = load_json("reserves.json")

    corridor_info = next((c for c in corridors if c["corridor"] == corridor), None)
    if corridor_info is None:
        raise ValueError(f"Unknown corridor: {corridor}")

    capacity_loss_pct = risk_score_to_capacity_loss_pct(risk_score)

    national_consumption_bpd = reserves["national_daily_consumption_bpd"]
    corridor_pct_of_imports = corridor_info["pct_of_india_crude_imports"] / 100.0

    volume_at_risk_bpd = national_consumption_bpd * corridor_pct_of_imports
    shortfall_bpd = volume_at_risk_bpd * (capacity_loss_pct / 100.0)
    shortfall_pct_of_total_imports = (shortfall_bpd / national_consumption_bpd) * 100.0

    estimated_price_delta = shortfall_pct_of_total_imports * PRICE_IMPACT_USD_PER_PCT_SHORTFALL

    reserve_barrels = reserves["total_capacity_barrels"] * (reserves["current_fill_pct"] / 100.0)
    days_to_reserve_stress = reserve_barrels / shortfall_bpd if shortfall_bpd > 0 else float("inf")

    affected_refineries = [
        r["name"] for r in refineries if r["primary_crude_source_corridor"] == corridor
    ]

    return {
        "corridor": corridor,
        "risk_score": risk_score,
        "assumed_capacity_loss_pct": round(capacity_loss_pct, 1),
        "duration_days": duration_days,
        "shortfall_bpd": round(shortfall_bpd, 0),
        "shortfall_pct_of_total_imports": round(shortfall_pct_of_total_imports, 2),
        "estimated_price_delta_usd": round(estimated_price_delta, 2),
        "days_to_reserve_stress": round(days_to_reserve_stress, 1),
        "affected_refineries": affected_refineries,
    }


if __name__ == "__main__":
    # Quick manual test — simulates a high-risk Hormuz scenario
    result = calculate_impact("Strait of Hormuz", risk_score=0.82, duration_days=14)
    print(json.dumps(result, indent=2))
