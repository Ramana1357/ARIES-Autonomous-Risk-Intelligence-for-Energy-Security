"""
ARIES Simulation Backend — reroute_algorithm.py  (Member 2)

Job: given a shortfall (from reserves_calculator.py) and the disrupted
corridor, rank alternate suppliers/routes that DON'T depend on that
corridor, so procurement teams know where to buy oil instead.

Run standalone for testing:
    python reroute_algorithm.py
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

GRADE_SCORE = {"high": 1.0, "medium": 0.6, "low": 0.3}


def load_suppliers():
    with open(DATA_DIR / "suppliers.json") as f:
        return json.load(f)


def score_option(supplier: dict, urgency_days: float) -> float:
    """
    Weighted score: favors low lead time, low freight cost, high grade match.
    Tune the weights (0.4 / 0.3 / 0.3) if you want to prioritize differently.
    """
    lead_time_score = max(0.0, 1.0 - (supplier["lead_time_days"] / 30.0))
    cost_score = max(0.0, 1.0 - (supplier["freight_cost_usd_per_bbl"] / 4.0))
    grade_score = GRADE_SCORE.get(supplier["grade_compatibility"], 0.5)

    # Penalize suppliers that can't deliver inside the urgency window
    urgency_penalty = 1.0 if supplier["lead_time_days"] <= urgency_days else 0.5

    score = (0.4 * lead_time_score + 0.3 * cost_score + 0.3 * grade_score) * urgency_penalty
    return round(score, 3)


def rank_reroute_options(shortfall_bpd: float, corridor_affected: str, urgency_days: float = 7) -> dict:
    """
    Main entry point. Returns ranked reroute options plus an executive
    summary string, given a shortfall and the corridor that's disrupted.
    """
    suppliers = load_suppliers()

    # Exclude suppliers who depend on the SAME corridor that's disrupted —
    # no point suggesting a reroute that goes through the same chokepoint.
    viable = [s for s in suppliers if s["depends_on_corridor"] != corridor_affected]

    options = []
    for s in viable:
        options.append({
            "supplier_country": s["supplier_country"],
            "route": s["route"],
            "volume_bpd_available": s["typical_volume_bpd"],
            "lead_time_days": s["lead_time_days"],
            "freight_cost_usd_per_bbl": s["freight_cost_usd_per_bbl"],
            "grade_compatibility": s["grade_compatibility"],
            "rank_score": score_option(s, urgency_days),
            "rationale": (
                f"{s['grade_compatibility'].capitalize()} grade match, "
                f"{s['lead_time_days']}-day lead time, does not transit "
                f"the disrupted corridor."
            ),
        })

    options.sort(key=lambda o: o["rank_score"], reverse=True)

    summary = generate_executive_summary(options, shortfall_bpd, corridor_affected)

    return {
        "corridor_affected": corridor_affected,
        "shortfall_bpd": shortfall_bpd,
        "urgency_days": urgency_days,
        "options": options,
        "executive_summary": summary,
    }


def generate_executive_summary(options: list, shortfall_bpd: float, corridor: str) -> str:
    if not options:
        return f"No viable reroute options found to cover the {shortfall_bpd:,.0f} bpd shortfall from {corridor}."

    top = options[0]
    covered = min(top["volume_bpd_available"], shortfall_bpd)
    pct_covered = (covered / shortfall_bpd * 100) if shortfall_bpd else 0

    summary = (
        f"To cover the {shortfall_bpd:,.0f} bpd shortfall from {corridor}, prioritize "
        f"{top['supplier_country']} via {top['route']} — covering an estimated {pct_covered:.0f}% "
        f"of the gap within {top['lead_time_days']:.0f} days at ~${top['freight_cost_usd_per_bbl']:.2f}/bbl "
        f"freight."
    )

    remaining = shortfall_bpd - covered
    if remaining > 0 and len(options) > 1:
        second = options[1]
        summary += (
            f" Blend with {second['supplier_country']} via {second['route']} to cover the "
            f"remaining ~{remaining:,.0f} bpd."
        )

    return summary


if __name__ == "__main__":
    # Quick manual test — matches the Hormuz scenario from reserves_calculator.py
    result = rank_reroute_options(
        shortfall_bpd=728000,  # example number, plug in real output from reserves_calculator
        corridor_affected="Strait of Hormuz",
        urgency_days=7,
    )
    print(json.dumps(result, indent=2))
