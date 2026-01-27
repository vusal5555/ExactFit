from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from agents.research_agent import research_icp
from utils.database import get_db

router = APIRouter()
db = get_db()


class ResearchRequest(BaseModel):
    icp: str


class CompanyResult(BaseModel):
    company_name: str
    domain: str
    source_url: str
    signal_type: str
    signal_detail: str
    status: str
    score: int


class ResearchResponse(BaseModel):
    icp: str
    total_found: int
    companies: List[CompanyResult]
    queries_used: List[str]
    errors: List[str]


@router.post("/research", response_model=ResearchResponse)
def run_research(request: ResearchRequest):
    """
    Run the Research Agent on an ICP.
    Returns companies with buying intent signals.

    """
    if not request.icp or len(request.icp) < 5:
        raise HTTPException(status_code=400, detail="ICP must be at least 5 characters")

    try:
        result = research_icp(request.icp)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Research agent error: {str(e)}")


@router.post("/research/save")
def research_and_save(request: ResearchRequest):
    """
    Run Research Agent and save results to Supabase.

    """
    if not request.icp or len(request.icp) < 5:
        raise HTTPException(status_code=400, detail="ICP must be at least 5 characters")

    try:
        result = research_icp(request.icp)

        saved_count = 0
        for company in result["companies"]:
            db.table("leads").insert(
                {
                    "company_name": company["company_name"],
                    "domain": company["domain"],
                    "sources": [company["source_url"]],
                    "status": "discovered",
                    "score": 0,
                    "raw_data": {
                        "signal_type": company["signal_type"],
                        "signal_detail": company["signal_detail"],
                        "icp": request.icp,
                    },
                }
            ).execute()
            saved_count += 1
        return {
            "message": f"Research complete. Saved {saved_count} leads.",
            "icp": request.icp,
            "total_found": result["total_found"],
            "saved": saved_count,
            "errors": result["errors"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Research agent error: {str(e)}")
