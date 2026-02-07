from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from agents.scoring_agent import score_leads
from utils.database import get_db

router = APIRouter()
db = get_db()


class CustomerConfig(BaseModel):
    competitors: Optional[List[str]] = []
    target_tools: Optional[List[str]] = []
    target_job_title: Optional[str] = None
    min_signals: Optional[int] = 1
    min_score: Optional[int] = 0


class ScoreRequest(BaseModel):
    lead_ids: Optional[List[str]] = None
    score_all: bool = False
    customer_config: Optional[CustomerConfig] = None


@router.post("/score")
def run_scoring(request: ScoreRequest):
    """
    Score leads based on intent signals.

    Args:
        lead_ids: Specific leads to score
        score_all: Or score all enriched leads
        customer_config: Customer's ICP settings
            - competitors: Tools they compete with
            - target_tools: Tools their ideal customers use
            - target_job_title: Role they want to reach
            - min_signals: Minimum signals to qualify
            - min_score: Minimum score to qualify
    """

    # Get leads from database
    if request.score_all:
        result = db.table("leads").select("*").eq("status", "enriched").execute()
    elif request.lead_ids:
        result = db.table("leads").select("*").in_("id", request.lead_ids).execute()
    else:
        raise HTTPException(
            status_code=400, detail="Provide lead_ids or set score_all=True"
        )

    leads = result.data

    if not leads:
        return {"message": "No leads to score", "scored": 0}

    # Convert customer config to dict
    config = {}
    if request.customer_config:
        config = request.customer_config.model_dump()

    # Run scoring
    scoring_result = score_leads(leads, customer_config=config)

    # Update database with scores
    updated_count = 0
    for lead in scoring_result["scored_leads"]:
        lead_id = lead.get("id")

        if not lead_id:
            continue

        update_data = {
            "status": "scored",
            "score": lead.get("score", 0),
            "tier": lead.get("tier", "cold"),
            "signal_count": lead.get("signal_count", 0),
            "signals": lead.get("signals", []),
            "talking_points": lead.get("talking_points", []),
            "sample_opener": lead.get("sample_opener", ""),
            "detected_tools": lead.get("detected_tools", []),
        }

        try:
            db.table("leads").update(update_data).eq("id", lead_id).execute()
            updated_count += 1
        except Exception as e:
            print(f"Failed to update lead {lead_id}: {e}")

    return {
        "message": "Scoring complete",
        "stats": scoring_result["stats"],
        "scored_count": updated_count,
        "reddit_signals": len(scoring_result.get("reddit_signals", [])),
    }


@router.get("/score/leads")
def get_scored_leads(
    tier: Optional[str] = None, min_score: Optional[int] = None, limit: int = 50
):
    """
    Get scored leads, optionally filtered by tier or minimum score.

    Args:
        tier: Filter by tier (hot, warm, cold)
        min_score: Minimum score to return
        limit: Max results
    """

    query = db.table("leads").select("*").eq("status", "scored")

    if tier:
        query = query.eq("tier", tier)

    if min_score:
        query = query.gte("score", min_score)

    query = query.order("score", desc=True).limit(limit)

    result = query.execute()

    return {"leads": result.data, "count": len(result.data)}


@router.get("/score/stats")
def get_scoring_stats():
    """Get scoring statistics."""

    result = db.table("leads").select("status, score, tier").execute()

    stats = {
        "total": 0,
        "scored": 0,
        "by_tier": {"hot": 0, "warm": 0, "cold": 0},
        "avg_score": 0,
    }

    scores = []

    for lead in result.data:
        stats["total"] += 1

        if lead.get("status") == "scored":
            stats["scored"] += 1

            tier = lead.get("tier", "cold")
            if tier in stats["by_tier"]:
                stats["by_tier"][tier] += 1

            if lead.get("score"):
                scores.append(lead["score"])

    if scores:
        stats["avg_score"] = round(sum(scores) / len(scores), 1)

    return stats
