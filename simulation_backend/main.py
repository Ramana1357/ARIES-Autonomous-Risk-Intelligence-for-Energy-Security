from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Project ARIES - Simulation API")

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DisruptionPayload(BaseModel):
    disruption_pct: float

@app.post("/api/simulate")
async def simulate_disruption(payload: DisruptionPayload):
    # India's Strategic Petroleum Reserve (SPR) baseline in days
    baseline_days = 9.5
    
    # Simple hackathon-grade math: subtract disruption impact from baseline
    # If disruption_pct is 20, we reduce the reserve "safety margin" by 20%
    impact = baseline_days * (payload.disruption_pct / 100.0)
    remaining_days = max(0, baseline_days - impact)
    
    return {
        "status": "success",
        "baseline_days": baseline_days,
        "disruption_pct": payload.disruption_pct,
        "remaining_days": round(remaining_days, 2),
        "impact_severity": "HIGH" if payload.disruption_pct > 20 else "MODERATE" if payload.disruption_pct > 5 else "LOW"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
