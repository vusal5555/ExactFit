from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from utils.database import get_db
import io
import csv
from fastapi.responses import StreamingResponse
from agents.research_agent import research_all_sources
from agents.enrichment_agent import enrich_leads


router = APIRouter()

db = get_db()


class LeadCreate(BaseModel):
    company_name: str
    domain: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    job_title: Optional[str] = None
    sources: List[str] = []


class LeadResponse(BaseModel):
    id: str
    company_name: str
    domain: Optional[str]
    contact_email: Optional[str]
    score: int
    intent_tier: int
    status: str


class FindLeadsRequest(BaseModel):
    icp: str
    target_role: str = "VP Sales"
    include_yc: bool = True
    include_producthunt: bool = True
    include_funding: bool = True


class ResponseModel(BaseModel):
    leads: List[LeadResponse]
    count: int


@router.get("/leads", response_model=ResponseModel)
def get_leads(tier: Optional[int] = None, status: Optional[str] = None):

    query = db.table("leads").select("*").order("score", desc=True)

    if tier:
        query = query.eq("intent_tier", tier)
    if status:
        query = query.eq("status", status)

    result = query.execute()
    return {"leads": result.data, "count": len(result.data)}


@router.post("/leads")
def create_lead(lead: LeadCreate):
    result = (
        db.table("leads")
        .insert(
            {
                "company_name": lead.company_name,
                "domain": lead.domain,
                "contact_email": lead.contact_email,
                "contact_name": lead.contact_name,
                "job_title": lead.job_title,
                "sources": lead.sources,
                "status": "discovered",
            }
        )
        .execute()
    )

    return {"lead": result.data[0], "message": "Lead created"}


@router.get("/leads/{lead_id}")
def get_lead(lead_id: str):
    result = db.table("leads").select("*").eq("id", lead_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    return {"lead": result.data[0]}


@router.post("/find-leads")
def find_leads(request: FindLeadsRequest):
    """
    Find leads based on ICP.
    Returns companies with buying signals + contact info.
    """

    # Step 1: Research all sources
    research_result = research_all_sources(
        icp=request.icp,
        include_yc=request.include_yc,
        include_ph=request.include_producthunt,
        include_funding=request.include_funding,
    )

    companies = research_result["companies"]

    # Step 2: Enrich with emails
    enrichment_result = enrich_leads(companies, target_job_title=request.target_role)
    leads = enrichment_result["enriched_leads"]

    # Step 3: Format output
    output = []
    for lead in leads:
        output.append(
            {
                "company": lead.get("company_name"),
                "domain": lead.get("domain"),
                "signal_type": lead.get("signal_type"),
                "signal": lead.get("signal_detail"),
                "contact_name": lead.get("contact_name"),
                "contact_email": lead.get("contact_email"),
                "contact_title": lead.get("contact_title"),
                "source_url": lead.get("source_url", ""),
            }
        )

    return {
        "leads": output,
        "count": len(output),
        "sources": research_result["by_source"],
        "stats": enrichment_result["stats"],
    }


@router.post("/find-leads/csv")
def find_leads_csv(request: FindLeadsRequest):
    """
    Find leads and return as CSV download.
    """

    result = find_leads(request)
    leads = result["leads"]

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "company",
            "domain",
            "signal_type",
            "signal",
            "contact_name",
            "contact_email",
            "contact_title",
            "source_url",
        ],
    )

    writer.writeheader()
    for lead in leads:
        writer.writerow(lead)

    output.seek(0)

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )
